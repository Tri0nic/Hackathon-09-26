"""Disk-backed profiling must bound event windows without changing daily semantics."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fire_risk.data.quality import profile_channel_days


def _source(path: Path, *, source_year: bool = True) -> pl.LazyFrame:
    start = datetime(2020, 12, 20, tzinfo=ZoneInfo("Europe/Moscow"))
    rows = []
    for day in range(45):
        for channel in ("A", "B"):
            for event in range(day % 5 + 3):
                rows.append(
                    {
                        "channel_id": channel,
                        "event_id": f"{day:03}-{channel}-{event:03}",
                        "registered_at": start
                        + timedelta(days=day, microseconds=event * 400000),
                        "raw_value": None
                        if event == 0
                        else "same"
                        if event < 5
                        else "other",
                        "alarm_flag": event >= 5,
                        # Journal provenance deliberately differs from event year.
                        "source_year": 2019 if channel == "A" else 2024,
                    }
                )
    frame = pl.DataFrame(rows).reverse()
    if not source_year:
        frame = frame.drop("source_year")
    frame.write_parquet(path, row_group_size=7)
    return pl.scan_parquet(path)


@pytest.mark.parametrize("source_year", [True, False])
def test_partitioned_profiles_match_global_semantics_across_months(
    tmp_path: Path, source_year: bool
) -> None:
    source = _source(tmp_path / "input.parquet", source_year=source_year)
    expected = profile_channel_days(source).collect()
    actual = profile_channel_days(source, temp_dir=tmp_path / "spool").collect()
    assert_frame_equal(actual, expected)
    a = actual.filter(pl.col("channel_id") == "A")
    assert a["historical_median_event_count"][0] is None
    assert a["historical_median_event_count"][1] == 3.0
    assert a["historical_median_event_count"][35] == 5.0
    assert a["longest_identical_state_run"].max() == 4
    assert a["max_repeats_per_second"].max() == 3


def test_partitioned_profile_result_scans_only_compact_daily_rows(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "events.parquet"
    source = _source(source_path)
    result = profile_channel_days(source, temp_dir=tmp_path / "spool")
    plan = result.show_graph(
        show=False, raw_output=True, engine="streaming", plan_stage="physical"
    )
    assert plan is not None
    assert str(source_path) not in plan
    assert "registered_at" not in plan
    assert "raw_value" not in plan
    assert "event_id" not in plan
    daily_files = list((tmp_path / "spool").rglob("daily/*.parquet"))
    assert len(daily_files) == 45
    assert (
        sum(
            pl.scan_parquet(path).select(pl.len()).collect().item()
            for path in daily_files
        )
        == 90
    )
    for path in (tmp_path / "spool").rglob("days/**/*.parquet"):
        assert (
            pl.scan_parquet(path)
            .select(pl.col("registered_at").dt.date().n_unique())
            .collect()
            .item()
            == 1
        )


def test_partitioned_empty_profiles_preserve_schema(tmp_path: Path) -> None:
    source = _source(tmp_path / "events.parquet").filter(pl.lit(False))
    assert_frame_equal(
        profile_channel_days(source, temp_dir=tmp_path / "spool").collect(),
        profile_channel_days(source).collect(),
    )
