"""Lazy, history-only object snapshots; incident targets attach separately."""

import polars as pl

from fire_risk.config import PipelineConfig

_WINDOWS = ("5m", "30m", "3h", "6h", "24h")
_KEYS = ["object_id", "scoring_timestamp"]
_CATEGORIES = {
    "smoke": ["smoke", "датчик дыма"],
    "heat": ["heat", "датчик температуры"],
    "gas": ["gas", "газовый датчик"],
    "manual": ["manual_call_point", "ручной извещатель"],
    "uir": ["uir-r", "уир-р"],
    "pump": ["pump", "насос"],
}


def _feature_events(events: pl.LazyFrame) -> pl.LazyFrame:
    names = events.collect_schema().names()
    optional = {
        "numeric_value": pl.lit(None, dtype=pl.Float64),
        "value_kind": pl.lit(None, dtype=pl.String),
        "quality_flags": pl.lit([], dtype=pl.List(pl.String)),
    }
    events = events.with_columns(
        expr.alias(name) for name, expr in optional.items() if name not in names
    )
    return events.filter(
        pl.col("object_id").is_not_null() & pl.col("registered_at").is_not_null()
    ).select(
        "object_id",
        "registered_at",
        "channel_id",
        "sensor_type",
        "alarm_flag",
        pl.col("numeric_value").cast(pl.Float64),
        "value_kind",
        (
            pl.col("baseline_stuck").fill_null(False)
            if "baseline_stuck" in names
            else pl.col("quality_flags").list.contains("stuck").fill_null(False)
            | (pl.col("stuck").fill_null(False) if "stuck" in names else pl.lit(False))
        ).alias("_baseline_stuck"),
        *[
            (
                pl.col("quality_flags").list.contains(flag).fill_null(False)
                | (pl.col(flag).fill_null(False) if flag in names else pl.lit(False))
            ).alias(flag)
            for flag in ("stuck", "burst", "historical_artifact")
        ],
        *[
            pl.col("sensor_type")
            .str.strip_chars()
            .str.to_lowercase()
            .is_in(values)
            .fill_null(False)
            .alias(f"_{category}")
            for category, values in _CATEGORIES.items()
        ],
        pl.lit(True).alias("_event"),
        pl.lit(False).alias("_snapshot"),
    )


def _window_features(window: str, config: PipelineConfig) -> list[pl.Expr]:
    event = pl.col("_event").fill_null(False)
    alarm = event & pl.col("alarm_flag").fill_null(False)
    gas = event & pl.col("_gas")
    heat = event & pl.col("_heat")
    smoke_alarm = (alarm & pl.col("_smoke")).any()
    expressions = {
        "event_count": event.sum().cast(pl.Int64),
        "alarm_count": alarm.sum().cast(pl.Int64),
        "unique_channels": pl.col("channel_id")
        .filter(event)
        .drop_nulls()
        .n_unique()
        .cast(pl.Int64),
        "unique_sensor_types": pl.col("sensor_type")
        .filter(event)
        .drop_nulls()
        .n_unique()
        .cast(pl.Int64),
        "malfunction_count": (event & (pl.col("value_kind") == "malfunction"))
        .sum()
        .cast(pl.Int64),
        "gas_max": pl.col("numeric_value").filter(gas).max(),
        "gas_mean": pl.col("numeric_value").filter(gas).mean(),
        "gas_alarm_count": (
            gas & (pl.col("numeric_value") >= config.methane_alarm_percent)
        )
        .sum()
        .cast(pl.Int64),
        "temperature_max": pl.col("numeric_value").filter(heat).max(),
        "temperature_mean": pl.col("numeric_value").filter(heat).mean(),
        **{
            f"{flag}_count": (event & pl.col(flag)).sum().cast(pl.Int64)
            for flag in ("stuck", "burst", "historical_artifact")
        },
        **{
            f"smoke_{category}": smoke_alarm & (alarm & pl.col(f"_{category}")).any()
            for category in ("heat", "manual", "uir")
        },
        "pump_alarm": (alarm & pl.col("_pump")).any(),
    }
    return [expr.alias(f"{name}_{window}") for name, expr in expressions.items()]


