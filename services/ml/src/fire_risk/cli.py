"""Reproducible, versioned preparation of source journals and training rows."""

import json
import os
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from fire_risk.config import PipelineConfig
from fire_risk.contracts import ChannelReference, IncidentEpisode
from fire_risk.data.csv_reader import partition_events
from fire_risk.data.device_metadata import DeviceAgeConfig, estimate_device_metadata
from fire_risk.data.episodes import build_episodes
from fire_risk.data.features import attach_horizon_targets, build_feature_snapshots
from fire_risk.data.inventory import build_object_inventory
from fire_risk.data.labels import ProxyLabelConfig, ProxyLabelProvider
from fire_risk.data.normalize import normalize_value
from fire_risk.data.pickets import parse_picket
from fire_risk.data.quality import (
    QualityThresholds,
    mark_historical_artifacts,
    profile_channel_days,
)
from fire_risk.data.references import (
    build_coverage_report,
    join_channels,
    load_state_index,
    scan_channel_reference,
)

app = typer.Typer(no_args_is_help=True)

_NORMALIZED_TYPE = pl.Struct(
    {
        "value_kind": pl.String,
        "numeric_value": pl.Float64,
        "state_code": pl.String,
        "normalization_rule": pl.String,
        "_alarm": pl.Boolean,
        "_value_flags": pl.List(pl.String),
        "picket_raw": pl.String,
        "picket_sort_key": pl.Float64,
        "location_group": pl.String,
    }
)
_DEVICE_TYPE = pl.Struct(
    {
        "estimated_install_date": pl.Date,
        "estimated_age_years": pl.Float64,
        "age_source": pl.String,
        "is_synthetic": pl.Boolean,
    }
)
_LABEL_SCHEMA = pl.Schema(
    {
        "incident_id": pl.String(),
        "object_id": pl.String(),
        "started_at": pl.Datetime("us", "UTC"),
        "ended_at": pl.Datetime("us", "UTC"),
        "incident_type": pl.String(),
        "decision": pl.String(),
        "confirmed_at": pl.Datetime("us", "UTC"),
        "source": pl.String(),
        "confidence": pl.Float64(),
        "rule_version": pl.String(),
    }
)


@app.callback()
def main() -> None:
    """Prepare immutable source journals into versioned model inputs."""


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(_json(value) + "\n", encoding="utf-8")


def _implementation_revision() -> dict[str, str]:
    override = os.environ.get("FIRE_RISK_IMPLEMENTATION_REVISION", "").strip()
    if override:
        return {
            "implementation_revision": override,
            "implementation_revision_source": "environment",
        }
    repository = Path(__file__).resolve().parents[4]
    if (repository / ".git").exists():
        try:
            revision = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={repository.as_posix()}",
                    "rev-parse",
                    "--verify",
                    "HEAD",
                ],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            return {
                "implementation_revision": revision,
                "implementation_revision_source": "git_head",
            }
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "implementation_revision": "unknown",
        "implementation_revision_source": "unavailable",
    }


def _normalize_events(
    events: pl.LazyFrame, states: Path, config: PipelineConfig
) -> pl.LazyFrame:
    # References are small, explicit materialization boundaries. Journals stay lazy.
    index = load_state_index(states)

    def normalize(row: dict[str, Any]) -> dict[str, Any]:
        value = normalize_value(
            row["sensor_type"] or "", row["raw_value"] or "", index, config
        )
        picket = parse_picket(row["sensor_name"] or "")
        return {
            "value_kind": value.kind.value,
            "numeric_value": value.numeric_value,
            "state_code": value.state_code,
            "normalization_rule": value.rule_code,
            "_alarm": value.alarm_flag,
            "_value_flags": value.quality_flags,
            "picket_raw": picket.raw,
            "picket_sort_key": picket.sort_key,
            "location_group": picket.location_group,
        }

    return (
        events.with_columns(
            pl.struct("sensor_type", "raw_value", "sensor_name")
            .map_elements(normalize, return_dtype=_NORMALIZED_TYPE)
            .alias("_normalized")
        )
        .unnest("_normalized")
        .with_columns(
            pl.col("alarm_flag").alias("source_alarm_flag"),
            (
                pl.coalesce("_alarm", "alarm_flag")
                | pl.col("_value_flags").list.contains("methane_alarm")
            ).alias("alarm_flag"),
            pl.concat_list("quality_flags", "_value_flags").alias("quality_flags"),
        )
        .drop("_alarm", "_value_flags")
    )


