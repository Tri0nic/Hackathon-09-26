"""Group normalized sensor events into deterministic object episodes."""

from datetime import timedelta
from pathlib import Path
from tempfile import mkdtemp

import polars as pl

from fire_risk.data.inventory import family_expression


def build_episodes(
    events: pl.LazyFrame,
    gap: timedelta,
    *,
    methane_alarm_percent: float = 1.0,
    temp_dir: Path | None = None,
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Return episodes and event membership; unknown objects have no episode."""
    names = events.collect_schema().names()
    defaults = {
        "value_kind": pl.lit(None, dtype=pl.String),
        "numeric_value": pl.lit(None, dtype=pl.Float64),
        "historical_artifact": pl.lit(False),
        "exclude_from_fire_training": pl.lit(False),
    }
    events = events.with_columns(
        expr.alias(name) for name, expr in defaults.items() if name not in names
    )
    if temp_dir is not None:
        return _bounded_episodes(events, gap, methane_alarm_percent, temp_dir)
    methane = (
        family_expression("gas")
        & (pl.col("value_kind") == "numeric")
        & pl.col("numeric_value").is_finite()
        & (pl.col("numeric_value") >= methane_alarm_percent)
    ).fill_null(False)
    fire_alarm = (
        pl.col("alarm_flag") & (pl.col("value_kind") != "malfunction").fill_null(True)
    ).fill_null(False)
    events = events.with_columns(
        methane.alias("_methane_alarm"),
        (fire_alarm | methane).alias("_fire_alarm"),
    )
    known = events.filter(pl.col("object_id").is_not_null()).sort(
        ["object_id", "registered_at", "event_id"]
    )
    known = known.with_columns(
        (
            (pl.col("registered_at").diff().over("object_id") > pl.lit(gap))
            .fill_null(True)
            .cast(pl.Int64)
        ).alias("_new_episode")
    ).with_columns(
        pl.col("_new_episode").cum_sum().over("object_id").alias("_episode_number")
    )
    known = known.with_columns(
        pl.col("registered_at")
        .min()
        .over(["object_id", "_episode_number"])
        .alias("_episode_start")
    )
    known = known.with_columns(
        pl.concat_str(
            pl.lit("ep:"),
            pl.col("object_id").str.len_bytes().cast(pl.String),
            pl.lit(":"),
            pl.col("object_id"),
            pl.lit(":"),
            pl.col("_episode_start")
            .dt.convert_time_zone("UTC")
            .dt.strftime("%Y-%m-%dT%H:%M:%S%.6fZ"),
        ).alias("episode_id")
    )
    episodes = (
        known.group_by("object_id", "episode_id")
        .agg(
            pl.col("registered_at").min().alias("started_at"),
            pl.col("registered_at").max().alias("ended_at"),
            pl.when(pl.col("_fire_alarm").any())
            .then(pl.lit("alarm"))
            .otherwise(pl.lit("unknown"))
            .alias("severity"),
            pl.col("channel_id").drop_nulls().unique().sort().alias("channel_ids"),
            pl.col("sensor_type").drop_nulls().unique().sort().alias("sensor_types"),
            pl.col("channel_id")
            .filter(pl.col("_fire_alarm"))
            .drop_nulls()
            .unique()
            .sort()
            .alias("alarming_channel_ids"),
            pl.col("sensor_type")
            .filter(pl.col("_fire_alarm"))
            .drop_nulls()
            .unique()
            .sort()
            .alias("alarming_sensor_types"),
            pl.col("channel_id")
            .filter(pl.col("_methane_alarm"))
            .drop_nulls()
            .unique()
            .sort()
            .alias("methane_alarm_channel_ids"),
            pl.col("historical_artifact").fill_null(False).any(),
            pl.col("exclude_from_fire_training").fill_null(False).any(),
            pl.col("picket_sort_key").min().alias("picket_from"),
            pl.col("picket_sort_key").max().alias("picket_to"),
            pl.col("quality_flags")
            .explode()
            .drop_nulls()
            .unique()
            .sort()
            .alias("quality_flags"),
        )
        .sort(["object_id", "started_at", "episode_id"])
        .select(
            "episode_id",
            "object_id",
            "started_at",
            "ended_at",
            "severity",
            "channel_ids",
            "sensor_types",
            "alarming_channel_ids",
            "alarming_sensor_types",
            "methane_alarm_channel_ids",
            "historical_artifact",
            "exclude_from_fire_training",
            "picket_from",
            "picket_to",
            "quality_flags",
        )
    )
    membership = pl.concat(
        [
            known.select("event_id", "episode_id"),
            events.filter(pl.col("object_id").is_null()).select(
                "event_id", pl.lit(None, dtype=pl.String).alias("episode_id")
            ),
        ]
    ).sort("event_id")
    return episodes, membership


def _bounded_episodes(
    events: pl.LazyFrame, gap: timedelta, methane_alarm_percent: float, temp_dir: Path
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Keep event windows inside UTC months, stitching compact episode fragments.

    The caller owns the temp lifetime. A large object may span the whole corpus,
    so object-only partitioning is insufficient. Fragment boundaries are merged
    with the same strictly-greater-than-gap rule as the unpartitioned algorithm.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="episodes-", dir=temp_dir))
    fields = [
        "event_id",
        "channel_id",
        "object_id",
        "registered_at",
        "sensor_type",
        "alarm_flag",
        "picket_sort_key",
        "quality_flags",
        "value_kind",
        "numeric_value",
        "historical_artifact",
        "exclude_from_fire_training",
    ]
    events.select(fields).sink_parquet(
        pl.PartitionByKey(
            root / "months",
            by={
                "_month": pl.col("registered_at")
                .dt.convert_time_zone("UTC")
                .dt.strftime("%Y-%m")
            },
            include_key=False,
        ),
        mkdir=True,
    )
    fragments = root / "fragments"
    members = root / "members"
    fragments.mkdir()
    members.mkdir()
    month_paths = sorted((root / "months").glob("*"))
    for index, month in enumerate(month_paths):
        local = pl.scan_parquet(month / "*.parquet", hive_partitioning=False)
        episode_part, member_part = build_episodes(
            local, gap, methane_alarm_percent=methane_alarm_percent
        )
        episode_part.sink_parquet(fragments / f"{index:06}.parquet")
        member_part.sink_parquet(members / f"{index:06}.parquet")
    if not month_paths:
        empty_episodes, empty_members = build_episodes(
            events.limit(0), gap, methane_alarm_percent=methane_alarm_percent
        )
        empty_episodes.sink_parquet(fragments / "000000.parquet")
        empty_members.sink_parquet(members / "000000.parquet")

    ordered = pl.scan_parquet(fragments / "*.parquet").sort(
        ["object_id", "started_at", "episode_id"]
    )
    components = (
        ordered.with_columns(
            (
                (pl.col("started_at") - pl.col("ended_at").shift(1).over("object_id"))
                > pl.lit(gap)
            )
            .fill_null(True)
            .cast(pl.Int64)
            .alias("_new")
        )
        .with_columns(pl.col("_new").cum_sum().over("object_id").alias("_component"))
        .with_columns(
            pl.col("started_at")
            .min()
            .over(["object_id", "_component"])
            .alias("_canonical_start")
        )
        .with_columns(
            pl.concat_str(
                pl.lit("ep:"),
                pl.col("object_id").str.len_bytes().cast(pl.String),
                pl.lit(":"),
                pl.col("object_id"),
                pl.lit(":"),
                pl.col("_canonical_start")
                .dt.convert_time_zone("UTC")
                .dt.strftime("%Y-%m-%dT%H:%M:%S%.6fZ"),
            ).alias("_canonical_id")
        )
        .collect(engine="streaming")
        .lazy()
    )
    list_fields = [
        "channel_ids",
        "sensor_types",
        "alarming_channel_ids",
        "alarming_sensor_types",
        "methane_alarm_channel_ids",
        "quality_flags",
    ]
    episodes = (
        components.group_by("object_id", "_canonical_id")
        .agg(
            pl.col("started_at").min(),
            pl.col("ended_at").max(),
            pl.when((pl.col("severity") == "alarm").any())
            .then(pl.lit("alarm"))
            .otherwise(pl.lit("unknown"))
            .alias("severity"),
            *[
                pl.col(name).explode().drop_nulls().unique().sort()
                for name in list_fields
            ],
            pl.col("historical_artifact").any(),
            pl.col("exclude_from_fire_training").any(),
            pl.col("picket_from").min(),
            pl.col("picket_to").max(),
        )
        .rename({"_canonical_id": "episode_id"})
        .sort(["object_id", "started_at", "episode_id"])
        .select(
            "episode_id",
            "object_id",
            "started_at",
            "ended_at",
            "severity",
            "channel_ids",
            "sensor_types",
            "alarming_channel_ids",
            "alarming_sensor_types",
            "methane_alarm_channel_ids",
            "historical_artifact",
            "exclude_from_fire_training",
            "picket_from",
            "picket_to",
            "quality_flags",
        )
    )
    mapping = components.select(
        pl.col("episode_id").alias("_fragment_id"), "_canonical_id"
    )
    # Files are chronological UTC months; each fragment's membership is sorted
    # by event_id. This is deterministic without sorting all event IDs at once.
    membership = (
        pl.scan_parquet(sorted(members.glob("*.parquet")))
        .join(
            mapping,
            left_on="episode_id",
            right_on="_fragment_id",
            how="left",
            maintain_order="left",
        )
        .select("event_id", pl.col("_canonical_id").alias("episode_id"))
    )
    return episodes, membership
