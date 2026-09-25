"""Atomic, identity-checked two-pass preparation of immutable source journals."""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from fire_risk.config import PipelineConfig
from fire_risk.contracts import ChannelReference, IncidentEpisode
from fire_risk.data.calibration import (
    calibrate_thresholds,
    read_calibration,
    write_calibration,
)
from fire_risk.data.csv_reader import partition_events
from fire_risk.data.device_metadata import DeviceAgeConfig, estimate_device_metadata
from fire_risk.data.episodes import build_episodes
from fire_risk.data.features import attach_horizon_targets, build_feature_snapshots
from fire_risk.data.inventory import build_object_inventory
from fire_risk.data.labels import (
    PROXY_RULE_VERSION,
    ProxyLabelConfig,
    ProxyLabelProvider,
)
from fire_risk.data.normalize import normalize_value
from fire_risk.data.pickets import parse_picket
from fire_risk.data.quality import (
    mark_historical_artifacts,
    profile_channel_days,
)
from fire_risk.data.references import (
    build_coverage_report,
    join_channels,
    load_state_index,
    scan_channel_reference,
)
from fire_risk.data.run_report import build_full_run_report

_NORMALIZED_TYPE = pl.Struct(
    {
        "value_kind": pl.String,
        "numeric_value": pl.Float64,
        "state_code": pl.String,
        "normalization_rule": pl.String,
        "_alarm": pl.Boolean,
        "_value_flags": pl.List(pl.String),
    }
)
_PICKET_TYPE = pl.Struct(
    {
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
        "rule_id": pl.String(),
        "episode_id": pl.String(),
        "sensor_combination": pl.List(pl.String()),
    }
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=_json_default,
        allow_nan=False,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_bytes((_json(value) + "\n").encode("utf-8"))


def _implementation_revision() -> dict[str, str]:
    override = os.environ.get("FIRE_RISK_IMPLEMENTATION_REVISION", "").strip()
    if override:
        return {
            "implementation_revision": override,
            "implementation_revision_source": "environment",
        }
    repository = next(
        (
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / ".git").exists()
        ),
        None,
    )
    if repository is not None:
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
        return {
            "value_kind": value.kind.value,
            "numeric_value": value.numeric_value,
            "state_code": value.state_code,
            "normalization_rule": value.rule_code,
            "_alarm": value.alarm_flag,
            "_value_flags": value.quality_flags,
        }

    def locate(name: str | None) -> dict[str, Any]:
        picket = parse_picket(name or "")
        return {
            "picket_raw": picket.raw,
            "picket_sort_key": picket.sort_key,
            "location_group": picket.location_group,
        }

    # Materialize only distinct lookups through the streaming engine. Keeping
    # these branches in the event query lets common-subplan reuse multiplex the
    # entire source while joins wait for their lookup builds to finish. Resolve
    # the small cardinality-bound tables first, then stream the event side once.
    value_keys = ["sensor_type", "raw_value"]
    values = (
        events.select(value_keys)
        .unique()
        .with_columns(
            pl.struct(value_keys)
            .map_elements(normalize, return_dtype=_NORMALIZED_TYPE)
            .alias("_normalized")
        )
        .unnest("_normalized")
        .collect(engine="streaming")
        .lazy()
    )
    locations = (
        events.select("sensor_name")
        .unique()
        .with_columns(
            pl.col("sensor_name")
            .map_elements(locate, return_dtype=_PICKET_TYPE, skip_nulls=False)
            .alias("_picket")
        )
        .unnest("_picket")
        .collect(engine="streaming")
        .lazy()
    )
    return (
        # Both right sides are unique by construction. Explicit m:1 validation
        # forces an in-memory join in Polars 1.33; retain streaming equi-joins.
        events.join(
            values,
            on=value_keys,
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
        .join(
            locations,
            on="sensor_name",
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
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
        # Resolve one row per channel before probing the event stream; a shared
        # source multiplexer would otherwise retain events during aggregation.
        .collect(engine="streaming")
        .lazy()
    )
    return events.join(metadata, on="channel_id", how="left", maintain_order="left")


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


SCHEMA_VERSION = "fire-risk-data-v2"
STAGES = (
    "00-source-inventory.json",
    "10-channel-day-profiles.parquet",
    "20-calibrated-thresholds.json",
    "30-normalized-events.parquet",
    "31-object-inventory.parquet",
    "32-object-inventory-by-type.parquet",
    "40-episodes.parquet",
    "41-episode-membership.parquet",
    "50-incident-labels.parquet",
    "60-feature-snapshots.parquet",
    "70-coverage.json",
    "71-quality-report.json",
    "72-run-report.json",
    "manifest.json",
)
_ALIASES = {
    "normalized_events.parquet": STAGES[3],
    "inventory_totals.parquet": STAGES[4],
    "inventory_by_type.parquet": STAGES[5],
    "episodes.parquet": STAGES[6],
    "episode_membership.parquet": STAGES[7],
    "incident_labels.parquet": STAGES[8],
    "feature_snapshots.parquet": STAGES[9],
    "coverage.json": STAGES[10],
    "quality_report.json": STAGES[11],
    "run_report.json": STAGES[12],
}


@dataclass(frozen=True)
class FullRunConfig:
    events: tuple[Path, ...]
    channels: Path
    states: Path
    output: Path
    temp_dir: Path
    run_id: str
    observed_until: datetime
    settings: PipelineConfig = field(default_factory=PipelineConfig)
    source_timezone: str = "Europe/Moscow"
    seed: int = 0
    device_as_of: date = date(2026, 9, 24)
    quality_thresholds: Path | None = None
    resume: bool = True
    schema_version: str = SCHEMA_VERSION
    implementation_revision: str | None = None


@dataclass(frozen=True)
class RunResult:
    directory: Path
    run_identity: str
    reused_stages: tuple[str, ...]
    built_stages: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _configuration(config: FullRunConfig) -> dict[str, Any]:
    return {
        "pipeline": config.settings.model_dump(),
        "source_timezone": config.source_timezone,
        "device_metadata": asdict(DeviceAgeConfig(as_of=config.device_as_of)),
        "device_seed": config.seed,
        "proxy_rule_version": PROXY_RULE_VERSION,
        "label_observed_until": config.observed_until.isoformat(),
        "calibration_mode": "frozen" if config.quality_thresholds else "train_only",
    }


def compute_run_identity(
    config: FullRunConfig, source_hashes: Mapping[str, str]
) -> str:
    return _identity(
        {
            "sources": dict(source_hashes),
            "configuration": _configuration(config),
            "implementation_revision": config.implementation_revision
            or _implementation_revision()["implementation_revision"],
            "schema_version": config.schema_version,
            "polars_version": pl.__version__,
        }
    )


def _atomic_write(path: Path, writer: Callable[[Path], object]) -> None:
    """Close and fsync a sibling before replacement; never unlink the old output."""
    with NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        writer(temporary)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StageStore:
    """Sequential dependency chain: one invalid stage invalidates its successors."""

    def __init__(
        self, directory: Path, *, resume: bool, schema_version: str = SCHEMA_VERSION
    ) -> None:
        self.directory = directory
        self.resume = resume
        self.schema_version = schema_version
        self.reused_stages: list[str] = []
        self.built_stages: list[str] = []
        self.records: dict[str, dict[str, Any]] = {}
        self._previous: dict[str, Any] | None = None
        self._invalidated = not resume

    def run(self, name: str, inputs: object, writer: Callable[[Path], object]) -> Path:
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Stage name must be a single filename")
        path = self.directory / name
        marker = self.directory / f"{name}.complete.json"
        identity = _identity({"inputs": inputs, "previous": self._previous})
        record: dict[str, Any] = {}
        if not self._invalidated:
            try:
                candidate = json.loads(marker.read_text(encoding="utf-8"))
                if (
                    isinstance(candidate, dict)
                    and candidate.get("stage") == name
                    and candidate.get("input_identity") == identity
                    and candidate.get("schema_version") == self.schema_version
                    and isinstance(candidate.get("statistics"), dict)
                    and candidate.get("output_sha256") == sha256_file(path)
                ):
                    record = candidate
            except (OSError, ValueError, TypeError):
                pass
        if record:
            self.reused_stages.append(name)
        else:
            self._invalidated = True
            marker.unlink(missing_ok=True)
            (self.directory / "manifest.json.complete.json").unlink(missing_ok=True)
            _atomic_write(path, writer)
            statistics = (
                {"row_count": pl.scan_parquet(path).select(pl.len()).collect().item()}
                if path.suffix == ".parquet"
                else {}
            )
            record = {
                "stage": name,
                "input_identity": identity,
                "output_sha256": sha256_file(path),
                "schema_version": self.schema_version,
                "statistics": statistics,
            }
            _atomic_write(marker, lambda target: _write_json(target, record))
            self.built_stages.append(name)
        self.records[name] = record
        self._previous = record
        return path


def _run_directory(config: FullRunConfig) -> Path:
    run_id = config.run_id
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id)
        or run_id.endswith((".", " "))
        or re.fullmatch(
            r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", run_id, re.IGNORECASE
        )
    ):
        raise ValueError("run-id must be one non-reserved Windows-safe path component")
    root = config.output.resolve()
    directory = (root / run_id).resolve()
    if directory.parent != root or directory.name != run_id:
        raise ValueError("run-id resolves outside output or aliases another directory")
    return directory