def _attach_device_metadata(
    events: pl.LazyFrame, config: DeviceAgeConfig, seed: int
) -> pl.LazyFrame:
    fields = list(ChannelReference.model_fields)
    first_seen = (
        events.filter(pl.col("object_id").is_not_null())
        .group_by("channel_id")
        .agg(
            pl.col("registered_at").min().dt.date().alias("first_seen"),
            *[pl.col(name).first() for name in fields if name != "channel_id"],
        )
    )

    def estimate(row: dict[str, Any]) -> dict[str, Any]:
        metadata = estimate_device_metadata(
            ChannelReference.model_validate({key: row[key] for key in fields}),
            row["first_seen"],
            seed,
            config,
        )
        return {
            key: value for key, value in asdict(metadata).items() if key != "channel_id"
        }

    metadata = (
        first_seen.with_columns(
            pl.struct(*fields, "first_seen")
            .map_elements(estimate, return_dtype=_DEVICE_TYPE)
            .alias("_device")
        )
        .select("channel_id", "_device")
        .unnest("_device")
    )
    return events.join(metadata, on="channel_id", how="left")


def _proxy_labels(episodes: pl.LazyFrame, observed_until: datetime) -> pl.LazyFrame:
    def label_batch(batch: pl.DataFrame) -> pl.DataFrame:
        labels: list[dict[str, Any]] = []
        for chunk in batch.iter_slices(10_000):
            records = [
                IncidentEpisode.model_validate(row)
                for row in chunk.iter_rows(named=True)
            ]
            if not records:
                continue
            provider = ProxyLabelProvider(
                ProxyLabelConfig(episodes=records, observed_until=observed_until)
            )
            labels.extend(
                label.model_dump()
                for label in provider.get_incidents(
                    min(ep.started_at for ep in records),
                    max(ep.started_at for ep in records) + timedelta(microseconds=1),
                    {ep.object_id for ep in records},
                )
            )
        return pl.DataFrame(labels, schema=_LABEL_SCHEMA)

    return episodes.map_batches(
        label_batch,
        schema=_LABEL_SCHEMA,
        streamable=True,
        predicate_pushdown=False,
        projection_pushdown=False,
        slice_pushdown=False,
    ).sort(["object_id", "started_at", "incident_id"])