def build_feature_snapshots(
    events: pl.LazyFrame, config: PipelineConfig
) -> pl.LazyFrame:
    """Build a per-object grid from floor(first event) to ceil(last event).

    Windows are (t - window, t]. Empty grid intervals have zero counts and
    null numeric summaries. Baselines average observed, eligible completed
    days; stuck events are omitted. Weekday uses ISO numbering (Monday = 1).
    No incident, label, or whole-day profile columns enter this computation.
    """
    if config.scoring_step_minutes <= 0:
        raise ValueError("scoring_step_minutes must be positive")
    source = _feature_events(events)
    step = f"{config.scoring_step_minutes}m"
    bounds = (
        source.group_by("object_id")
        .agg(
            pl.col("registered_at").min().dt.truncate(step).alias("_start"),
            pl.col("registered_at").max().alias("_last"),
        )
        .with_columns(
            pl.when(pl.col("_last") == pl.col("_last").dt.truncate(step))
            .then(pl.col("_last"))
            .otherwise(pl.col("_last").dt.truncate(step).dt.offset_by(step))
            .alias("_end")
        )
    )
    grid = (
        bounds.select(
            "object_id",
            pl.datetime_ranges("_start", "_end", interval=step).alias("registered_at"),
        )
        .explode("registered_at")
        .filter(pl.col("registered_at").is_not_null())
    )
    markers = grid.with_columns(
        pl.lit(True).alias("_snapshot"), pl.lit(False).alias("_event")
    )
    timeline = pl.concat([source, markers], how="diagonal").sort(
        ["object_id", "registered_at", "_snapshot"]
    )
    result = grid.rename({"registered_at": "scoring_timestamp"})
    for window in _WINDOWS:
        rolled = (
            timeline.rolling(
                "registered_at", period=window, closed="right", group_by="object_id"
            )
            .agg(pl.col("_snapshot").last(), *_window_features(window, config))
            .filter(pl.col("_snapshot"))
            .drop("_snapshot")
            .unique(subset=["object_id", "registered_at"])
            .rename({"registered_at": "scoring_timestamp"})
        )
        result = result.join(rolled, on=_KEYS, how="left")
    daily = (
        source.filter(~pl.col("_baseline_stuck"))
        .with_columns(pl.col("registered_at").dt.truncate("1d").alias("_day"))
        .group_by("object_id", "_day")
        .agg(pl.len().alias("_daily_count"))
        .sort(["object_id", "_day"])
        .with_columns(
            (
                pl.col("_daily_count").cum_sum().over("object_id")
                / pl.col("_day").cum_count().over("object_id")
            ).alias("historical_daily_event_baseline")
        )
        .select("object_id", "_day", "historical_daily_event_baseline")
    )
    result = (
        result.with_columns(
            pl.col("scoring_timestamp")
            .dt.truncate("1d")
            .dt.offset_by("-1d")
            .alias("_prior_day")
        )
        .sort(["object_id", "_prior_day"])
        .join_asof(
            daily,
            left_on="_prior_day",
            right_on="_day",
            by="object_id",
            strategy="backward",
            check_sortedness=False,
        )
        .drop("_prior_day", "_day")
    )
    return result.with_columns(
        pl.col("scoring_timestamp").dt.hour().alias("hour"),
        pl.col("scoring_timestamp").dt.weekday().alias("weekday"),
        pl.col("scoring_timestamp").dt.month().alias("month"),
        (pl.col("event_count_24h") / pl.col("historical_daily_event_baseline")).alias(
            "activity_ratio_24h"
        ),
    ).sort(_KEYS)


