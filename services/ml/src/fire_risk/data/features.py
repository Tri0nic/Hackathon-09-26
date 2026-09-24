"""Lazy, history-only object snapshots; incident targets attach separately."""

from datetime import datetime

import polars as pl

from fire_risk.config import PipelineConfig
from fire_risk.data.inventory import (
    SIGNAL_FAMILIES,
    build_object_inventory,
    family_expression,
)
from fire_risk.data.quality import (
    QualityThresholds,
    causal_quality_flags,
    mark_historical_artifacts,
    profile_channel_days,
)

_WINDOWS = ("5m", "30m", "3h", "6h", "24h")
_WINDOW_SECONDS = (300, 1800, 10800, 21600, 86400)
_KEYS = ["object_id", "scoring_timestamp"]


def _feature_events(
    events: pl.LazyFrame, thresholds: QualityThresholds
) -> pl.LazyFrame:
    names = events.collect_schema().names()
    optional = {
        "event_id": pl.lit(None, dtype=pl.String),
        "raw_value": pl.lit(None, dtype=pl.String),
        "numeric_value": pl.lit(None, dtype=pl.Float64),
        "value_kind": pl.lit(None, dtype=pl.String),
        "quality_flags": pl.lit([], dtype=pl.List(pl.String)),
    }
    events = events.with_columns(
        expr.alias(name) for name, expr in optional.items() if name not in names
    )
    flags = ("stuck", "burst", "historical_artifact")
    baseline_excluded = pl.any_horizontal(
        pl.col("quality_flags").list.contains("stuck"),
        pl.col("quality_flags").list.contains("historical_artifact"),
        *[
            pl.col(name)
            for name in (
                "baseline_stuck",
                "baseline_excluded",
                "stuck",
                "historical_artifact",
                "exclude_from_fire_training",
            )
            if name in names
        ],
    ).fill_null(False)
    # Retrospective inputs are safe only for completed-day baseline exclusion.
    # Rebuild window flags at this public boundary, even for pre-profiled input.
    events = events.with_columns(
        baseline_excluded.alias("baseline_excluded")
    ).with_columns(
        pl.col("quality_flags")
        .list.eval(pl.element().filter(~pl.element().is_in(flags)))
        .alias("quality_flags")
    )
    if {"event_id", "raw_value"}.issubset(names):
        history = events.select(
            "event_id",
            "raw_value",
            "object_id",
            "registered_at",
            "channel_id",
            "sensor_type",
            "alarm_flag",
            "numeric_value",
            "value_kind",
            "quality_flags",
            "baseline_excluded",
        )
        events = causal_quality_flags(
            mark_historical_artifacts(
                history, profile_channel_days(history), thresholds
            ),
            thresholds,
        )
    else:
        # Reduced signal-only inputs cannot establish a state run. Unverified
        # technical flags must not masquerade as observations available at t.
        events = events.with_columns(pl.lit(False).alias(flag) for flag in flags)
    return events.filter(
        pl.col("object_id").is_not_null() & pl.col("registered_at").is_not_null()
    ).select(
        "object_id",
        "registered_at",
        "channel_id",
        "event_id",
        "raw_value",
        "sensor_type",
        "alarm_flag",
        pl.col("numeric_value").cast(pl.Float64),
        "value_kind",
        pl.col("baseline_excluded").fill_null(False).alias("_baseline_excluded"),
        *[pl.col(flag).fill_null(False) for flag in flags],
        *[
            family_expression(category).alias(f"_{category}")
            for category in SIGNAL_FAMILIES
        ],
        pl.lit(True).alias("_event"),
        pl.lit(False).alias("_snapshot"),
    )


