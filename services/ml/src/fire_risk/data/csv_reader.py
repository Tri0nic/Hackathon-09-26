"""Read event journals without materializing the source CSV files."""

from pathlib import Path

import polars as pl


def scan_events(paths: list[Path]) -> pl.LazyFrame:
    """Scan event journals into the canonical raw-event columns."""
    frames = [pl.scan_csv(path, encoding="utf8", infer_schema=False) for path in paths]
    source = pl.concat(frames)
    registered_at = pl.concat_str(
        [pl.col("дата"), pl.col("время")], separator=" "
    ).str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False)
    return source.select(
        pl.col("ид_события").cast(pl.String).alias("event_id"),
        pl.col("ид_канала_данных").cast(pl.String).alias("channel_id"),
        registered_at.alias("registered_at"),
        pl.col("тревожное").str.to_lowercase().is_in(["t", "true", "1"]).alias("alarm_flag"),
        pl.col("значение_датчика").alias("raw_value"),
        registered_at.dt.year().alias("source_year"),
    )


def partition_events(paths: list[Path]) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Separate rows with invalid timestamps for quality review."""
    events = scan_events(paths)
    valid = events.filter(pl.col("registered_at").is_not_null())
    bad = events.filter(pl.col("registered_at").is_null()).with_columns(
        pl.lit("invalid_timestamp").alias("quality_reason")
    )
    return valid, bad
