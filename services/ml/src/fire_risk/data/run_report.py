"""Deterministic label statistics; feature names describe overlap, never labels."""

from collections.abc import Mapping, Sequence
from typing import Any

import polars as pl

from fire_risk.contracts import IncidentLabel
from fire_risk.data.labels import PROXY_RULE_VERSION

_FEATURE_FAMILY_TOKENS = {
    "gas": {"gas", "methane"},
    "heat": {"heat", "temperature"},
    "manual": {"manual"},
    "pump": {"pump"},
    "smoke": {"smoke"},
    "uir": {"uir"},
}


def build_label_report(
    labels: Sequence[IncidentLabel] | pl.LazyFrame,
    targets: pl.DataFrame | pl.LazyFrame,
    feature_columns: Sequence[str],
    *,
    source_timezone: str = "UTC",
) -> dict[str, object]:
    """Summarize proxy incidents and available target classes for all horizons.

    Target column names match attach_horizon_targets (target_now/6h/12h/24h).
    Censored rows never enter class balance. No feature values are accepted or
    consulted, and all insertion orders are deterministic for JSON serialization.
    """
    label_schema = pl.Schema(
        {
            "source": pl.String(),
            "rule_version": pl.String(),
            "object_id": pl.String(),
            "rule_id": pl.String(),
            "sensor_combination": pl.List(pl.String),
            "started_at": pl.Datetime("us", "UTC"),
        }
    )
    label_frame = (
        labels
        if isinstance(labels, pl.LazyFrame)
        else pl.DataFrame(
            [
                {key: label.model_dump()[key] for key in label_schema}
                for label in labels
            ],
            schema=label_schema,
        ).lazy()
    )
    proxy = label_frame.filter(pl.col("source") == "proxy").with_columns(
        pl.col("rule_version", "rule_id").fill_null("unspecified"),
        pl.col("sensor_combination").list.unique().list.sort(),
        pl.col("started_at")
        .dt.convert_time_zone(source_timezone)
        .dt.year()
        .cast(pl.String)
        .alias("year"),
    )
    versions = (
        proxy.select("rule_version")
        .unique()
        .sort("rule_version")
        .collect()["rule_version"]
        .to_list()
    )

    def grouped_counts(column: str) -> dict[str, int]:
        return dict(proxy.group_by(column).len().sort(column).collect().iter_rows())

    frame = targets.lazy() if isinstance(targets, pl.DataFrame) else targets
    statistics = (
        frame.select(
            pl.len().alias("total"),
            *[
                expression.alias(f"{horizon}_{name}")
                for horizon in ("12h", "24h", "6h", "now")
                for name, expression in {
                    "available": pl.col(f"target_{horizon}_available").sum(),
                    "positive": (
                        pl.col(f"target_{horizon}_available")
                        & pl.col(f"target_{horizon}")
                    ).sum(),
                    "negative": (
                        pl.col(f"target_{horizon}_available")
                        & ~pl.col(f"target_{horizon}")
                    ).sum(),
                }.items()
            ],
        )
        .collect()
        .row(0, named=True)
    )
    counts: dict[str, object] = {}
    balance: dict[str, object] = {}
    for horizon in ("12h", "24h", "6h", "now"):
        available = statistics[f"{horizon}_available"]
        positive = statistics[f"{horizon}_positive"]
        negative = statistics[f"{horizon}_negative"]
        counts[horizon] = {
            "available": available,
            "censored": statistics["total"] - available,
            "negative": negative,
            "positive": positive,
        }
        balance[horizon] = {
            "negative": negative,
            "positive": positive,
            "positive_share": positive / available if available else None,
        }
    combinations = proxy.group_by("sensor_combination").len().collect().rows()
    shared_columns = {
        family: sorted(
            {
                column
                for column in feature_columns
                if tokens.intersection(column.casefold().replace("-", "_").split("_"))
            }
        )
        for family, tokens in _FEATURE_FAMILY_TOKENS.items()
    }
    return {
        "class_balance": balance,
        "feature_rule_overlap": {
            "feature_columns_by_family": shared_columns,
            "proxy_signal_families": sorted(_FEATURE_FAMILY_TOKENS),
            "shared_signal_families": [
                family for family, columns in shared_columns.items() if columns
            ],
        },
        "proxy_incidents": {
            "by_object": grouped_counts("object_id"),
            "by_rule": grouped_counts("rule_id"),
            "by_sensor_combination": [
                {"count": count, "sensor_combination": list(combination)}
                for combination, count in sorted(combinations)
            ],
            "by_year": grouped_counts("year"),
            "total": proxy.select(pl.len()).collect().item(),
        },
        "proxy_rule_version": versions[0]
        if len(versions) == 1
        else ("mixed" if versions else PROXY_RULE_VERSION),
        "proxy_rule_versions": versions,
        "targets": counts,
        "warning": (
            "WARNING: proxy metrics measure reproduction of reconstructed labels, "
            "not detection quality for confirmed real fires. Feature/rule signal "
            "overlap can inflate agreement with proxy labels."
        ),
    }