def _duration_totals(
    runs: pl.LazyFrame, grid: pl.LazyFrame, window: str, seconds: int
) -> pl.LazyFrame:
    """Integrate clipped duration ramps using at most three points per run."""
    limit = seconds * 1_000_000
    cap = pl.col("_start") + limit
    age = pl.col("_end") - pl.col("_start")
    common = ["object_id", "_broken"]
    points = pl.concat(
        [
            runs.select(
                *common,
                pl.col("_start").alias("_time"),
                pl.lit(1, dtype=pl.Int64).alias("_slope"),
                pl.lit(0, dtype=pl.Int64).alias("_jump"),
            ),
            runs.filter(pl.col("_end").is_null() | (cap <= pl.col("_end"))).select(
                *common,
                cap.alias("_time"),
                pl.lit(-1, dtype=pl.Int64).alias("_slope"),
                pl.lit(0, dtype=pl.Int64).alias("_jump"),
            ),
            runs.filter(pl.col("_end").is_not_null()).select(
                *common,
                pl.col("_end").alias("_time"),
                -(age < limit).cast(pl.Int64).alias("_slope"),
                -age.clip(upper_bound=limit).alias("_jump"),
            ),
        ]
    ).with_columns(
        (pl.col("_slope") * pl.col("_broken")).alias("_mal_slope"),
        (pl.col("_jump") * pl.col("_broken")).alias("_mal_jump"),
    )
    markers = grid.with_columns(pl.lit(True).alias("_snapshot"))
    timeline = (
        pl.concat([points, markers], how="diagonal")
        .group_by("object_id", "_time")
        .agg(
            pl.col("_snapshot").any(),
            *[
                pl.col(name).sum()
                for name in ("_slope", "_jump", "_mal_slope", "_mal_jump")
            ],
        )
        .sort(["object_id", "_time"])
        .with_columns(
            pl.col("_slope").cum_sum(),
            pl.col("_mal_slope").cum_sum(),
            pl.col("_time").diff().fill_null(0).alias("_elapsed"),
        )
        .with_columns(
            (
                pl.col("_elapsed") * pl.col("_slope").shift().fill_null(0)
                + pl.col("_jump")
            ).alias("_active_increment"),
            (
                pl.col("_elapsed") * pl.col("_mal_slope").shift().fill_null(0)
                + pl.col("_mal_jump")
            ).alias("_mal_increment"),
        )
        .with_columns(
            pl.col("_active_increment")
            .cum_sum()
            .alias(f"active_state_duration_seconds_{window}"),
            pl.col("_mal_increment")
            .cum_sum()
            .alias(f"malfunction_duration_seconds_{window}"),
        )
    )
    return timeline.filter(pl.col("_snapshot")).select(
        "object_id",
        "_time",
        pl.col(f"active_state_duration_seconds_{window}") / 1_000_000,
        pl.col(f"malfunction_duration_seconds_{window}") / 1_000_000,
    )


def _oldest_state_age(
    runs: pl.LazyFrame, grid: pl.LazyFrame, name: str
) -> pl.LazyFrame:
    """Build the disjoint envelope of oldest active runs, then look up snapshots."""
    envelope = (
        runs.with_columns(pl.col("_end").fill_null(2**63 - 1))
        .sort(["object_id", "_start", "_end"])
        .with_columns(pl.col("_end").cum_max().alias("_covered_until"))
        .with_columns(
            pl.max_horizontal("_start", pl.col("_covered_until").shift()).alias(
                "_segment_start"
            )
        )
        .filter(pl.col("_end") > pl.col("_segment_start"))
        .select("object_id", "_segment_start", "_start", "_end")
        .sort(["object_id", "_segment_start"])
    )
    return (
        grid.sort(["object_id", "_time"])
        .join_asof(
            envelope,
            left_on="_time",
            right_on="_segment_start",
            by="object_id",
            strategy="backward",
            check_sortedness=False,
        )
        .select(
            "object_id",
            "_time",
            pl.when(pl.col("_time") < pl.col("_end"))
            .then(pl.col("_time") - pl.col("_start"))
            .otherwise(0)
            .alias(name),
        )
    )


def _duration_features(source: pl.LazyFrame, grid: pl.LazyFrame) -> pl.LazyFrame:
    """Execute one complete object history per duration partition, sequentially.

    Only distinct object IDs are collected here. Every in-memory window fallback
    receives a single object's filtered events; no partition shares channel
    state. Peak duration intermediate size is at most 3 * events_for_object +
    snapshots_for_object per window, independent of other objects' histories.
    """
    object_ids = (
        source.select("object_id")
        .unique()
        .sort("object_id")
        .collect(engine="streaming")
        .get_column("object_id")
        .to_list()
    )
    if not object_ids:
        return _duration_partition(source, grid)
    return pl.concat(
        [
            _duration_partition(
                source.filter(pl.col("object_id") == object_id),
                grid.filter(pl.col("object_id") == object_id),
            )
            for object_id in object_ids
        ],
        parallel=False,
    )


