from pathlib import Path

import polars as pl

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
