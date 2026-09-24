"""Group normalized sensor events into deterministic object episodes."""

from datetime import timedelta

import polars as pl


def build_episodes(
    events: pl.LazyFrame, gap: timedelta
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Return episodes and event membership; unknown objects have no episode."""
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
            pl.when(pl.col("alarm_flag").any())
            .then(pl.lit("alarm"))
            .otherwise(pl.lit("unknown"))
            .alias("severity"),
            pl.col("channel_id").drop_nulls().unique().sort().alias("channel_ids"),
            pl.col("sensor_type").drop_nulls().unique().sort().alias("sensor_types"),
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
