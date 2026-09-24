"""Behavioral checks for channel-day quality profiles and quarantine."""

from datetime import UTC, datetime

import polars as pl
import pytest

from fire_risk.data.quality import (
    QualityThresholds,
    mark_historical_artifacts,
    profile_channel_days,
)


def _dt(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def _events(rows: list[tuple[str, str, datetime, bool, str]]) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "event_id": [row[0] for row in rows],
            "channel_id": [row[1] for row in rows],
            "registered_at": [row[2] for row in rows],
            "alarm_flag": [row[3] for row in rows],
            "raw_value": [row[4] for row in rows],
            "source_year": [row[2].year for row in rows],
        }
    ).lazy()


def _thresholds() -> QualityThresholds:
    return QualityThresholds(
        min_burst_events=4,
        max_repeats_per_second=3,
        max_event_rate_deviation=3.0,
        min_stuck_run=4,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_burst_events", 1),
        ("min_stuck_run", 0),
        ("max_repeats_per_second", 1.5),
        ("min_burst_events", True),
        ("max_event_rate_deviation", float("nan")),
        ("max_event_rate_deviation", float("inf")),
        ("max_event_rate_deviation", 1.0),
    ],
)
def test_threshold_schema_rejects_unsafe_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        QualityThresholds(**{field: value})  # type: ignore[arg-type]


def test_profile_preserves_source_year_for_calibration() -> None:
    source = _events([("a", "A", _dt(2024, 6, 1), False, "normal")])
    assert profile_channel_days(source).collect()["source_year"].to_list() == [2024]


def test_anomalous_day_does_not_exclude_entire_2021_or_other_channel() -> None:
    rows = [
        ("a0", "A", _dt(2021, 5, 3, 12), False, "normal"),
        ("a1", "A", _dt(2021, 5, 4, 12), False, "normal"),
        ("a2", "A", _dt(2021, 5, 4, 12), False, "normal"),
        ("a3", "A", _dt(2021, 5, 4, 12), False, "normal"),
        ("a4", "A", _dt(2021, 5, 4, 12), False, "normal"),
        ("a5", "A", _dt(2021, 5, 5, 12), False, "normal"),
        ("b0", "B", _dt(2021, 5, 4, 12), False, "normal"),
        ("a6", "A", _dt(2022, 5, 4, 12), False, "normal"),
    ]
    events = _events(rows)
    marked = mark_historical_artifacts(
        events, profile_channel_days(events), _thresholds()
    )

    assert isinstance(marked, pl.LazyFrame)
    by_id = {row["event_id"]: row for row in marked.collect().to_dicts()}
    for event_id in ("a1", "a2", "a3", "a4"):
        assert by_id[event_id]["burst"] is True
        assert by_id[event_id]["historical_artifact"] is True
        assert by_id[event_id]["exclude_from_fire_training"] is True
    for event_id in ("a0", "a5", "a6", "b0"):
        assert by_id[event_id]["historical_artifact"] is False
        assert by_id[event_id]["exclude_from_fire_training"] is False


def test_profile_counts_alarms_values_repeats_and_consecutive_runs() -> None:
    events = _events(
        [
            ("3", "A", _dt(2021, 5, 4, 9, 0, 1), True, "open"),
            ("1", "A", _dt(2021, 5, 4, 9), False, "closed"),
            ("2", "A", _dt(2021, 5, 4, 9), False, "closed"),
            ("4", "A", _dt(2021, 5, 4, 9, 0, 2), False, "closed"),
            ("5", "A", _dt(2021, 5, 4, 9, 0, 3), False, "closed"),
            ("6", "A", _dt(2021, 5, 5, 9), False, "closed"),
        ]
    )

    profiles = profile_channel_days(events)

    assert isinstance(profiles, pl.LazyFrame)
    day = profiles.collect().sort("day").to_dicts()[0]
    assert day["event_count"] == 5
    assert day["alarm_count"] == 1
    assert day["alarm_share"] == 0.2
    assert day["unique_values"] == 2
    assert day["max_repeats_per_second"] == 2
    assert day["longest_identical_state_run"] == 2


def test_repeats_are_counted_in_whole_seconds() -> None:
    events = _events(
        [
            ("a", "A", _dt(2021, 5, 4, 9, 0, 0, 100000), False, "x"),
            ("b", "A", _dt(2021, 5, 4, 9, 0, 0, 900000), False, "y"),
            ("c", "A", _dt(2021, 5, 4, 9, 0, 1), False, "z"),
        ]
    )

    assert profile_channel_days(events).collect()["max_repeats_per_second"][0] == 2


def test_rate_baseline_uses_only_prior_days_of_same_channel() -> None:
    events = _events(
        [
            ("a0", "A", _dt(2020, 1, 1), False, "x"),
            ("a1", "A", _dt(2020, 1, 2), False, "x"),
            ("a2", "A", _dt(2020, 1, 2, 1), False, "y"),
            ("a3", "A", _dt(2021, 1, 1), False, "x"),
            ("a4", "A", _dt(2021, 1, 1, 1), False, "y"),
            ("a5", "A", _dt(2021, 1, 1, 2), False, "z"),
            ("a6", "A", _dt(2021, 1, 1, 3), False, "w"),
            ("b0", "B", _dt(2021, 1, 1), False, "x"),
        ]
    )

    rows = profile_channel_days(events).collect().sort(["channel_id", "day"]).to_dicts()
    a_rows = [row for row in rows if row["channel_id"] == "A"]
    b_row = next(row for row in rows if row["channel_id"] == "B")

    assert a_rows[0]["historical_median_event_count"] is None
    assert a_rows[1]["historical_median_event_count"] == 1
    assert a_rows[2]["historical_median_event_count"] == 1.5
    assert a_rows[2]["event_rate_deviation"] == 4 / 1.5
    assert b_row["historical_median_event_count"] is None


def test_stuck_threshold_is_inclusive_and_run_resets_at_day_boundary() -> None:
    events = _events(
        [
            ("a0", "A", _dt(2021, 5, 3, 23, 59), False, "same"),
            ("a1", "A", _dt(2021, 5, 4, 0), False, "same"),
            ("a2", "A", _dt(2021, 5, 4, 1), False, "same"),
            ("a3", "A", _dt(2021, 5, 4, 2), False, "same"),
            ("a4", "A", _dt(2021, 5, 4, 3), False, "same"),
            ("b0", "B", _dt(2021, 5, 4, 0), False, "same"),
        ]
    )
    marked = mark_historical_artifacts(
        events, profile_channel_days(events), _thresholds()
    )
    by_id = {row["event_id"]: row for row in marked.collect().to_dicts()}

    assert by_id["a0"]["stuck"] is False
    assert all(
        by_id[event_id]["stuck"] is True for event_id in ("a1", "a2", "a3", "a4")
    )
    assert by_id["b0"]["stuck"] is False


def test_marking_preserves_upstream_quality_flags() -> None:
    events = _events(
        [
            ("a", "A", _dt(2021, 5, 4, 9), False, "same"),
            ("b", "A", _dt(2021, 5, 4, 9), False, "same"),
            ("c", "A", _dt(2021, 5, 4, 9), False, "same"),
            ("d", "A", _dt(2021, 5, 4, 9), False, "same"),
        ]
    ).with_columns(pl.lit(["unknown_channel"]).alias("quality_flags"))

    marked = mark_historical_artifacts(
        events, profile_channel_days(events), _thresholds()
    )

    assert (
        marked.collect()["quality_flags"].to_list()
        == [["unknown_channel", "burst", "stuck", "historical_artifact"]] * 4
    )