@app.command()
def prepare(
    events: Annotated[
        list[Path],
        typer.Option(exists=True, dir_okay=False, help="Repeat for each journal CSV."),
    ],
    channels: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    states: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option()],
    run_id: Annotated[str, typer.Option()],
    label_observed_until: Annotated[
        str, typer.Option(help="Confirmed label coverage end (ISO-8601 with timezone).")
    ],
    config: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    source_timezone: Annotated[
        str, typer.Option(help="Timezone of naive source timestamps.")
    ] = "UTC",
    device_seed: Annotated[int, typer.Option()] = 0,
    device_as_of: Annotated[str, typer.Option()] = "2026-09-24",
) -> None:
    """Write one run directory; repeating identical inputs reproduces its data."""
    try:
        observed_until = datetime.fromisoformat(label_observed_until)
    except ValueError as exc:
        raise typer.BadParameter(
            "label-observed-until must be an ISO-8601 datetime",
            param_hint="--label-observed-until",
        ) from exc
    if observed_until.tzinfo is None or observed_until.utcoffset() is None:
        raise typer.BadParameter(
            "label-observed-until must be timezone-aware",
            param_hint="--label-observed-until",
        )
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id)
        or run_id.endswith((".", " "))
        or re.fullmatch(
            r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", run_id, re.IGNORECASE
        )
    ):
        raise typer.BadParameter(
            "run-id must be one non-reserved Windows-safe path component without a trailing dot or space"
        )
    root = output.resolve()
    directory = (root / run_id).resolve()
    if directory.parent != root or directory.name != run_id:
        raise typer.BadParameter(
            "run-id resolves outside output or aliases another directory name"
        )
    settings = (
        PipelineConfig.model_validate_json(config.read_text(encoding="utf-8"))
        if config
        else PipelineConfig()
    )
    if settings.scoring_step_minutes <= 0 or settings.episode_gap_minutes < 0:
        raise typer.BadParameter(
            "scoring step must be positive and episode gap non-negative"
        )
    age_config = DeviceAgeConfig(as_of=date.fromisoformat(device_as_of))
    thresholds = QualityThresholds()
    effective_config = {
        "pipeline": settings.model_dump(),
        "source_timezone": source_timezone,
        "device_metadata": asdict(age_config),
        "device_seed": device_seed,
        "quality_thresholds": asdict(thresholds),
        "proxy_rule_version": "smvu-proxy-v1",
        "label_observed_until": observed_until.isoformat(),
    }
    started_at = datetime.now(UTC)
    directory.mkdir(parents=True, exist_ok=True)
    journals = sorted(events, key=lambda path: str(path.resolve()))
    source_records = [
        {
            "role": role,
            "filename": path.name,
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
        }
        for role, path in [("events", path) for path in journals]
        + [("channels", channels), ("states", states)]
    ]
    valid, quarantined = partition_events(journals)
    coverage = build_coverage_report(valid, channels, states)
    coverage_json = {
        "total_events": coverage.total_events,
        "unknown_channel_events": coverage.unknown_channel_events,
        "conflicting_state_events": sum(coverage.conflicting_type_value_pairs.values()),
        **{
            name: [
                {"sensor_type": sensor, "raw_value": value, "event_count": count}
                for (sensor, value), count in sorted(
                    pairs.items(),
                    key=lambda item: (
                        item[0][0] or "",
                        item[0][1] is not None,
                        item[0][1] or "",
                    ),
                )
            ]
            for name, pairs in [
                ("unmapped_type_value_pairs", coverage.unmapped_type_value_pairs),
                ("conflicting_type_value_pairs", coverage.conflicting_type_value_pairs),
            ]
        },
    }
    joined = join_channels(valid, channels).with_columns(
        pl.col("registered_at")
        .dt.replace_time_zone(source_timezone)
        .dt.convert_time_zone("UTC")
    )
    normalized = _normalize_events(joined, states, settings)
    normalized = _attach_device_metadata(normalized, age_config, device_seed)
    normalized = mark_historical_artifacts(
        normalized, profile_channel_days(normalized), thresholds
    )
    normalized.sort(["registered_at", "event_id"]).sink_parquet(
        directory / "normalized_events.parquet"
    )
    normalized = pl.scan_parquet(directory / "normalized_events.parquet")
    episodes, membership = build_episodes(
        normalized, timedelta(minutes=settings.episode_gap_minutes)
    )
    episodes.sink_parquet(directory / "episodes.parquet")
    membership.sink_parquet(directory / "episode_membership.parquet")
    episodes = pl.scan_parquet(directory / "episodes.parquet")
    _proxy_labels(episodes, observed_until).sink_parquet(
        directory / "incident_labels.parquet"
    )
    labels = pl.scan_parquet(directory / "incident_labels.parquet")
    inventory = scan_channel_reference(channels)
    inventory_totals, inventory_by_type = build_object_inventory(inventory)
    inventory_totals.sink_parquet(directory / "inventory_totals.parquet")
    inventory_by_type.sink_parquet(directory / "inventory_by_type.parquet")
    attach_horizon_targets(
        build_feature_snapshots(normalized, settings, inventory), labels, observed_until
    ).sink_parquet(directory / "feature_snapshots.parquet")
    input_quality_reasons = {
        reason: count
        for reason, count in quarantined.group_by("quality_reason")
        .len()
        .collect(engine="streaming")
        .iter_rows()
    }
    malformed = sum(input_quality_reasons.values())
    quality = (
        normalized.select(
            pl.len().alias("normalized_rows"),
            *[
                pl.col(flag).sum().alias(f"{flag}_rows")
                for flag in ("stuck", "burst", "historical_artifact")
            ],
            pl.col("exclude_from_fire_training")
            .sum()
            .alias("excluded_from_fire_training_rows"),
        )
        .collect(engine="streaming")
        .row(0, named=True)
    )
    quality.update(
        {
            "invalid_timestamp_rows": input_quality_reasons.get("invalid_timestamp", 0),
            "malformed_input_rows": malformed,
            "input_quality_reasons": input_quality_reasons,
            "quarantined_rows": malformed + quality["excluded_from_fire_training_rows"],
            "unknown_channel_events": coverage.unknown_channel_events,
            "conflicting_state_events": sum(
                coverage.conflicting_type_value_pairs.values()
            ),
        }
    )
    row_counts = {
        name: pl.scan_parquet(directory / f"{name}.parquet")
        .select(pl.len())
        .collect(engine="streaming")
        .item()
        for name in (
            "normalized_events",
            "episodes",
            "episode_membership",
            "incident_labels",
            "feature_snapshots",
            "inventory_totals",
            "inventory_by_type",
        )
    }
    _write_json(directory / "coverage.json", coverage_json)
    _write_json(directory / "quality_report.json", quality)
    _write_json(
        directory / "manifest.json",
        {
            "schema_version": "fire-risk-data-v1",
            "run_id": run_id,
            "sources": source_records,
            "configuration": effective_config,
            "config_hash": sha256(_json(effective_config).encode("utf-8")).hexdigest(),
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
            "row_counts": row_counts,
            "polars_version": pl.__version__,
            **_implementation_revision(),
        },
    )
    typer.echo(f"Prepared {directory}")


if __name__ == "__main__":
    app()
