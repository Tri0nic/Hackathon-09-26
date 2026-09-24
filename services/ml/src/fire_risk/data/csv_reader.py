"""Read event journals without materializing the source CSV files."""

import csv
from pathlib import Path

import polars as pl

_REQUIRED_FIELDS = {
    "ид_события": "missing_event_id",
    "ид_канала_данных": "missing_channel_id",
    "дата": "missing_date",
    "время": "missing_time",
    "тревожное": "missing_alarm_flag",
    "значение_датчика": "missing_raw_value",
}
_CANONICAL_FIELDS = (
    "event_id",
    "channel_id",
    "registered_at",
    "alarm_flag",
    "raw_value",
    "source_year",
)


def _preflight_shapes(path: Path) -> list[tuple[int, str]]:
    """Stream CSV records, retaining only ragged-record indices and reasons."""
    malformed: list[tuple[int, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if not set(_REQUIRED_FIELDS).issubset(header) or len(set(header)) != len(
            header
        ):
            raise ValueError(f"{path}: missing or duplicate required CSV columns")
        for index, row in enumerate(reader):
            if len(row) != len(header):
                malformed.append(
                    (
                        index,
                        "too_few_fields" if len(row) < len(header) else "extra_fields",
                    )
                )
    return malformed


def _scan_annotated(path: Path) -> pl.LazyFrame:
    malformed = _preflight_shapes(path)
    # Truncation is safe only with the independent shape audit: extra cells
    # cannot abort the scan, and their records are always quarantined below.
    source = pl.scan_csv(
        path,
        encoding="utf8",
        infer_schema=False,
        truncate_ragged_lines=True,
        row_index_name="_source_index",
        raise_if_empty=False,
    )
    if malformed:
        shapes = pl.DataFrame(
            malformed,
            schema={"_source_index": pl.get_index_type(), "_shape_reason": pl.String},
            orient="row",
        )
        source = source.join(
            shapes.lazy(), on="_source_index", how="left", maintain_order="left"
        )
    else:
        source = source.with_columns(
            pl.lit(None, dtype=pl.String).alias("_shape_reason")
        )
    registered_at = pl.concat_str(
        [pl.col("дата"), pl.col("время")], separator=" "
    ).str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=False)
    alarm_text = pl.col("тревожное").str.strip_chars().str.to_lowercase()
    reason = pl.coalesce(
        pl.col("_shape_reason"),
        *[
            pl.when(pl.col(field).str.strip_chars().eq("").fill_null(True)).then(
                pl.lit(reason)
            )
            for field, reason in _REQUIRED_FIELDS.items()
        ],
        pl.when(~alarm_text.is_in(["t", "true", "1", "f", "false", "0"])).then(
            pl.lit("invalid_alarm_flag")
        ),
        pl.when(registered_at.is_null()).then(pl.lit("invalid_timestamp")),
    )
    return source.select(
        pl.col("ид_события").cast(pl.String).alias("event_id"),
        pl.col("ид_канала_данных").cast(pl.String).alias("channel_id"),
        registered_at.alias("registered_at"),
        alarm_text.is_in(["t", "true", "1"]).alias("alarm_flag"),
        pl.col("значение_датчика").alias("raw_value"),
        registered_at.dt.year().alias("source_year"),
        reason.alias("quality_reason"),
        pl.lit(str(path.resolve())).alias("source_file"),
        (pl.col("_source_index") + 2).alias("source_row"),
    )


def scan_events(paths: list[Path]) -> pl.LazyFrame:
    """Scan canonical raw columns; use partition_events for validated inputs."""
    return pl.concat([_scan_annotated(path) for path in paths]).select(
        _CANONICAL_FIELDS
    )


def partition_events(paths: list[Path]) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Return valid rows and explicit row-level quarantine with source identity.

    A streaming structural preflight stores only malformed record indices.
    Field/value validation and subsequent event processing remain lazy.
    source_row counts logical CSV records including the header, not physical
    lines when quoted values span lines.
    """
    events = pl.concat([_scan_annotated(path) for path in paths])
    valid = events.filter(pl.col("quality_reason").is_null()).drop("quality_reason")
    bad = events.filter(pl.col("quality_reason").is_not_null())
    return valid, bad