def attach_horizon_targets(
    snapshots: pl.LazyFrame, incidents: pl.LazyFrame
) -> pl.LazyFrame:
    """Attach active [start, end) and cumulative future (t, t+h] targets.

    Zero-duration incidents are active at their exact timestamp; an absent
    end denotes an ongoing incident. Explicit negative/undecided dispatcher
    decisions are not fire labels. Unknown proxy/synthetic labels remain
    provisional positives. With no decision column, the input is presumed
    to be an already selected incident table.

    Groups prefer the earliest active incident, otherwise the nearest future
    incident within 24h; ties use incident_id for reproducibility.
    """
    names = incidents.collect_schema().names()
    if "decision" in names:
        positive = pl.col("decision") == "confirmed_fire"
        if "source" in names:
            positive = positive | (
                (pl.col("decision") == "unknown")
                & pl.col("source").is_in(["proxy", "synthetic"])
            )
        incidents = incidents.filter(positive)
    labels = incidents.select(
        "object_id", "incident_id", "started_at", "ended_at"
    ).sort(["object_id", "started_at", "incident_id"])
    keys = snapshots.select(_KEYS)
    bounds = keys.group_by("object_id").agg(
        pl.col("scoring_timestamp").min().alias("_first_score"),
        pl.col("scoring_timestamp").max().alias("_last_score"),
    )
    # Partition active-interval matches by day, preventing an object-wide
    # snapshot × incident join across the entire multiyear history.
    active_days = (
        labels.join(bounds, on="object_id")
        .filter(
            (pl.col("started_at") <= pl.col("_last_score"))
            & (
                pl.col("ended_at").is_null()
                | (pl.col("ended_at") >= pl.col("_first_score"))
            )
        )
        .with_columns(
            pl.date_ranges(
                pl.max_horizontal("started_at", "_first_score").dt.date(),
                pl.min_horizontal(
                    pl.col("ended_at").fill_null(pl.col("_last_score")), "_last_score"
                ).dt.date(),
            ).alias("_active_day")
        )
        .explode("_active_day")
        .drop("_first_score", "_last_score")
    )
    active = (
        keys.with_columns(pl.col("scoring_timestamp").dt.date().alias("_active_day"))
        .join(active_days, on=["object_id", "_active_day"])
        .filter(
            (pl.col("started_at") <= pl.col("scoring_timestamp"))
            & (
                (pl.col("scoring_timestamp") < pl.col("ended_at"))
                | pl.col("ended_at").is_null()
                | (
                    (pl.col("started_at") == pl.col("ended_at"))
                    & (pl.col("started_at") == pl.col("scoring_timestamp"))
                )
            )
        )
        .sort([*_KEYS, "started_at", "incident_id"])
        .group_by(_KEYS)
        .agg(pl.col("incident_id").first().alias("_active_id"))
    )
    future = labels.unique(
        subset=["object_id", "started_at"], keep="first", maintain_order=True
    )
    result = (
        snapshots.sort(_KEYS)
        .join_asof(
            future,
            left_on="scoring_timestamp",
            right_on="started_at",
            by="object_id",
            strategy="forward",
            allow_exact_matches=False,
            check_sortedness=False,
        )
        .join(active, on=_KEYS, how="left")
        .with_columns(
            pl.col("_active_id").is_not_null().alias("target_now"),
            *[
                (
                    pl.col("started_at")
                    <= pl.col("scoring_timestamp") + pl.duration(hours=hours)
                )
                .fill_null(False)
                .alias(f"target_{hours}h")
                for hours in (6, 12, 24)
            ],
        )
    )
    return (
        result.with_columns(
            pl.coalesce(
                "_active_id",
                pl.when(pl.col("target_24h")).then(pl.col("incident_id")),
            ).alias("episode_group_id")
        )
        .drop("incident_id", "started_at", "ended_at", "_active_id")
        .sort(_KEYS)
    )
