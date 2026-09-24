from pathlib import Path

import polars as pl
import pytest

from fire_risk.data.references import (
    ReferenceIntegrityError,
    build_coverage_report,
    join_channels,
    scan_channel_reference,
    scan_state_reference,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_exact_russian_channel_headers_map_without_manual_rename() -> None:
    row = scan_channel_reference(FIXTURES / "channels_russian.csv").collect().row(
        0, named=True
    )
    assert row["channel_id"] == "120578"
    assert row["object_id"] == "42"
    assert row["object_name"] == "Объект 42"


def test_same_alarm_multiple_state_sets_are_known_and_preserved() -> None:
    mapping = scan_state_reference(FIXTURES / "states_russian.csv").collect()
    row = mapping.filter(pl.col("state_name") == "Норма").row(0, named=True)
    assert row["alarm_flag"] is False
    assert row["state_set_ids"] == ["1", "2"]
    assert row["is_conflicting"] is False


def test_true_false_mapping_retains_ids_and_null_alarm() -> None:
    mapping = scan_state_reference(FIXTURES / "states_russian.csv").collect()
    row = mapping.filter(pl.col("state_name") == "Температура ниже 3ºC1").row(
        0, named=True
    )

    assert row["alarm_flag"] is None
    assert row["state_set_ids"] == ["13"]
    assert row["is_conflicting"] is True


def test_russian_channel_schema_accepts_bom_and_shuffled_columns(tmp_path: Path) -> None:
    source = pl.read_csv(FIXTURES / "channels_russian.csv", infer_schema=False)
    shuffled = tmp_path / "channels_bom.csv"
    shuffled.write_text(
        "\ufeff" + source.select(reversed(source.columns)).write_csv(),
        encoding="utf-8",
    )

    row = scan_channel_reference(shuffled).collect().row(0, named=True)

    assert row["channel_id"] == "120578"
    assert row["object_id"] == "42"


def test_canonical_reference_headers_remain_supported() -> None:
    channel = scan_channel_reference(FIXTURES / "channels.csv").collect().row(
        0, named=True
    )
    state = scan_state_reference(FIXTURES / "states.csv").collect().row(0, named=True)

    assert channel["channel_id"] == "001"
    assert channel["object_id"] == "object-1"
    assert state["sensor_type"] == "Датчик дыма"
    assert state["alarm_flag"] is False


def test_partial_russian_channel_schema_lists_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "partial.csv"
    pl.read_csv(FIXTURES / "channels_russian.csv", infer_schema=False).drop(
        "Имя"
    ).write_csv(path)

    with pytest.raises(ReferenceIntegrityError, match=r"missing=\['Имя'\]; unexpected=\[\]"):
        scan_channel_reference(path)


def test_unexpected_state_header_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "unexpected.csv"
    pl.read_csv(FIXTURES / "states.csv", infer_schema=False).with_columns(
        pl.lit("unused").alias("surprise")
    ).write_csv(path)

    with pytest.raises(ReferenceIntegrityError, match=r"missing=\[\]; unexpected=\['surprise'\]"):
        scan_state_reference(path)


def test_exact_state_duplicates_collapse(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.csv"
    source = (FIXTURES / "states.csv").read_text(encoding="utf-8")
    path.write_text(source + source.splitlines()[1] + "\n", encoding="utf-8")

    rows = scan_state_reference(path).collect()

    assert rows.height == 1
    assert rows.row(0, named=True)["state_set_ids"] == ["smoke-states"]


def test_alarm_tokens_normalize_strictly(tmp_path: Path) -> None:
    path = tmp_path / "tokens.csv"
    path.write_text(
        "sensor_type,state_set_id,state_name,alarm_flag\n"
        "T,1,a,true\nT,1,b,t\nT,1,c,1\n"
        "T,1,d,false\nT,1,e,f\nT,1,g,0\n",
        encoding="utf-8",
    )

    rows = scan_state_reference(path).collect()
    flags = {row["state_name"]: row["alarm_flag"] for row in rows.iter_rows(named=True)}

    assert flags == {"a": True, "b": True, "c": True, "d": False, "e": False, "g": False}


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


def test_coverage_counts_same_alarm_multiple_sets_as_covered(tmp_path: Path) -> None:
    states = tmp_path / "states.csv"
    source = (FIXTURES / "states.csv").read_text(encoding="utf-8")
    states.write_text(source + "Датчик дыма,other,Норма,false\n", encoding="utf-8")

    report = build_coverage_report(events_fixture(), FIXTURES / "channels.csv", states)

    assert report.unmapped_type_value_pairs == {("Датчик дыма", "Обнаружен дым"): 1}
    assert report.conflicting_type_value_pairs == {}


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