def _duration_partition(source: pl.LazyFrame, grid: pl.LazyFrame) -> pl.LazyFrame:
    """Aggregate one object's run change points with O(events + snapshots) rows.

    Ends only cancel a run's contribution at that later transition. Appending a
    future transition cannot alter any earlier change point or snapshot value.
    No Python callback or channel-by-snapshot product is used. Grouped windows
    that fall back from streaming remain bounded by this object partition.
    """
    source = source.select(
        "object_id",
        "channel_id",
        "registered_at",
        "event_id",
        "raw_value",
        "value_kind",
    ).cache()
    grid = grid.cache()
    channel_keys = ["object_id", "channel_id"]
    runs = (
        source.filter(
            pl.col("raw_value").is_not_null() & pl.col("channel_id").is_not_null()
        )
        .sort([*channel_keys, "registered_at", "event_id"])
        .filter(
            pl.col("raw_value").ne_missing(
                pl.col("raw_value").shift().over(channel_keys)
            )
        )
        .select(
            *channel_keys,
            pl.col("registered_at").dt.epoch("us").alias("_start"),
            (pl.col("value_kind") == "malfunction")
            .fill_null(False)
            .cast(pl.Int64)
            .alias("_broken"),
        )
        .with_columns(pl.col("_start").shift(-1).over(channel_keys).alias("_end"))
        .filter(pl.col("_end").is_null() | (pl.col("_end") > pl.col("_start")))
        .cache()
    )
    grid_us = grid.select(
        "object_id", pl.col("registered_at").dt.epoch("us").alias("_time")
    )
    keys = ["object_id", "_time"]
    result = _oldest_state_age(runs, grid_us, "_active_age").join(
        _oldest_state_age(runs.filter(pl.col("_broken") == 1), grid_us, "_mal_age"),
        on=keys,
        how="left",
    )
    for window, seconds in zip(_WINDOWS, _WINDOW_SECONDS, strict=True):
        result = result.join(
            _duration_totals(runs, grid_us, window, seconds), on=keys, how="left"
        )
        result = result.with_columns(
            (
                pl.col("_active_age").clip(upper_bound=seconds * 1_000_000) / 1_000_000
            ).alias(f"max_active_state_duration_seconds_{window}"),
            (
                pl.col("_mal_age").clip(upper_bound=seconds * 1_000_000) / 1_000_000
            ).alias(f"max_malfunction_duration_seconds_{window}"),
        )
    return (
        result.drop("_active_age", "_mal_age")
        .rename({"_time": "scoring_timestamp"})
        .with_columns(
            pl.col("scoring_timestamp")
            .cast(pl.Datetime("us", "UTC"))
            .cast(grid.collect_schema()["registered_at"])
        )
    )


def _slope(signal: pl.Expr) -> pl.Expr:
    numeric = signal & pl.col("numeric_value").is_not_null()
    timestamps = pl.col("registered_at").filter(numeric)
    # Center before conversion to float to preserve short time differences.
    hours = (timestamps - timestamps.min()).dt.total_microseconds() / 3_600_000_000
    values = pl.col("numeric_value").filter(numeric)
    variance = hours.var(ddof=0)
    return (
        pl.when((timestamps.n_unique() >= 2) & (variance > 0))
        .then(pl.cov(hours, values, ddof=0) / variance)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )


def _window_features(window: str, config: PipelineConfig) -> list[pl.Expr]:
    event = pl.col("_event").fill_null(False)
    alarm = event & pl.col("alarm_flag").fill_null(False)
    gas = event & pl.col("_gas")
    heat = event & pl.col("_heat")
    smoke_alarm = (alarm & pl.col("_smoke")).any()
    observed_state = event & pl.col("raw_value").is_not_null()
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
        "gas_slope_per_hour": _slope(gas),
        "temperature_slope_per_hour": _slope(heat),
        "gas_variability": pl.col("numeric_value").filter(gas).std(ddof=1),
        "temperature_variability": pl.col("numeric_value").filter(heat).std(ddof=1),
        "state_entropy": pl.when(observed_state.any())
        .then(
            pl.struct("channel_id", "raw_value")
            .filter(observed_state)
            .value_counts()
            .struct.field("count")
            .entropy(base=2, normalize=True)
        )
        .otherwise(pl.lit(None, dtype=pl.Float64)),
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


