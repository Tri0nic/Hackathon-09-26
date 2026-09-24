"""Sanitize event journals to disk with bounded Python memory, then scan lazily."""

import atexit
import csv
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TextIO

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
_MAX_RECORD_CHARS = 1_048_576


class _RecordTooLarge(Exception):
    pass


class _RecordLines(Iterator[str]):
    """Bound one csv.reader call and remember where recovery should resume."""

    def __init__(self, handle: TextIO) -> None:
        self.handle = handle
        self.first_line: str | None = None
        self.next_record_position = 0
        self.consumed = 0
        self.quote_state = "start"

    def __next__(self) -> str:
        line = self.handle.readline(_MAX_RECORD_CHARS - self.consumed + 1)
        if not line:
            raise StopIteration
        first = self.first_line is None
        if first:
            self.first_line = line
        self.consumed += len(line)
        if self.consumed > _MAX_RECORD_CHARS:
            # readline(size) may stop inside a physical line. Drain it in fixed
            # chunks, never handing a partial line to the CSV parser.
            while line and not line.endswith(("\n", "\r")):
                line = self.handle.readline(65_536)
            if line.endswith("\r"):
                position = self.handle.tell()
                if self.handle.read(1) != "\n":
                    self.handle.seek(position)
            if first:
                self.next_record_position = self.handle.tell()
            raise _RecordTooLarge
        if first:
            self.next_record_position = self.handle.tell()
        # csv.reader(strict=True) permits quotes inside unquoted fields. RFC4180
        # does not, so validate quote boundaries as well as its parser errors.
        for char in line:
            if self.quote_state == "quoted":
                if char == '"':
                    self.quote_state = "closed"
            elif self.quote_state == "closed":
                if char == '"':
                    self.quote_state = "quoted"
                elif char in ",\r\n":
                    self.quote_state = "start"
                else:
                    raise csv.Error("characters after a closing quote")
            elif char == '"':
                if self.quote_state != "start":
                    raise csv.Error("quote inside an unquoted field")
                self.quote_state = "quoted"
            elif char in ",\r\n":
                self.quote_state = "start"
            else:
                self.quote_state = "unquoted"
        return line


def _read_record(handle: TextIO) -> tuple[list[str], str | None] | None:
    lines = _RecordLines(handle)
    try:
        row = next(csv.reader(lines, strict=True), None)
        return None if row is None else (row, None)
    except (csv.Error, _RecordTooLarge) as error:
        reason = (
            "record_too_large"
            if isinstance(error, _RecordTooLarge) or "field larger" in str(error)
            else "invalid_csv_quoting"
        )
        # An unfinished quote may have consumed neighboring physical lines.
        # Retry from the first line after the malformed record, preserving valid
        # multiline records whenever strict parsing succeeds.
        handle.seek(lines.next_record_position)
        try:
            row = next(csv.reader([lines.first_line or ""]), [])
        except csv.Error:
            row = []
        return row, reason


@cache
def _spool_directory() -> Path:
    directory = TemporaryDirectory(prefix="fire-risk-csv-")
    # LazyFrame transformations/clones do not retain arbitrary Python owners.
    # Keep the owner alive until normal process exit, then remove every spool.
    atexit.register(directory.cleanup)
    return Path(directory.name)


def _sanitize_csv(path: Path, temp_dir: Path | None = None) -> Path:
    """Write one row at a time; no collection grows with good or bad row count."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        record = _read_record(handle)
        header, header_error = record if record is not None else ([], None)
        if (
            header_error
            or not set(_REQUIRED_FIELDS).issubset(header)
            or len(set(header)) != len(header)
        ):
            raise ValueError(f"{path}: missing, duplicate or malformed CSV columns")
        positions = [header.index(field) for field in _REQUIRED_FIELDS]
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            dir=temp_dir if temp_dir is not None else _spool_directory(),
            delete=False,
        ) as output:
            spool = Path(output.name)
            try:
                writer = csv.writer(output)
                writer.writerow([*_REQUIRED_FIELDS, "_shape_reason", "_source_index"])
                index = 0
                while (record := _read_record(handle)) is not None:
                    row, reason = record
                    if reason is None and len(row) != len(header):
                        reason = (
                            "too_few_fields"
                            if len(row) < len(header)
                            else "extra_fields"
                        )
                    writer.writerow(
                        [
                            *[
                                row[pos] if pos < len(row) else None
                                for pos in positions
                            ],
                            reason,
                            index,
                        ]
                    )
                    index += 1
            except BaseException:
                output.close()
                spool.unlink(missing_ok=True)
                raise
    return spool


def _scan_annotated(path: Path, temp_dir: Path | None = None) -> pl.LazyFrame:
    source = pl.scan_csv(
        _sanitize_csv(path, temp_dir),
        encoding="utf8",
        infer_schema=False,
        schema_overrides={"_source_index": pl.UInt64},
        raise_if_empty=False,
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


def partition_events(
    paths: list[Path], *, temp_dir: Path | None = None
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Return valid rows and explicit row-level quarantine with source identity.

    Streaming sanitation uses a bounded record buffer. An explicit temp_dir is
    caller-owned; otherwise process-owned spools are removed at normal exit.
    Field validation and both partitions are lazy.
    source_row counts logical CSV records including the header, not physical
    lines when quoted values span lines. On quote/size errors, recovery treats
    the first physical line as the malformed record and retries its neighbors.
    """
    events = pl.concat([_scan_annotated(path, temp_dir) for path in paths])
    valid = events.filter(pl.col("quality_reason").is_null()).drop("quality_reason")
    bad = events.filter(pl.col("quality_reason").is_not_null())
    return valid, bad