def build_full_run_report(
    events: pl.LazyFrame,
    quarantined: pl.LazyFrame,
    labels: pl.LazyFrame,
    targets: pl.LazyFrame,
    *,
    coverage: Mapping[str, Any],
    quality: Mapping[str, Any],
    calibration: Mapping[str, Any],
    source_hashes: Mapping[str, str],
    source_timezone: str,
    seed: int,
    implementation_revision: str,
    run_identity: str,
) -> dict[str, Any]:
    """Aggregate on disk; only small grouped tables enter the JSON report."""
    accepted = events.group_by("source_year").agg(
        (~pl.col("exclude_from_fire_training")).sum().alias("accepted"),
        pl.col("exclude_from_fire_training").sum().alias("quarantined"),
    )
    rejected = quarantined.group_by("source_year").agg(
        pl.lit(0, dtype=pl.UInt32).alias("accepted"), pl.len().alias("quarantined")
    )
    rows = (
        pl.concat([accepted, rejected], how="vertical_relaxed")
        .group_by("source_year")
        .agg(pl.col("accepted").sum(), pl.col("quarantined").sum())
        .sort("source_year")
        .collect()
    )
    unknown = events.filter(pl.col("value_kind") == "unknown")
    unknown_counts = (
        unknown.select(
            pl.len().alias("events"),
            pl.struct("sensor_type", "raw_value").n_unique().alias("pairs"),
        )
        .collect()
        .row(0, named=True)
    )
    unknown_counts.update(
        {
            "conflicting_events": coverage["conflicting_state_events"],
            "conflicting_pairs": len(coverage["conflicting_type_value_pairs"]),
        }
    )
    excluded = events.filter(
        (pl.col("source_year") == 2021) & pl.col("exclude_from_fire_training")
    ).with_columns(
        pl.col("registered_at")
        .dt.convert_time_zone(source_timezone)
        .dt.date()
        .alias("day"),
        pl.col("quality_flags")
        .list.eval(
            pl.element().filter(
                pl.element().is_in(["burst", "stuck", "historical_artifact"])
            )
        )
        .alias("reasons"),
    )
    intervals = (
        excluded.group_by("channel_id", "day")
        .agg(
            pl.len().alias("rows"),
            pl.col("reasons").explode().unique().sort(),
        )
        .sort("channel_id", "day")
        .collect()
        .to_dicts()
    )
    by_reason = dict(
        excluded.select("reasons")
        .explode("reasons")
        .group_by("reasons")
        .len()
        .sort("reasons")
        .collect()
        .iter_rows()
    )
    total, unknown_channels = (
        coverage["total_events"],
        coverage["unknown_channel_events"],
    )
    return {
        "schema_version": "fire-risk-run-report-v2",
        "run_identity": run_identity,
        "rows_by_source_year": {
            str(row["source_year"]) if row["source_year"] is not None else "unknown": {
                "accepted": row["accepted"],
                "quarantined": row["quarantined"],
            }
            for row in rows.iter_rows(named=True)
        },
        "channel_object_coverage": {
            "matched_events": total - unknown_channels,
            "unknown_events": unknown_channels,
            "coverage_percent": 100.0 * (total - unknown_channels) / total
            if total
            else None,
        },
        "unknown_states": unknown_counts,
        "excluded_2021": {
            "pre_calibration_intervals": [],
            "pre_calibration_rows": 0,
            "pre_calibration_reason": "No pre-established channel-day exclusion annotations supplied",
            "intervals": intervals,
            "rows": sum(row["rows"] for row in intervals),
            "rows_by_reason": by_reason,
        },
        "quality_calibration": dict(calibration),
        "quality": dict(quality),
        "source_sha256": dict(source_hashes),
        "source_timezone": source_timezone,
        "seed": seed,
        "implementation_revision": implementation_revision,
        **build_label_report(
            labels,
            targets,
            targets.collect_schema().names(),
            source_timezone=source_timezone,
        ),
    }