def _freshness_partition(
    events: pl.LazyFrame, grid: pl.LazyFrame, inventory: pl.LazyFrame
) -> pl.LazyFrame:
    """Union one channel's closed 24h intervals, then count active intervals.

    This equals testing its last observation <= t against t - 24h, without a
    channel x snapshot product. At most E intervals and 2E endpoint records
    exist per object. A future event can extend an interval only through a
    period that was already fresh; no earlier snapshot changes.
    """
    keys = ["object_id", "channel_id"]
    intervals = (
        events.filter(pl.col("registered_at").is_not_null())
        .select(*keys, "registered_at")
        .join(inventory.select(*keys, "sensor_type"), on=keys, how="inner")
        .sort([*keys, "registered_at"])
        .with_columns(
            (pl.col("registered_at").diff().over(keys) > pl.duration(hours=24))
            .fill_null(True)
            .cast(pl.Int64)
            .alias("_new_interval")
        )
        .with_columns(pl.col("_new_interval").cum_sum().over(keys).alias("_interval"))
        .group_by(*keys, "_interval")
        .agg(
            pl.col("registered_at").min().alias("_start"),
            (pl.col("registered_at").max() + pl.duration(hours=24)).alias("_end"),
            pl.col("sensor_type").first(),
        )
        .with_columns(
            pl.lit(1, dtype=pl.Int64).alias("_all"),
            *[
                family_expression(family).cast(pl.Int64).alias(f"_{family}")
                for family in SIGNAL_FAMILIES
            ],
        )
        .cache()
    )
    families = ["all", *SIGNAL_FAMILIES]
    result = grid.rename({"registered_at": "scoring_timestamp"}).sort(_KEYS)
    for endpoint, inclusive in [("start", True), ("end", False)]:
        counts = (
            intervals.group_by("object_id", f"_{endpoint}")
            .agg(
                *[
                    pl.col(f"_{family}").sum().alias(f"_{endpoint}_{family}")
                    for family in families
                ]
            )
            .sort(["object_id", f"_{endpoint}"])
            .with_columns(
                *[
                    pl.col(f"_{endpoint}_{family}").cum_sum().over("object_id")
                    for family in families
                ]
            )
        )
        result = result.join_asof(
            counts,
            left_on="scoring_timestamp",
            right_on=f"_{endpoint}",
            by="object_id",
            strategy="backward",
            allow_exact_matches=inclusive,
            check_sortedness=False,
        )
    return result.select(
        *_KEYS,
        *[
            (
                pl.col(f"_start_{family}").fill_null(0)
                - pl.col(f"_end_{family}").fill_null(0)
            ).alias(
                "fresh_channel_count"
                if family == "all"
                else f"fresh_{family}_channel_count"
            )
            for family in families
        ],
    )


def _freshness_features(
    events: pl.LazyFrame, grid: pl.LazyFrame, inventory: pl.LazyFrame
) -> pl.LazyFrame:
    """Keep window/sort fallback memory bounded to a single object's history."""
    totals, _ = build_object_inventory(inventory)
    object_ids = (
        grid.select("object_id")
        .unique()
        .sort("object_id")
        .collect(engine="streaming")["object_id"]
        .to_list()
    )
    partitions = [
        _freshness_partition(
            events.filter(pl.col("object_id") == object_id),
            grid.filter(pl.col("object_id") == object_id),
            inventory.filter(pl.col("object_id") == object_id),
        )
        for object_id in object_ids
    ]
    fresh = (
        pl.concat(partitions, parallel=False)
        if partitions
        else _freshness_partition(events, grid, inventory)
    )
    result = fresh.join(totals, on="object_id", how="left")
    suffixes = [
        "channel_count",
        *[f"{family}_channel_count" for family in SIGNAL_FAMILIES],
    ]
    return (
        result.with_columns(
            *[pl.col(f"inventory_{suffix}").fill_null(0) for suffix in suffixes]
        )
        .with_columns(
            *[
                (pl.col(f"inventory_{suffix}") - pl.col(f"fresh_{suffix}")).alias(
                    f"stale_{suffix}"
                )
                for suffix in suffixes
            ]
        )
        .with_columns(
            pl.when(pl.col("inventory_channel_count") > 0)
            .then(pl.col("stale_channel_count") / pl.col("inventory_channel_count"))
            .otherwise(pl.lit(None, dtype=pl.Float64))
            .alias("stale_channel_share")
        )
        .sort(_KEYS)
    )


