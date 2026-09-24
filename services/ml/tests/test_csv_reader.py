import gc
import json
import os
import subprocess
import sys
import tracemalloc
from hashlib import file_digest
from pathlib import Path

import polars as pl
import pytest

from fire_risk.data.csv_reader import partition_events, scan_events

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"


def test_scan_events_builds_canonical_lazy_rows() -> None:
    lazy = scan_events([FIXTURES / "events.csv"])

    assert isinstance(lazy, pl.LazyFrame)
    frame = lazy.collect()
    assert frame.columns == [
        "event_id",
        "channel_id",
        "registered_at",
        "alarm_flag",
        "raw_value",
        "source_year",
    ]
    assert frame["event_id"].to_list() == ["1", "2"]
    assert frame["channel_id"].to_list() == ["120578", "120298"]
    assert frame["registered_at"].dt.strftime("%Y-%m-%d %H:%M:%S").to_list() == [
        "2026-08-01 03:09:27",
        "2026-08-01 03:10:00",
    ]
    assert frame["alarm_flag"].to_list() == [True, False]
    assert frame["raw_value"].to_list() == ["Обнаружен дым", "28"]
    assert frame["source_year"].to_list() == [2026, 2026]


def test_invalid_timestamp_is_quarantined_without_dropping_valid_rows() -> None:
    valid, bad = partition_events([FIXTURES / "events_malformed.csv"])

    assert isinstance(valid, pl.LazyFrame)
    assert isinstance(bad, pl.LazyFrame)
    assert valid.collect()["event_id"].to_list() == ["3"]
    quarantined = bad.collect()
    assert quarantined["event_id"].to_list() == ["4"]
    assert quarantined["quality_reason"].to_list() == ["invalid_timestamp"]


@pytest.mark.parametrize(
    ("bad_row", "reason"),
    [
        ("2,001,2024-01-03,00:01:00,f,", "missing_raw_value"),
        ("2,001,2024-01-03,00:01:00,f", "too_few_fields"),
        ("2,001,2024-01-03,00:01:00,f,20,extra", "extra_fields"),
        (",001,2024-01-03,00:01:00,f,20", "missing_event_id"),
        ("2,,2024-01-03,00:01:00,f,20", "missing_channel_id"),
        ("2,001,,00:01:00,f,20", "missing_date"),
        ("2,001,2024-01-03,,f,20", "missing_time"),
        ("2,001,2024-01-03,00:01:00,,20", "missing_alarm_flag"),
        ("2,001,2024-01-03,00:01:00,maybe,20", "invalid_alarm_flag"),
        ("2,001,2024-01-03,00:01:00,f,   ", "missing_raw_value"),
        ('2,001,2024-01-03,00:01:00,f,"20"oops', "invalid_csv_quoting"),
        ('2,001,2024-01-03,00:01:00,f,20"oops', "invalid_csv_quoting"),
        ('2,001,2024-01-03,00:01:00,f,"unfinished', "invalid_csv_quoting"),
        ("", "too_few_fields"),
    ],
)
def test_malformed_record_is_quarantined_without_losing_valid_neighbors(
    tmp_path: Path,
    bad_row: str,
    reason: str,
) -> None:
    source = tmp_path / "malformed.csv"
    source.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,f,20\n" + bad_row + "\n"
        '3,001,2024-01-03,00:02:00,t,"Тревога, дым"\n',
        encoding="utf-8",
    )
    valid, bad = partition_events([source])
    assert isinstance(valid, pl.LazyFrame)
    assert isinstance(bad, pl.LazyFrame)
    assert valid.collect()["event_id"].to_list() == ["1", "3"]
    assert valid.collect()["raw_value"].to_list() == ["20", "Тревога, дым"]
    quarantined = bad.collect()
    assert quarantined.height == 1
    assert quarantined["quality_reason"].item() == reason
    assert quarantined["source_row"].item() == 3
    assert quarantined["source_file"].item() == str(source.resolve())


def test_many_malformed_rows_preserve_valid_neighbors_and_multiline_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        handle.write(HEADER)
        for block in range(4_000):
            if block % 400 == 0:
                handle.write(f"valid-{block},001,2024-01-03,00:00:00,f,20\n")
            handle.write(f"extra-{block},001,2024-01-03,00:00:00,f,20,extra\n")
            handle.write(f"missing-{block},001,2024-01-03,00:00:00,f,\n")
            handle.write(f'quote-{block},001,2024-01-03,00:00:00,f,"20"oops\n')
        handle.write('last,001,2024-01-03,00:00:00,t,"Тревога, дым\r\nи ""газ"""\n')
    with source.open("rb") as handle:
        before_hash = file_digest(handle, "sha256").hexdigest()

    valid, bad = partition_events([source])

    assert isinstance(valid, pl.LazyFrame)
    assert isinstance(bad, pl.LazyFrame)
    rows = valid.collect()
    assert rows["event_id"].to_list() == [
        "valid-0",
        "valid-400",
        "valid-800",
        "valid-1200",
        "valid-1600",
        "valid-2000",
        "valid-2400",
        "valid-2800",
        "valid-3200",
        "valid-3600",
        "last",
    ]
    assert rows["raw_value"][-1] == 'Тревога, дым\r\nи "газ"'
    assert rows["source_row"][0] == 2
    assert rows["source_row"][-1] == 12_012
    assert dict(bad.group_by("quality_reason").len().collect().iter_rows()) == {
        "extra_fields": 4_000,
        "missing_raw_value": 4_000,
        "invalid_csv_quoting": 4_000,
    }
    assert (
        bad.select(pl.struct("source_file", "source_row").n_unique()).collect().item()
        == 12_000
    )
    with source.open("rb") as handle:
        assert file_digest(handle, "sha256").hexdigest() == before_hash


