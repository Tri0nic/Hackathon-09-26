from pathlib import Path

import polars as pl
import pytest

from fire_risk.data.references import (
    ReferenceIntegrityError,
    build_coverage_report,
    join_channels,
)

FIXTURES = Path(__file__).parent / "fixtures"


def events_fixture() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "event_id": ["1", "2", "3"],
            "channel_id": ["001", "002", "missing"],
            "raw_value": ["Обнаружен дым", "Норма", "Другое"],
        }
    )


def test_unknown_channel_is_preserved_with_quality_flag() -> None:
    joined = join_channels(events_fixture(), FIXTURES / "channels.csv")

    assert isinstance(joined, pl.LazyFrame)
    rows = joined.collect()
    assert rows.height == 3
    missing = rows.filter(pl.col("channel_id") == "missing").row(0, named=True)
    assert missing["object_id"] is None
    assert "unknown_channel" in missing["quality_flags"]
    known = rows.filter(pl.col("channel_id") == "001").row(0, named=True)
    assert known["object_id"] == "object-1"
    assert known["level1_object_name"] == "Шахта"
    assert known["quality_flags"] == []


def test_duplicate_channel_ids_are_rejected(tmp_path: Path) -> None:
    duplicate_csv = tmp_path / "channels.csv"
    source = (FIXTURES / "channels.csv").read_text(encoding="utf-8")
    duplicate_csv.write_text(source + source.splitlines()[1] + "\n", encoding="utf-8")

    with pytest.raises(ReferenceIntegrityError, match="001"):
        join_channels(events_fixture(), duplicate_csv)


def test_join_appends_unknown_flag_to_existing_flags() -> None:
    events = events_fixture().with_columns(
        pl.lit(["upstream_issue"]).alias("quality_flags")
    )

    rows = join_channels(events, FIXTURES / "channels.csv").collect()
    missing = rows.filter(pl.col("channel_id") == "missing").row(0, named=True)
    known = rows.filter(pl.col("channel_id") == "001").row(0, named=True)
    assert missing["quality_flags"] == ["upstream_issue", "unknown_channel"]
    assert known["quality_flags"] == ["upstream_issue"]


def test_coverage_report_counts_unknown_channels_and_unmapped_pairs() -> None:
    report = build_coverage_report(
        events_fixture(), FIXTURES / "channels.csv", FIXTURES / "states.csv"
    )

    assert report.total_events == 3
    assert report.unknown_channel_events == 1
    assert report.unmapped_type_value_pairs == {("Датчик дыма", "Обнаружен дым"): 1}


def test_conflicting_state_rows_are_reported_and_not_counted_as_covered(
    tmp_path: Path,
) -> None:
    states = tmp_path / "states.csv"
    source = (FIXTURES / "states.csv").read_text(encoding="utf-8")
    states.write_text(
        source + "Датчик дыма,other-states,Норма,true\n", encoding="utf-8"
    )

    report = build_coverage_report(events_fixture(), FIXTURES / "channels.csv", states)

    assert report.conflicting_type_value_pairs == {("Датчик дыма", "Норма"): 1}
    assert report.unmapped_type_value_pairs == {
        ("Датчик дыма", "Обнаружен дым"): 1,
        ("Датчик дыма", "Норма"): 1,
    }


def test_coverage_handles_entirely_null_optional_values() -> None:
    source = events_fixture().with_columns(pl.lit(None).alias("raw_value"))
    report = build_coverage_report(
        source, FIXTURES / "channels.csv", FIXTURES / "states.csv"
    )
    assert report.total_events == 3
    assert report.unknown_channel_events == 1
    assert report.unmapped_type_value_pairs == {("Датчик дыма", None): 2}