def build_feature_snapshots(
    events: pl.LazyFrame,
    config: PipelineConfig,
    inventory: pl.LazyFrame | None = None,
    *,
    thresholds: QualityThresholds,
) -> pl.LazyFrame:
    """Build a per-object grid from floor(first event) to ceil(last event).

    Windows are (t - window, t]. Empty grid intervals have zero counts and
    null numeric summaries. Baselines average observed, eligible completed
    days; stuck and historical/corrupted intervals are omitted. Weekday uses
    ISO numbering (Monday = 1).
    Current-state durations are summed/maximized after clipping each channel
    independently. Missing raw history gives zero duration and null entropy.
    Causal quality is rebuilt from raw event history at this boundary. Without
    raw values/event IDs, unverifiable technical flags default to zero; existing
    exclusion annotations can only exclude completed days from the baseline.
    No incident, label, or current whole-day profile enters a window feature.
    When the canonical channel reference is provided as inventory, freshness
    uses [t - 24h, t] inclusively. Never-observed channels are stale. Omitting
    inventory preserves the legacy feature schema, without inferring a reference.
    """
    if config.scoring_step_minutes <= 0:
        raise ValueError("scoring_step_minutes must be positive")
    source = _feature_events(events, thresholds)
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
    result = grid.rename({"registered_at": "scoring_timestamp"}).join(
        _duration_features(source, grid), on=_KEYS, how="left"
    )
    if inventory is not None:
        result = result.join(
            _freshness_features(events, grid, inventory), on=_KEYS, how="left"
        )
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
        source.filter(~pl.col("_baseline_excluded"))
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
    snapshots: pl.LazyFrame, incidents: pl.LazyFrame, observed_until: datetime
) -> pl.LazyFrame:
    """Attach active [start, end) and cumulative future (t, t+h] targets.

    Zero-duration incidents are active at their exact timestamp; an absent
    end denotes an ongoing incident. Explicit negative/undecided dispatcher
    decisions are not fire labels. Unknown proxy/synthetic labels remain
    provisional positives. With no decision column, the input is presumed
    to be an already selected incident table.

    Groups are connected components of incident influence intervals: from
    24h before start through the active interval. Overlapping intervals merge
    transitively within each object. The earliest incident (ties use its ID)
    names the component, independent of input order and selected snapshots.
    """
    names = incidents.collect_schema().names()
    if observed_until.tzinfo is None or observed_until.utcoffset() is None:
        raise ValueError("observed_until must be timezone-aware")
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
    # Integer microseconds let ongoing intervals extend to infinity without
    # creating artificial calendar dates. Point incidents include their start.
    labels = (
        labels.with_columns(
            (pl.col("started_at") - pl.duration(hours=24))
            .dt.epoch("us")
            .alias("_influence_start"),
            pl.when(pl.col("ended_at").is_null())
            .then(pl.lit(2**63 - 1, dtype=pl.Int64))
            .otherwise(
                pl.max_horizontal(
                    pl.col("ended_at").dt.epoch("us"),
                    pl.col("started_at").dt.epoch("us") + 1,
                )
            )
            .alias("_influence_end"),
        )
        .with_columns(
            pl.col("_influence_end").cum_max().over("object_id").alias("_covered_until")
        )
        .with_columns(
            pl.col("_covered_until").shift(1).over("object_id").alias("_prior_end")
        )
        .with_columns(
            (
                pl.col("_prior_end").is_null()
                | (pl.col("_influence_start") >= pl.col("_prior_end"))
            )
            .cast(pl.Int64)
            .alias("_new_component")
        )
        .with_columns(
            pl.col("_new_component").cum_sum().over("object_id").alias("_component")
        )
        .with_columns(
            pl.col("incident_id")
            .first()
            .over("object_id", "_component")
            .alias("_context_group_id")
        )
        .drop(
            "_influence_start",
            "_influence_end",
            "_covered_until",
            "_prior_end",
            "_new_component",
            "_component",
        )
    )
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
        .agg(pl.col("_context_group_id").first().alias("_active_id"))
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
            *[
                (
                    pl.col("scoring_timestamp") + pl.duration(hours=hours)
                    <= pl.lit(observed_until)
                )
                .fill_null(False)
                .alias(f"target_{hours}h_available")
                for hours in (6, 12, 24)
            ],
            (pl.col("scoring_timestamp") <= pl.lit(observed_until))
            .fill_null(False)
            .alias("target_now_available"),
        )
        .with_columns(
            pl.when(pl.col("target_now_available"))
            .then(pl.col("_active_id").is_not_null())
            .otherwise(pl.lit(None, dtype=pl.Boolean))
            .alias("target_now"),
            *[
                pl.when(pl.col(f"target_{hours}h_available"))
                .then(
                    (
                        pl.col("started_at")
                        <= pl.col("scoring_timestamp") + pl.duration(hours=hours)
                    ).fill_null(False)
                )
                .otherwise(pl.lit(None, dtype=pl.Boolean))
                .alias(f"target_{hours}h")
                for hours in (6, 12, 24)
            ],
        )
    )
    return (
        result.with_columns(
            pl.coalesce(
                "_active_id",
                pl.when(
                    pl.any_horizontal(
                        *[
                            pl.col(f"target_{hours}h").fill_null(False)
                            for hours in (6, 12, 24)
                        ]
                    )
                ).then(pl.col("_context_group_id")),
            ).alias("episode_group_id")
        )
        .drop(
            "incident_id", "started_at", "ended_at", "_active_id", "_context_group_id"
        )
        .sort(_KEYS)
    )
