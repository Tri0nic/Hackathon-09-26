"""Object-scoped episode grouping and event membership."""

from datetime import UTC, datetime, timedelta

import polars as pl

from fire_risk.data.episodes import build_episodes

START = datetime(2024, 1, 2, 3, 0, tzinfo=UTC)


def _events(*minutes: int) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "event_id": [f"event-{minute}" for minute in minutes],
            "channel_id": ["channel-1"] * len(minutes),
            "object_id": ["object-1"] * len(minutes),
            "registered_at": [START + timedelta(minutes=minute) for minute in minutes],
            "sensor_type": ["smoke"] * len(minutes),
            "alarm_flag": [True] * len(minutes),
            "picket_sort_key": [3.0] * len(minutes),
            "quality_flags": [[] for _ in minutes],
        }
    ).lazy()


def test_repeated_events_inside_gap_form_one_episode() -> None:
    episodes, membership = build_episodes(_events(0, 4, 12), timedelta(minutes=30))

    assert isinstance(episodes, pl.LazyFrame)
    assert isinstance(membership, pl.LazyFrame)
    assert episodes.collect().height == 1
    assert membership.collect()["episode_id"].n_unique() == 1


def test_event_after_gap_starts_new_episode() -> None:
    episodes, membership = build_episodes(_events(0, 31), timedelta(minutes=30))

    assert episodes.collect().height == 2
    assert membership.collect()["episode_id"].n_unique() == 2


def test_equal_gap_and_chained_events_stay_in_one_episode() -> None:
    episodes, membership = build_episodes(_events(0, 30, 60), timedelta(minutes=30))

    assert episodes.collect().height == 1
    assert membership.collect()["episode_id"].n_unique() == 1


def test_same_time_on_two_objects_creates_two_episodes() -> None:
    events = _events(0, 1).with_columns(
        pl.Series("object_id", ["object-1", "object-2"]),
        pl.lit(START).alias("registered_at"),
    )

    episodes, membership = build_episodes(events, timedelta(minutes=30))

    assert episodes.collect().height == 2
    assert membership.collect()["episode_id"].n_unique() == 2


def test_event_without_picket_remains_in_episode() -> None:
    events = _events(0).with_columns(pl.lit(None).alias("picket_sort_key"))

    episodes, membership = build_episodes(events, timedelta(minutes=30))

    assert membership.collect().height == 1
    assert episodes.collect()["picket_from"].item() is None
    assert episodes.collect()["picket_to"].item() is None


def test_unknown_object_event_is_retained_without_episode() -> None:
    events = _events(0, 1, 2).with_columns(
        pl.Series("object_id", ["object-1", None, None]),
        pl.Series("channel_id", ["known", "unknown-a", "unknown-b"]),
    )

    episodes, membership = build_episodes(events, timedelta(minutes=30))

    assert episodes.collect().height == 1
    assert membership.collect().to_dicts() == [
        {"event_id": "event-0", "episode_id": episodes.collect()["episode_id"].item()},
        {"event_id": "event-1", "episode_id": None},
        {"event_id": "event-2", "episode_id": None},
    ]


def test_episode_aggregates_distinct_channels_types_pickets_flags_and_alarm() -> None:
    events = _events(0, 5, 10).with_columns(
        pl.Series("channel_id", ["z", "a", "z"]),
        pl.Series("sensor_type", ["smoke", "heat", None]),
        pl.Series("alarm_flag", [False, True, False]),
        pl.Series("picket_sort_key", [8.0, None, 3.0]),
        pl.Series("quality_flags", [["burst"], ["unknown_state", "burst"], []]),
    )

    episodes, _ = build_episodes(events, timedelta(minutes=30))

    row = episodes.collect().row(0, named=True)
    assert row["object_id"] == "object-1"
    assert row["started_at"] == START
    assert row["ended_at"] == START + timedelta(minutes=10)
    assert row["severity"] == "alarm"
    assert row["channel_ids"] == ["a", "z"]
    assert row["sensor_types"] == ["heat", "smoke"]
    assert row["picket_from"] == 3.0
    assert row["picket_to"] == 8.0
    assert row["quality_flags"] == ["burst", "unknown_state"]


def test_episode_without_alarm_has_unknown_severity() -> None:
    episodes, _ = build_episodes(
        _events(0).with_columns(pl.lit(False).alias("alarm_flag")),
        timedelta(minutes=30),
    )

    assert episodes.collect()["severity"].item() == "unknown"


def test_empty_quality_flags_aggregate_to_empty_list() -> None:
    episodes, _ = build_episodes(_events(0, 5), timedelta(minutes=30))

    assert episodes.collect()["quality_flags"].to_list() == [[]]


def test_all_unknown_objects_produce_only_null_membership() -> None:
    events = _events(0, 1).with_columns(pl.lit(None, dtype=pl.String).alias("object_id"))

    episodes, membership = build_episodes(events, timedelta(minutes=30))

    assert episodes.collect().is_empty()
    assert membership.collect().to_dicts() == [
        {"event_id": "event-0", "episode_id": None},
        {"event_id": "event-1", "episode_id": None},
    ]


def test_episode_ids_and_output_order_are_independent_of_input_order() -> None:
    events = _events(0, 31, 32).with_columns(
        pl.Series("object_id", ["object-b", "object-a", "object-a"]),
        pl.Series("channel_id", ["z", "x", "y"]),
    )
    first_episodes, first_membership = build_episodes(events, timedelta(minutes=30))
    reversed_episodes, reversed_membership = build_episodes(
        events.sort("event_id", descending=True), timedelta(minutes=30)
    )

    assert first_episodes.collect().to_dicts() == reversed_episodes.collect().to_dicts()
    assert first_membership.collect().to_dicts() == reversed_membership.collect().to_dicts()
    assert first_episodes.collect()["episode_id"].n_unique() == 2