def _journal_year(path: Path) -> int | None:
    match = re.search(r"(?:^|[-_])(20\d{2})(?:$|[-_])", path.stem)
    return int(match[1]) if match else None


@contextmanager
def _temporary_space(directory: Path) -> Iterator[Path]:
    """Own all sanitation spools and route Polars streaming spill to the caller."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("POLARS_TEMP_DIR")
    os.environ["POLARS_TEMP_DIR"] = str(directory)
    try:
        with TemporaryDirectory(prefix="fire-risk-", dir=directory) as path:
            yield Path(path)
    finally:
        if previous is None:
            os.environ.pop("POLARS_TEMP_DIR", None)
        else:
            os.environ["POLARS_TEMP_DIR"] = previous


def _coverage_json(events: pl.LazyFrame, config: FullRunConfig) -> dict[str, Any]:
    coverage = build_coverage_report(events, config.channels, config.states)
    return {
        "total_events": coverage.total_events,
        "unknown_channel_events": coverage.unknown_channel_events,
        "conflicting_state_events": sum(coverage.conflicting_type_value_pairs.values()),
        **{
            name: [
                {"sensor_type": sensor, "raw_value": value, "event_count": count}
                for (sensor, value), count in sorted(
                    pairs.items(), key=lambda item: (item[0][0] or "", item[0][1] or "")
                )
            ]
            for name, pairs in [
                ("unmapped_type_value_pairs", coverage.unmapped_type_value_pairs),
                ("conflicting_type_value_pairs", coverage.conflicting_type_value_pairs),
            ]
        },
    }


def _quality_json(
    normalized: pl.LazyFrame, quarantined: pl.LazyFrame, coverage: dict[str, Any]
) -> dict[str, Any]:
    reasons = dict(quarantined.group_by("quality_reason").len().collect().iter_rows())
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
        .collect()
        .row(0, named=True)
    )
    quality.update(
        {
            "invalid_timestamp_rows": reasons.get("invalid_timestamp", 0),
            "malformed_input_rows": sum(reasons.values()),
            "input_quality_reasons": reasons,
            "quarantined_rows": sum(reasons.values())
            + quality["excluded_from_fire_training_rows"],
            "unknown_channel_events": coverage["unknown_channel_events"],
            "conflicting_state_events": coverage["conflicting_state_events"],
        }
    )
    return quality


def _publish_alias(source: Path, target: Path) -> None:
    if target.exists() and sha256_file(source) == sha256_file(target):
        return

    def link_or_copy(temporary: Path) -> None:
        # Both names are generated files on the same output volume. Replacing
        # either name later leaves the other inode intact until it is refreshed.
        temporary.unlink()
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copyfile(source, temporary)

    _atomic_write(target, link_or_copy)


def run_full(config: FullRunConfig) -> RunResult:
    """Hash inputs, run train-only pass 1 (or import frozen JSON), then pass 2.

    The temp/output locations are operational, not identity inputs. No wall-clock
    value, resume status or timing statistic enters stage identities or reports.
    Concurrent writers to the same run directory are unsupported.
    """
    directory = _run_directory(config)
    if not config.events:
        raise ValueError("At least one event journal is required")
    if (
        config.observed_until.tzinfo is None
        or config.observed_until.utcoffset() is None
    ):
        raise ValueError("label-observed-until must be timezone-aware")
    timezone = ZoneInfo(config.source_timezone)
    if (
        config.settings.scoring_step_minutes <= 0
        or config.settings.episode_gap_minutes < 0
    ):
        raise ValueError("scoring step must be positive and episode gap non-negative")
    revision = (
        {
            "implementation_revision": config.implementation_revision,
            "implementation_revision_source": "explicit",
        }
        if config.implementation_revision
        else _implementation_revision()
    )
    config = replace(
        config, implementation_revision=revision["implementation_revision"]
    )
    journals = sorted({path.resolve() for path in config.events}, key=str)
    if len(journals) != len(config.events):
        raise ValueError("Duplicate event journal paths")
    records = [("events", path) for path in journals] + [
        ("channels", config.channels.resolve()),
        ("states", config.states.resolve()),
    ]
    sources = [path for _, path in records]
    if config.quality_thresholds is not None:
        sources.append(config.quality_thresholds.resolve())
    if any(path.is_relative_to(directory) for path in sources):
        raise ValueError("Source files must be outside the run output directory")
    before = {str(path): sha256_file(path) for path in sources}
    source_records = [
        {
            "role": role,
            "filename": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": before[str(path)],
        }
        for role, path in records
    ]
    train = [path for path in journals if 2019 <= (_journal_year(path) or 0) <= 2024]
    if config.quality_thresholds is None and (
        not train
        or any(_journal_year(path) not in range(2019, 2027) for path in journals)
    ):
        raise ValueError(
            "Calibration requires journals named ext-journal-YYYY.csv (2019-2026) and train sources"
        )
    run_identity = compute_run_identity(config, before)
    directory.mkdir(parents=True, exist_ok=True)
    store = StageStore(
        directory, resume=config.resume, schema_version=config.schema_version
    )
    started_at = datetime.now(UTC)
    with _temporary_space(config.temp_dir) as temp:
        parsed: dict[Path, tuple[pl.LazyFrame, pl.LazyFrame]] = {}

        def partitions(paths: list[Path]) -> tuple[pl.LazyFrame, pl.LazyFrame]:
            for path in paths:
                if path not in parsed:
                    valid, bad = partition_events([path], temp_dir=temp)
                    if (year := _journal_year(path)) is not None:
                        valid = valid.with_columns(
                            pl.lit(year, dtype=pl.Int32).alias("source_year")
                        )
                        bad = bad.with_columns(
                            pl.lit(year, dtype=pl.Int32).alias("source_year")
                        )
                    parsed[path] = valid, bad
            return tuple(
                pl.concat([parsed[path][index] for path in paths]) for index in (0, 1)
            )  # type: ignore[return-value]

        def normalized_input(paths: list[Path]) -> pl.LazyFrame:
            valid, _ = partitions(paths)
            local = join_channels(valid, config.channels).with_columns(
                pl.col("registered_at").dt.replace_time_zone(config.source_timezone)
            )
            return _normalize_events(local, config.states, config.settings)

        store.run(
            STAGES[0],
            source_records,
            lambda path: _write_json(
                path,
                {
                    "schema_version": config.schema_version,
                    "sources": source_records,
                },
            ),
        )
        normalization_config = config.settings.model_dump(
            exclude={"scoring_step_minutes", "episode_gap_minutes"}
        )
        profile_inputs = {
            "normalization": normalization_config,
            "source_timezone": config.source_timezone,
            "implementation_revision": config.implementation_revision,
            "polars_version": pl.__version__,
        }

        def write_profiles(path: Path) -> None:
            if train:
                # Do not derive calibration membership from any proposed or
                # static quality cutoffs. No established exclusions are supplied.
                profiles = profile_channel_days(
                    normalized_input(train), temp_dir=temp / "train-profiles"
                ).with_columns(
                    pl.lit(False).alias("historical_artifact"),
                    pl.lit(False).alias("exclude_from_fire_training"),
                )
            else:
                profiles = pl.DataFrame(
                    schema={
                        "channel_id": pl.String,
                        "day": pl.Date,
                        "source_year": pl.Int32,
                        "event_count": pl.UInt32,
                        "max_repeats_per_second": pl.UInt32,
                        "longest_identical_state_run": pl.UInt32,
                        "event_rate_deviation": pl.Float64,
                        "historical_artifact": pl.Boolean,
                        "exclude_from_fire_training": pl.Boolean,
                    }
                ).lazy()
            profiles.sort(["channel_id", "day", "source_year"]).sink_parquet(path)

        profile_path = store.run(STAGES[1], profile_inputs, write_profiles)

        def write_thresholds(path: Path) -> None:
            if config.quality_thresholds:
                frozen = read_calibration(config.quality_thresholds)
            else:
                train_hashes = {str(path): before[str(path)] for path in train}
                train_hashes.update(
                    {
                        str(path): before[str(path)]
                        for _, path in records
                        if path not in journals
                    }
                )
                frozen = calibrate_thresholds(
                    pl.scan_parquet(profile_path),
                    train_hashes,
                    config.seed,
                    implementation_revision=config.implementation_revision,
                )
            write_calibration(path, frozen)

        frozen_path = store.run(
            STAGES[2],
            {
                "seed": config.seed,
                "frozen_source_sha256": before.get(
                    str(config.quality_thresholds.resolve())
                )
                if config.quality_thresholds
                else None,
            },
            write_thresholds,
        )
        # Always load the persisted artifact, including the first execution.
        calibration = read_calibration(frozen_path)
        thresholds = calibration.thresholds
        effective_config = {
            **_configuration(config),
            "quality_thresholds": asdict(thresholds),
            "quality_calibration": calibration.to_dict(),
        }

        def write_normalized(path: Path) -> None:
            normalized = normalized_input(journals)
            # This post-freeze profile pass cannot feed stage 20. Persist compact
            # profiles before joining flags to avoid buffering the event probe
            # while a shared full-corpus aggregation waits to finish.
            application_profile_path = temp / "application-profiles.parquet"
            profile_channel_days(
                normalized, temp_dir=temp / "application-profiles"
            ).sink_parquet(application_profile_path)
            normalized = _attach_device_metadata(
                normalized, DeviceAgeConfig(as_of=config.device_as_of), config.seed
            )
            normalized = mark_historical_artifacts(
                normalized, pl.scan_parquet(application_profile_path), thresholds
            )
            # Consumers impose their own chronological/object ordering. Keep
            # deterministic source order here instead of sorting the wide corpus.
            normalized.with_columns(
                pl.col("registered_at").dt.convert_time_zone("UTC")
            ).sink_parquet(path)

        normalized_path = store.run(
            STAGES[3], {"device_as_of": config.device_as_of}, write_normalized
        )
        normalized = pl.scan_parquet(normalized_path)
        for index in (4, 5):

            def write_inventory(path: Path, index: int = index) -> None:
                build_object_inventory(scan_channel_reference(config.channels))[
                    index - 4
                ].sink_parquet(path)

            store.run(STAGES[index], {}, write_inventory)

        episode_products: tuple[pl.LazyFrame, pl.LazyFrame] | None = None

        def episodes_and_membership() -> tuple[pl.LazyFrame, pl.LazyFrame]:
            nonlocal episode_products
            if episode_products is None:
                episode_products = build_episodes(
                    normalized,
                    timedelta(minutes=config.settings.episode_gap_minutes),
                    methane_alarm_percent=config.settings.methane_alarm_percent,
                    temp_dir=temp / "episode-products",
                )
            return episode_products

        episode_path = store.run(
            STAGES[6],
            {"gap_minutes": config.settings.episode_gap_minutes},
            lambda path: episodes_and_membership()[0].sink_parquet(path),
        )
        store.run(
            STAGES[7], {}, lambda path: episodes_and_membership()[1].sink_parquet(path)
        )
        label_path = store.run(
            STAGES[8],
            {
                "proxy_rule_version": PROXY_RULE_VERSION,
                "observed_until": config.observed_until,
            },
            lambda path: _proxy_labels(
                pl.scan_parquet(episode_path), config.observed_until
            ).sink_parquet(path),
        )

        def write_features(path: Path) -> None:
            local_events = normalized.with_columns(
                pl.col("registered_at").dt.convert_time_zone(config.source_timezone)
            )
            local_labels = pl.scan_parquet(label_path).with_columns(
                pl.col("started_at", "ended_at").dt.convert_time_zone(
                    config.source_timezone
                )
            )
            features = build_feature_snapshots(
                local_events,
                config.settings,
                scan_channel_reference(config.channels),
                thresholds=thresholds,
            )
            attach_horizon_targets(
                features, local_labels, config.observed_until.astimezone(timezone)
            ).with_columns(
                pl.col("scoring_timestamp").dt.convert_time_zone("UTC")
            ).sink_parquet(path)

        feature_path = store.run(
            STAGES[9],
            {"scoring_step_minutes": config.settings.scoring_step_minutes},
            write_features,
        )
        coverage_path = store.run(
            STAGES[10],
            {},
            lambda path: _write_json(
                path, _coverage_json(partitions(journals)[0], config)
            ),
        )
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        quality_path = store.run(
            STAGES[11],
            {},
            lambda path: _write_json(
                path, _quality_json(normalized, partitions(journals)[1], coverage)
            ),
        )
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        store.run(
            STAGES[12],
            {"run_identity": run_identity},
            lambda path: _write_json(
                path,
                {
                    **build_full_run_report(
                        normalized,
                        partitions(journals)[1],
                        pl.scan_parquet(label_path),
                        pl.scan_parquet(feature_path),
                        coverage=coverage,
                        quality=quality,
                        calibration=calibration.to_dict(),
                        source_hashes=before,
                        source_timezone=config.source_timezone,
                        seed=config.seed,
                        implementation_revision=config.implementation_revision
                        or "unknown",
                        run_identity=run_identity,
                    ),
                    "profile_passes": {
                        "calibration_source_years": sorted(
                            {_journal_year(path) for path in train}
                        ),
                        "application_source_years": sorted(
                            {_journal_year(path) for path in journals}
                        ),
                        "application_uses_frozen_thresholds": True,
                        "event_partition": "source_timezone_month_then_day",
                    },
                },
            ),
        )
        after = {str(path): sha256_file(path) for path in sources}
        if before != after:
            (directory / "manifest.json.complete.json").unlink(missing_ok=True)
            raise ValueError(
                "Source hashes changed during run; manifest was not completed"
            )
        row_counts = {
            alias.removesuffix(".parquet"): store.records[name]["statistics"][
                "row_count"
            ]
            for alias, name in _ALIASES.items()
            if alias.endswith(".parquet")
        }
        store.run(
            STAGES[13],
            {"run_identity": run_identity},
            lambda path: _write_json(
                path,
                {
                    "schema_version": config.schema_version,
                    "run_id": config.run_id,
                    "run_identity": run_identity,
                    "sources": source_records,
                    "configuration": effective_config,
                    "config_hash": _identity(effective_config),
                    "source_sha256_before": before,
                    "source_sha256_after": after,
                    "started_at": started_at,
                    "completed_at": datetime.now(UTC),
                    "row_counts": row_counts,
                    "polars_version": pl.__version__,
                    "stages": dict(store.records),
                    **revision,
                },
            ),
        )
        for alias, name in _ALIASES.items():
            _publish_alias(directory / name, directory / alias)
    return RunResult(
        directory, run_identity, tuple(store.reused_stages), tuple(store.built_stages)
    )
