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


def causal_quality_flags(
    events: pl.LazyFrame, thresholds: QualityThresholds
) -> pl.LazyFrame:
    """Replace retrospective day flags with flags observable at each event.

    Consumes the profiled normalized table. The historical median refers only
    to completed preceding days; all current-day statistics use prefixes.
    Rows remain flagged from the first detected anomaly through that day.
    Retain retrospective stuck as baseline_stuck, usable only once that day
    is complete; it must never enter current-day/window features.
    """
    flags = ("burst", "stuck", "historical_artifact")
    original = events.collect_schema().names()
    keys = ["channel_id", "_causal_day"]
    ordered = events.with_columns(
        pl.col("stuck").alias("baseline_stuck"),
        pl.col("registered_at").dt.date().alias("_causal_day"),
        pl.col("registered_at").dt.truncate("1s").alias("_causal_second"),
    ).sort([*keys, "registered_at", "event_id"])
    changed = (
        (pl.col("raw_value") != pl.col("raw_value").shift(1).over(keys))
        | (pl.col("alarm_flag") != pl.col("alarm_flag").shift(1).over(keys))
    ).fill_null(True)
    prefixes = (
        ordered.with_columns(changed.cast(pl.Int64).alias("_causal_changed"))
        .with_columns(
            pl.col("event_id").cum_count().over(keys).alias("_seen"),
            pl.col("event_id")
            .cum_count()
            .over([*keys, "_causal_second"])
            .alias("_repeats_seen"),
            pl.col("_causal_changed").cum_sum().over(keys).alias("_causal_run"),
        )
        .with_columns(
            pl.col("event_id")
            .cum_count()
            .over([*keys, "_causal_run"])
            .alias("_run_seen")
        )
        .with_columns(
            pl.col("_repeats_seen").cum_max().over(keys).alias("_max_repeats_seen"),
            pl.col("_run_seen").cum_max().over(keys).alias("_longest_run_seen"),
        )
    )
    result = (
        prefixes.with_columns(
            (
                (pl.col("_seen") >= thresholds.min_burst_events)
                & (
                    (pl.col("_max_repeats_seen") >= thresholds.max_repeats_per_second)
                    | (
                        (pl.col("_seen") / pl.col("historical_median_event_count"))
                        >= thresholds.max_event_rate_deviation
                    )
                )
            )
            .fill_null(False)
            .alias("burst"),
            (pl.col("_longest_run_seen") >= thresholds.min_stuck_run).alias("stuck"),
            pl.col("quality_flags")
            .list.eval(pl.element().filter(~pl.element().is_in(flags)))
            .alias("quality_flags"),
        )
        .with_columns(
            (
                (pl.col("registered_at").dt.year() == 2021)
                & (pl.col("burst") | pl.col("stuck"))
            ).alias("historical_artifact")
        )
        .with_columns(pl.col("historical_artifact").alias("exclude_from_fire_training"))
    )
    for flag in flags:
        result = result.with_columns(
            pl.when(pl.col(flag))
            .then(pl.concat_list("quality_flags", pl.lit([flag])))
            .otherwise(pl.col("quality_flags"))
            .alias("quality_flags")
        )
    return result.select(*original, "baseline_stuck")