def test_quarantine_python_memory_does_not_grow_with_bad_row_count(
    tmp_path: Path,
) -> None:
    peaks = []
    for count in (10_000, 100_000):
        source = tmp_path / f"all-bad-{count}.csv"
        with source.open("w", encoding="utf-8") as handle:
            handle.write(HEADER)
            for index in range(count):
                handle.write(f"{index},001,2024-01-03,00:00:00,f,20,extra\n")
        gc.collect()
        tracemalloc.start()
        try:
            valid, bad = partition_events([source])
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert valid.select(pl.len()).collect().item() == 0
        assert bad.select(pl.len()).collect().item() == count
    # A tenfold increase must not allocate a tuple/list entry per bad record.
    assert peaks[1] < peaks[0] + 1_000_000, peaks
    assert peaks[1] < 3_000_000, peaks


def test_input_files_keep_distinct_source_rows_and_years(tmp_path: Path) -> None:
    sources = []
    for year in (2023, 2024):
        source = tmp_path / f"{year}.csv"
        source.write_text(
            HEADER
            + f"same-id,001,{year}-01-03,00:00:00,f,20\n"
            + f'same-bad-id,001,{year}-01-03,00:01:00,f,"20"oops\n',
            encoding="utf-8",
        )
        sources.append(source)

    valid, bad = partition_events(sources)

    assert valid.collect()["source_year"].to_list() == [2023, 2024]
    assert bad.collect()["source_year"].to_list() == [2023, 2024]
    all_rows = pl.concat([valid, bad.drop("quality_reason")]).collect()
    assert (
        all_rows.select(pl.struct("source_file", "source_row").n_unique()).item() == 4
    )
    assert all_rows["source_row"].to_list() == [2, 2, 3, 3]


def test_oversized_unfinished_record_does_not_consume_following_valid_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "oversized.csv"
    with source.open("w", encoding="utf-8") as handle:
        handle.write(HEADER)
        handle.write('too-large,001,2024-01-03,00:00:00,f,"')
        for _ in range(32):
            handle.write("x" * 65_536)
        handle.write("\nneighbor,001,2024-01-03,00:01:00,f,20\n")

    valid, bad = partition_events([source])

    assert valid.collect()["event_id"].to_list() == ["neighbor"]
    assert bad.collect()["quality_reason"].to_list() == ["record_too_large"]


def test_oversized_crlf_record_keeps_one_quarantine_identity(tmp_path: Path) -> None:
    source = tmp_path / "oversized-crlf.csv"
    prefix = 'too-large,001,2024-01-03,00:00:00,f,"'
    with source.open("w", encoding="utf-8", newline="") as handle:
        handle.write(HEADER)
        handle.write(prefix)
        handle.write("x" * (1_048_576 - len(prefix)))
        handle.write("\r\nneighbor,001,2024-01-03,00:01:00,f,20\r\n")

    valid, bad = partition_events([source])

    assert bad.collect()["source_row"].to_list() == [2]
    assert valid.collect()["source_row"].to_list() == [3]


def test_lazy_temp_backing_survives_collection_and_is_removed_at_process_exit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "events.csv"
    source.write_text(
        HEADER
        + "1,001,2024-01-03,00:00:00,f,20\n"
        + '2,001,2024-01-03,00:01:00,f,"20"oops\n',
        encoding="utf-8",
    )
    spool_parent = tmp_path / "os-temp"
    spool_parent.mkdir()
    code = """
import gc
import json
import sys
from pathlib import Path
import polars as pl
from fire_risk.data.csv_reader import partition_events
valid, bad = partition_events([Path(sys.argv[1])])
derived = valid.select(pl.len())
del valid
gc.collect()
assert derived.collect().item() == 1
assert bad.select(pl.len()).collect().item() == 1
assert derived.collect().item() == 1
print(json.dumps([str(path) for path in Path(sys.argv[2]).rglob('*') if path.is_file()]))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(source), str(spool_parent)],
        env={
            **os.environ,
            **{key: str(spool_parent) for key in ("TMP", "TEMP", "TMPDIR")},
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout), "Expected disk backing while LazyFrames are alive"
    assert list(spool_parent.iterdir()) == []
