"""Lazy channel-day profiles and targeted historical anomaly quarantine."""

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class QualityThresholds:
    """Cutoffs for observable channel-day technical anomalies."""

    min_burst_events: int = 100
    max_repeats_per_second: int = 25
    max_event_rate_deviation: float = 10.0
    min_stuck_run: int = 100


def profile_channel_days(events: pl.LazyFrame) -> pl.LazyFrame:
    """Summarize each channel/day against its preceding channel-day history."""
    keys = ["channel_id", "day"]
    dated = events.with_columns(pl.col("registered_at").dt.date().alias("day"))
    counts = dated.group_by(keys).agg(
        pl.len().alias("event_count"),
        pl.col("alarm_flag").cast(pl.Int64).sum().alias("alarm_count"),
        pl.col("raw_value").n_unique().alias("unique_values"),
    )
    repeats = (
        dated.with_columns(
            pl.col("registered_at").dt.truncate("1s").alias("_event_second")
        )
        .group_by([*keys, "_event_second"])
        .agg(pl.len().alias("_repeats"))
        .group_by(keys)
        .agg(pl.col("_repeats").max().alias("max_repeats_per_second"))
    )
    ordered = dated.sort([*keys, "registered_at", "event_id"])
    state_changed = (
        (pl.col("raw_value") != pl.col("raw_value").shift(1).over(keys))
        | (pl.col("alarm_flag") != pl.col("alarm_flag").shift(1).over(keys))
    ).fill_null(True)
    runs = (
        ordered.with_columns(state_changed.cast(pl.Int64).alias("_state_changed"))
        .with_columns(pl.col("_state_changed").cum_sum().over(keys).alias("_run_id"))
        .group_by([*keys, "_run_id"])
        .agg(pl.len().alias("_run_length"))
        .group_by(keys)
        .agg(pl.col("_run_length").max().alias("longest_identical_state_run"))
    )
    profiles = counts.join(repeats, on=keys).join(runs, on=keys)
    profiles = profiles.with_columns(
        (pl.col("alarm_count") / pl.col("event_count")).alias("alarm_share")
    ).sort(keys)
    profiles = profiles.with_columns(
        pl.col("event_count")
        .shift(1)
        .rolling_median(window_size=30, min_samples=1)
        .over("channel_id")
        .alias("historical_median_event_count")
    )
    return profiles.with_columns(
        (pl.col("event_count") / pl.col("historical_median_event_count")).alias(
            "event_rate_deviation"
        )
    )


def mark_historical_artifacts(
    events: pl.LazyFrame,
    profiles: pl.LazyFrame,
    thresholds: QualityThresholds,
) -> pl.LazyFrame:
    """Attach per-event channel-day flags, quarantining anomalous 2021 intervals."""
    keys = ["channel_id", "day"]
    joined = events.with_columns(pl.col("registered_at").dt.date().alias("day")).join(
        profiles, on=keys, how="left"
    )
    burst = (pl.col("event_count") >= thresholds.min_burst_events) & (
        (pl.col("max_repeats_per_second") >= thresholds.max_repeats_per_second)
        | (pl.col("event_rate_deviation") >= thresholds.max_event_rate_deviation)
    )
    stuck = pl.col("longest_identical_state_run") >= thresholds.min_stuck_run
    joined = joined.with_columns(
        burst.fill_null(False).alias("burst"),
        stuck.fill_null(False).alias("stuck"),
    ).with_columns(
        (
            (pl.col("registered_at").dt.year() == 2021)
            & (pl.col("burst") | pl.col("stuck"))
        ).alias("historical_artifact")
    )
    joined = joined.with_columns(
        pl.col("historical_artifact").alias("exclude_from_fire_training")
    )
    if "quality_flags" not in events.collect_schema().names():
        joined = joined.with_columns(
            pl.lit([], dtype=pl.List(pl.String)).alias("quality_flags")
        )
    for flag in ("burst", "stuck", "historical_artifact"):
        joined = joined.with_columns(
            pl.when(pl.col(flag))
            .then(pl.concat_list("quality_flags", pl.lit([flag])))
            .otherwise(pl.col("quality_flags"))
            .alias("quality_flags")
        )
    return joined.drop("day")
