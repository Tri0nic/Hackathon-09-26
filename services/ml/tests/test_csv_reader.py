from pathlib import Path

import polars as pl
import pytest

from fire_risk.data.csv_reader import partition_events, scan_events

FIXTURES = Path(__file__).parent / "fixtures"


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
