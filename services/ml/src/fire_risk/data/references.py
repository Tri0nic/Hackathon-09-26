"""Join reference metadata and report coverage of observed event values."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl


class ReferenceIntegrityError(ValueError):
    """A reference table cannot be joined without ambiguous results."""


_CHANNEL_FIELDS = (
    "channel_id",
    "engineering_system_type",
    "sensor_type",
    "sensor_name",
    "object_id",
    "object_level",
    "object_name",
    "level2_object_id",
    "level2_object_name",
    "level1_object_id",
    "level1_object_name",
)


@dataclass(frozen=True)
class CoverageReport:
    total_events: int
    unknown_channel_events: int
    unmapped_type_value_pairs: dict[tuple[str, str], int]


def join_channels(events: pl.LazyFrame, channels: Path) -> pl.LazyFrame:
    """Keep every event while adding the exact channel-reference fields."""
    reference = pl.scan_csv(channels, infer_schema=False).select(_CHANNEL_FIELDS).with_columns(
        pl.col("channel_id").cast(pl.String),
        pl.col("object_level").cast(pl.Int64),
    )
    duplicates = (
        reference.group_by("channel_id")
        .len()
        .filter(pl.col("len") > 1)
        .select("channel_id")
        .collect()
    )
    if not duplicates.is_empty():
        raise ReferenceIntegrityError(
            f"Duplicate channel_id values: {duplicates['channel_id'].to_list()}"
        )

    if "quality_flags" not in events.collect_schema().names():
        events = events.with_columns(pl.lit([], dtype=pl.List(pl.String)).alias("quality_flags"))
    return events.join(reference, on="channel_id", how="left").with_columns(
        pl.when(pl.col("object_id").is_null())
        .then(pl.concat_list("quality_flags", pl.lit(["unknown_channel"])))
        .otherwise(pl.col("quality_flags"))
        .alias("quality_flags")
    )


def build_coverage_report(
    events: pl.LazyFrame, channels: Path, states: Path
) -> CoverageReport:
    """Count channel misses and observed values absent from the state reference."""
    joined = join_channels(events, channels)
    totals = joined.select(
        pl.len().alias("total_events"),
        pl.col("object_id").is_null().sum().alias("unknown_channel_events"),
    ).collect().row(0, named=True)

    state_pairs = (
        pl.scan_csv(states, infer_schema=False)
        .select("sensor_type", "state_set_id", "state_name", "alarm_flag")
        .select("sensor_type", pl.col("state_name").alias("raw_value"))
        .unique()
    )
    unmapped = (
        joined.filter(pl.col("sensor_type").is_not_null())
        .join(state_pairs, on=["sensor_type", "raw_value"], how="anti")
        .group_by("sensor_type", "raw_value")
        .len()
        .collect()
    )
    pairs = {
        (sensor_type, raw_value): count
        for sensor_type, raw_value, count in unmapped.iter_rows()
    }
    return CoverageReport(
        total_events=totals["total_events"],
        unknown_channel_events=totals["unknown_channel_events"],
        unmapped_type_value_pairs=pairs,
    )
