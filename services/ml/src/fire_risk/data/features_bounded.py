"""Exact daily feature execution with compact history and state carries."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp
from typing import cast

import polars as pl

from fire_risk.config import PipelineConfig
from fire_risk.data.features import (
    _KEYS,
    _WINDOWS,
    _duration_features,
    _feature_events,
    _freshness_features,
    _window_features,
    attach_horizon_targets,
    build_feature_snapshots,
)
from fire_risk.data.quality import QualityThresholds, _daily_profiles, _profile_history


def _state_carry(source: pl.DataFrame) -> pl.DataFrame:
    keys = ["object_id", "channel_id"]
    return (
        source.lazy()
        .filter(pl.col("raw_value").is_not_null() & pl.col("channel_id").is_not_null())
        .sort([*keys, "registered_at", "event_id"])
        .filter(pl.col("raw_value").ne_missing(pl.col("raw_value").shift().over(keys)))
        .group_by(keys)
        .agg(pl.exclude(keys).last())
        .select(source.columns)
        .collect()
    )


def _daily_features(
    source: pl.DataFrame,
    carry: pl.DataFrame,
    grid: pl.DataFrame,
    config: PipelineConfig,
    inventory: pl.LazyFrame | None,
    baseline: pl.DataFrame,
) -> pl.LazyFrame:
    """At most two event days enter windows; seeds enter durations only."""
    lazy = source.lazy()
    grid_lazy = grid.lazy()
    durations = _duration_features(
        pl.concat([carry, source]).lazy(), grid_lazy
    ).collect()
    result = grid_lazy.rename({"registered_at": "scoring_timestamp"}).join(
        durations.lazy(), on=_KEYS, how="left"
    )
    if inventory is not None:
        fresh = _freshness_features(lazy, grid_lazy, inventory).collect()
        result = result.join(fresh.lazy(), on=_KEYS, how="left")
    markers = grid_lazy.with_columns(
        pl.lit(True).alias("_snapshot"), pl.lit(False).alias("_event")
    )
    timeline = pl.concat([lazy, markers], how="diagonal").sort(
        ["object_id", "registered_at", "_snapshot"]
    )
    for window in _WINDOWS:
        # Aggregate only the scoring grid, not a rolling result per input event.
        rolled = (
            timeline.group_by_dynamic(
                "registered_at",
                every=f"{config.scoring_step_minutes}m",
                period=window,
                offset=f"-{window}",
                closed="right",
                label="right",
                group_by="object_id",
            )
            .agg(*_window_features(window, config))
            .rename({"registered_at": "scoring_timestamp"})
            .collect()
        )
        result = result.join(rolled.lazy(), on=_KEYS, how="left")
    return (
        result.join(baseline.lazy(), on="object_id", how="left")
        .with_columns(
            pl.col("scoring_timestamp").dt.hour().alias("hour"),
            pl.col("scoring_timestamp").dt.weekday().alias("weekday"),
            pl.col("scoring_timestamp").dt.month().alias("month"),
            (
                pl.col("event_count_24h") / pl.col("historical_daily_event_baseline")
            ).alias("activity_ratio_24h"),
        )
        .sort(_KEYS)
    )


def bounded_features(
    events: pl.LazyFrame,
    config: PipelineConfig,
    inventory: pl.LazyFrame | None,
    thresholds: QualityThresholds,
    temp_dir: Path,
) -> pl.LazyFrame:
    temp_dir.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="features-", dir=temp_dir))
    names = events.collect_schema().names()
    wanted = [
        "object_id",
        "registered_at",
        "channel_id",
        "sensor_type",
        "alarm_flag",
        "event_id",
        "raw_value",
        "numeric_value",
        "value_kind",
        "quality_flags",
        "baseline_stuck",
        "baseline_excluded",
        "stuck",
        "historical_artifact",
        "exclude_from_fire_training",
    ]
    raw = events.select([name for name in wanted if name in names])
    valid = raw.filter(pl.col("registered_at").is_not_null())
    step = f"{config.scoring_step_minutes}m"
    step_us = config.scoring_step_minutes * 60_000_000
    bounds = (
        valid.filter(pl.col("object_id").is_not_null())
        .group_by("object_id")
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
        .collect(engine="streaming")
    )
    if bounds.is_empty():
        return build_feature_snapshots(
            raw.limit(0), config, inventory, thresholds=thresholds
        )
    valid.sink_parquet(
        pl.PartitionByKey(
            root / "months",
            by={"_month": pl.col("registered_at").dt.strftime("%Y-%m")},
            include_key=False,
        ),
        mkdir=True,
    )
    days: dict[str, Path] = {}
    profile_dir = root / "profiles"
    profile_dir.mkdir()
    for index, month in enumerate(sorted((root / "months").glob("*"))):
        folder = root / "days" / str(index)
        pl.scan_parquet(month / "*.parquet", hive_partitioning=False).sink_parquet(
            pl.PartitionByKey(
                folder,
                by={"_day": pl.col("registered_at").dt.date()},
                include_key=False,
            ),
            mkdir=True,
        )
        for day in sorted(folder.glob("*")):
            key = day.name.split("=", 1)[1]
            days[key] = day
            if {"event_id", "raw_value"}.issubset(names):
                _daily_profiles(
                    pl.scan_parquet(day / "*.parquet", hive_partitioning=False)
                ).sink_parquet(profile_dir / f"{key}.parquet")
    profiles = (
        _profile_history(pl.scan_parquet(profile_dir / "*.parquet")).collect(
            engine="streaming"
        )
        if {"event_id", "raw_value"}.issubset(names)
        else None
    )
    prepared = root / "prepared"
    output = root / "snapshots"
    prepared.mkdir()
    output.mkdir()
    empty = _feature_events(raw.limit(0), thresholds).collect()
    previous = empty
    carry = empty
    totals = pl.DataFrame(
        schema={
            "object_id": bounds.schema["object_id"],
            "_sum": pl.UInt64,
            "_days": pl.UInt64,
        }
    )
    day_start = cast(datetime, bounds["_start"].min()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    last = cast(datetime, bounds["_end"].max())
    inventory = (
        inventory.collect(engine="streaming").lazy() if inventory is not None else None
    )
    while day_start <= last:
        next_day = day_start + timedelta(days=1)
        key = day_start.date().isoformat()
        if key in days:
            day_profiles = (
                profiles.filter(pl.col("day") == day_start.date()).lazy()
                if profiles is not None
                else None
            )
            today = _feature_events(
                pl.scan_parquet(days[key] / "*.parquet", hive_partitioning=False),
                thresholds,
                profiles=day_profiles,
            ).collect()
            today.write_parquet(prepared / f"{key}.parquet")
        else:
            today = empty
        # Grid is built from each object's original bounds, including empty days.
        grid = (
            bounds.lazy()
            .filter((pl.col("_start") < next_day) & (pl.col("_end") >= day_start))
            .select(
                "object_id",
                pl.datetime_ranges(
                    pl.col("_start")
                    + pl.duration(
                        microseconds=(
                            (
                                (pl.lit(day_start) - pl.col("_start"))
                                .dt.total_microseconds()
                                .clip(lower_bound=0)
                                + step_us
                                - 1
                            )
                            // step_us
                        )
                        * step_us
                    ),
                    pl.min_horizontal("_end", pl.lit(next_day)),
                    interval=step,
                ).alias("registered_at"),
            )
            .explode("registered_at")
            .filter(pl.col("registered_at") < next_day)
            .collect()
        )
        source = pl.concat([previous, today])
        baseline = totals.select(
            "object_id",
            (pl.col("_sum") / pl.col("_days")).alias("historical_daily_event_baseline"),
        )
        if not grid.is_empty():
            seeds = carry.with_columns(
                pl.lit(day_start - timedelta(days=1)).alias("registered_at"),
                pl.lit("").alias("event_id"),
            )
            _daily_features(
                source, seeds, grid, config, inventory, baseline
            ).sink_parquet(output / f"{key}.parquet")
        daily = (
            today.filter(~pl.col("_baseline_excluded"))
            .group_by("object_id")
            .agg(pl.len().cast(pl.UInt64).alias("_sum"))
            .with_columns(pl.lit(1, dtype=pl.UInt64).alias("_days"))
        )
        totals = (
            pl.concat([totals, daily])
            .group_by("object_id")
            .agg(pl.col("_sum", "_days").sum())
        )
        # At next day's left 24h boundary, retain the state preceding previous.
        carry = _state_carry(pl.concat([carry, previous]))
        previous = today
        day_start = next_day
    return pl.scan_parquet(sorted(output.glob("*.parquet")))


def bounded_targets(
    snapshots: pl.LazyFrame,
    incidents: pl.LazyFrame,
    observed_until: datetime,
    temp_dir: Path,
) -> pl.LazyFrame:
    """Keep wide snapshot sorts/joins within a local day, not the corpus."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="targets-", dir=temp_dir))
    labels = incidents.collect(engine="streaming").lazy()
    snapshots.sink_parquet(
        pl.PartitionByKey(
            root / "months",
            by={"_month": pl.col("scoring_timestamp").dt.strftime("%Y-%m")},
            include_key=False,
        ),
        mkdir=True,
        row_group_size=8192,
    )
    output = root / "targets"
    output.mkdir()
    for index, month in enumerate(sorted((root / "months").glob("*"))):
        days = root / "days" / str(index)
        pl.scan_parquet(month / "*.parquet", hive_partitioning=False).sink_parquet(
            pl.PartitionByKey(
                days,
                by={"_day": pl.col("scoring_timestamp").dt.date()},
                include_key=False,
            ),
            mkdir=True,
            row_group_size=8192,
        )
        for day in sorted(days.glob("*")):
            attach_horizon_targets(
                pl.scan_parquet(day / "*.parquet", hive_partitioning=False),
                labels,
                observed_until,
            ).sink_parquet(output / f"{day.name}.parquet")
    files = sorted(output.glob("*.parquet"))
    if not files:
        return attach_horizon_targets(snapshots.limit(0), labels, observed_until)
    return pl.scan_parquet(files)
