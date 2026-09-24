"""Historical-only feature windows and independently attached incident targets."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fire_risk.config import PipelineConfig
from fire_risk.data.features import attach_horizon_targets, build_feature_snapshots
from fire_risk.data.quality import (
    QualityThresholds,
    causal_quality_flags,
    mark_historical_artifacts,
    profile_channel_days,
)

START = datetime(2024, 1, 3, tzinfo=UTC)


def events(minutes: list[int]) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "object_id": ["mine"] * len(minutes),
            "registered_at": [START + timedelta(minutes=m) for m in minutes],
            "channel_id": [f"ch-{i}" for i in range(len(minutes))],
            "sensor_type": ["smoke"] * len(minutes),
            "alarm_flag": [True] * len(minutes),
            "value_kind": ["known_state"] * len(minutes),
        },
        schema_overrides={
            "registered_at": pl.Datetime("us", "UTC"),
            "object_id": pl.String,
            "sensor_type": pl.String,
            "channel_id": pl.String,
            "value_kind": pl.String,
            "alarm_flag": pl.Boolean,
        },
    ).lazy()


def at_start(frame: pl.LazyFrame) -> pl.DataFrame:
    return frame.filter(pl.col("scoring_timestamp") == START).collect()


@pytest.mark.parametrize(
    "minutes,window", [(5, "5m"), (30, "30m"), (180, "3h"), (360, "6h"), (1440, "24h")]
)
def test_windows_exclude_left_boundary_and_include_scoring_time(
    minutes: int, window: str
) -> None:
    result = at_start(
        build_feature_snapshots(
            events([-minutes, -minutes + 1, 0, 1]), PipelineConfig()
        )
    )
    assert result[f"event_count_{window}"].item() == 2
    assert result[f"alarm_count_{window}"].item() == 2
    assert result[f"unique_channels_{window}"].item() == 2
    assert result[f"unique_sensor_types_{window}"].item() == 1


def test_grid_has_unique_object_times_and_configurable_step() -> None:
    source = pl.concat(
        [
            events([1, 19]),
            events([0, 20]).with_columns(pl.lit("other").alias("object_id")),
        ]
    )
    result = build_feature_snapshots(
        source, PipelineConfig(scoring_step_minutes=10)
    ).collect()
    assert result.select("object_id", "scoring_timestamp").rows() == [
        ("mine", START),
        ("mine", START + timedelta(minutes=10)),
        ("mine", START + timedelta(minutes=20)),
        ("other", START),
        ("other", START + timedelta(minutes=10)),
        ("other", START + timedelta(minutes=20)),
    ]
    assert result["event_count_5m"].to_list() == [0, 0, 1, 1, 0, 1]
    assert result.select("hour", "weekday", "month").row(0) == (0, 3, 1)


def test_missing_optional_signals_have_stable_typed_defaults() -> None:
    result = at_start(build_feature_snapshots(events([0]), PipelineConfig()))
    assert result["gas_max_5m"].item() is None
    assert result["temperature_mean_5m"].item() is None
    assert result.schema["gas_max_5m"] == pl.Float64
    assert result.schema["malfunction_count_5m"] == pl.Int64
    assert result["gas_alarm_count_5m"].item() == 0
    assert result["stuck_count_5m"].item() == 0
    assert result["smoke_heat_5m"].item() is False


def test_window_signals_and_malfunctions_ignore_unverified_technical_flags() -> None:
    source = events([-4, -3, -2, -1, 0]).with_columns(
        pl.Series(
            "sensor_type",
            ["Газовый датчик", "gas", "Датчик температуры", "smoke", "heat"],
        ),
        pl.Series("numeric_value", [0.5, 1.5, 20.0, None, 30.0]),
        pl.Series(
            "value_kind", ["numeric", "numeric", "numeric", "malfunction", "numeric"]
        ),
        pl.Series(
            "quality_flags", [[], ["burst"], ["stuck"], ["historical_artifact"], []]
        ),
    )
    result = at_start(build_feature_snapshots(source, PipelineConfig()))
    assert result.select("gas_max_5m", "gas_mean_5m", "gas_alarm_count_5m").row(0) == (
        1.5,
        1.0,
        1,
    )
    assert result.select("temperature_max_5m", "temperature_mean_5m").row(0) == (
        30.0,
        25.0,
    )
    assert result.select(
        "malfunction_count_5m",
        "stuck_count_5m",
        "burst_count_5m",
        "historical_artifact_count_5m",
    ).row(0) == (1, 0, 0, 0)
    assert result["smoke_heat_5m"].item() is True


def test_baseline_uses_completed_days_and_excludes_stuck_events() -> None:
    source = events([-2880, -2879, -1440, -1439, -1438, 0]).with_columns(
        pl.Series("stuck", [False, False, False, False, True, False])
    )
    result = at_start(build_feature_snapshots(source, PipelineConfig()))
    assert result["historical_daily_event_baseline"].item() == 2.0
    # The left boundary is excluded: two previous-day events + one current / 2.
    assert result["activity_ratio_24h"].item() == 1.5


def test_future_events_cannot_change_earlier_features_or_baseline() -> None:
    source = events([-1440, -1439, -4, 0])
    future = events([1, 2880]).with_columns(pl.lit("new-type").alias("sensor_type"))
    before = at_start(build_feature_snapshots(source, PipelineConfig()))
    after = at_start(
        build_feature_snapshots(pl.concat([source, future]), PipelineConfig())
    )
    assert_frame_equal(before, after)


def test_unknown_objects_and_empty_input_produce_no_training_rows() -> None:
    for source in [
        events([]),
        events([0]).with_columns(pl.lit(None, dtype=pl.String).alias("object_id")),
    ]:
        assert build_feature_snapshots(source, PipelineConfig()).collect().is_empty()


def test_nonpositive_step_is_rejected() -> None:
    with pytest.raises(ValueError, match="scoring_step_minutes"):
        build_feature_snapshots(events([0]), PipelineConfig(scoring_step_minutes=0))


def incidents() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "incident_id": ["fire-a"],
            "object_id": ["mine"],
            "started_at": [START],
            "ended_at": [START + timedelta(hours=1)],
        }
    ).lazy()


def test_horizon_boundaries_are_cumulative_and_now_is_half_open() -> None:
    snapshots = pl.DataFrame(
        {
            "object_id": ["mine"] * 8,
            "scoring_timestamp": [
                START + timedelta(minutes=m)
                for m in [-1441, -1440, -721, -720, -360, 0, 59, 60]
            ],
        }
    ).lazy()
    result = attach_horizon_targets(snapshots, incidents()).collect()
    assert result.select(
        "target_now", "target_6h", "target_12h", "target_24h"
    ).rows() == [
        (False, False, False, False),
        (False, False, False, True),
        (False, False, False, True),
        (False, False, True, True),
        (False, True, True, True),
        (True, False, False, False),
        (True, False, False, False),
        (False, False, False, False),
    ]
    assert result["episode_group_id"].to_list() == [
        None,
        "fire-a",
        "fire-a",
        "fire-a",
        "fire-a",
        "fire-a",
        "fire-a",
        None,
    ]


def test_targets_preserve_rows_with_no_incident_or_another_object() -> None:
    snapshots = pl.DataFrame(
        {"object_id": ["elsewhere"], "scoring_timestamp": [START]}
    ).lazy()
    for labels in [incidents(), incidents().filter(pl.lit(False))]:
        result = attach_horizon_targets(snapshots, labels).collect()
        assert result.height == 1
        assert result["target_now"].item() is False
        assert result["episode_group_id"].item() is None


def test_overlapping_incidents_select_active_group_before_future_group() -> None:
    labels = pl.concat(
        [
            incidents(),
            incidents().with_columns(
                pl.lit("fire-b").alias("incident_id"),
                pl.lit(START + timedelta(minutes=5)).alias("started_at"),
                pl.lit(START + timedelta(minutes=10)).alias("ended_at"),
            ),
        ]
    )
    snapshots = pl.DataFrame(
        {
            "object_id": ["mine"] * 2,
            "scoring_timestamp": [START, START + timedelta(minutes=15)],
        }
    ).lazy()
    result = attach_horizon_targets(snapshots, labels).collect()
    assert result["target_now"].to_list() == [True, True]
    assert result["episode_group_id"].to_list() == ["fire-a", "fire-a"]


def test_future_incident_changes_target_without_changing_past_features() -> None:
    initial = events([-5, 0])
    later = pl.concat(
        [initial, events([60]).with_columns(pl.lit("heat").alias("sensor_type"))]
    )
    past = build_feature_snapshots(initial, PipelineConfig()).filter(
        pl.col("scoring_timestamp") == START
    )
    updated = build_feature_snapshots(later, PipelineConfig()).filter(
        pl.col("scoring_timestamp") == START
    )
    labels = incidents().with_columns(
        pl.lit(START + timedelta(hours=1)).alias("started_at")
    )
    before = attach_horizon_targets(past, labels.filter(pl.lit(False))).collect()
    after = attach_horizon_targets(updated, labels).collect()
    assert before["target_6h"].item() is False
    assert after["target_6h"].item() is True
    assert_frame_equal(
        before.select(past.collect_schema().names()),
        after.select(past.collect_schema().names()),
    )


def test_negative_decisions_are_not_fire_targets_but_proxy_unknown_is() -> None:
    snapshots = pl.DataFrame(
        {"object_id": ["mine"], "scoring_timestamp": [START]}
    ).lazy()
    for decision in [
        "false_alarm",
        "maintenance",
        "sensor_malfunction",
        "smoke_without_fire",
        "unknown",
    ]:
        result = attach_horizon_targets(
            snapshots,
            incidents().with_columns(
                pl.lit(decision).alias("decision"), pl.lit("dispatcher").alias("source")
            ),
        ).collect()
        assert result["target_now"].item() is False
    proxy = incidents().with_columns(
        pl.lit("unknown").alias("decision"), pl.lit("proxy").alias("source")
    )
    assert (
        attach_horizon_targets(snapshots, proxy).collect()["target_now"].item() is True
    )


def test_completed_day_baseline_excludes_entire_known_stuck_interval() -> None:
    source = events([-2880, -2879] + [-1440] * 101 + [0]).with_columns(
        pl.Series("event_id", [str(i) for i in range(104)]),
        pl.lit("channel").alias("channel_id"),
        pl.lit("unchanged").alias("raw_value"),
    )
    thresholds = QualityThresholds()
    marked = mark_historical_artifacts(source, profile_channel_days(source), thresholds)
    causal = causal_quality_flags(marked, thresholds)
    result = at_start(build_feature_snapshots(causal, PipelineConfig()))
    assert result["historical_daily_event_baseline"].item() == 2.0


def test_connected_forecast_contexts_share_one_group_across_active_and_future_rows() -> (
    None
):
    labels = pl.DataFrame(
        {
            "incident_id": ["fire-a", "fire-b", "fire-c"],
            "object_id": ["mine"] * 3,
            "started_at": [
                START,
                START + timedelta(hours=1),
                START + timedelta(hours=48),
            ],
            "ended_at": [
                START + timedelta(minutes=5),
                START + timedelta(minutes=65),
                START + timedelta(hours=48, minutes=5),
            ],
        }
    ).lazy()
    snapshots = pl.DataFrame(
        {
            "object_id": ["mine"] * 5,
            "scoring_timestamp": [
                START + timedelta(minutes=m) for m in [0, 15, 30, 60, 48 * 60]
            ],
        }
    ).lazy()
    result = attach_horizon_targets(snapshots, labels).collect()
    assert result["target_6h"].to_list() == [True, True, True, False, False]
    assert result["target_now"].to_list() == [True, False, False, True, True]
    assert result["episode_group_id"].to_list() == [
        "fire-a",
        "fire-a",
        "fire-a",
        "fire-a",
        "fire-c",
    ]


def test_context_components_are_transitive_and_stable_under_incident_reordering() -> (
    None
):
    labels = pl.DataFrame(
        {
            "incident_id": ["fire-a", "fire-b", "fire-c", "other-fire"],
            "object_id": ["mine", "mine", "mine", "other"],
            "started_at": [
                START,
                START + timedelta(hours=23),
                START + timedelta(hours=46),
                START,
            ],
            "ended_at": [
                START + timedelta(minutes=5),
                START + timedelta(hours=23, minutes=5),
                START + timedelta(hours=46, minutes=5),
                START + timedelta(minutes=5),
            ],
        }
    ).lazy()
    snapshots = labels.select(
        "object_id", pl.col("started_at").alias("scoring_timestamp")
    )
    expected_groups = ["fire-a", "fire-a", "fire-a", "other-fire"]
    forward = attach_horizon_targets(snapshots, labels).collect()
    reversed_order = attach_horizon_targets(snapshots, labels.reverse()).collect()
    assert forward["episode_group_id"].to_list() == expected_groups
    assert_frame_equal(forward, reversed_order)


def test_public_builder_recomputes_retrospective_flags_without_future_leakage() -> None:
    def marked(minutes: list[int]) -> pl.LazyFrame:
        source = events(minutes).with_columns(
            pl.Series("event_id", [str(i) for i in range(len(minutes))]),
            pl.lit("channel").alias("channel_id"),
            pl.lit("unchanged").alias("raw_value"),
        )
        return mark_historical_artifacts(
            source, profile_channel_days(source), QualityThresholds()
        )

    before = at_start(build_feature_snapshots(marked([0]), PipelineConfig()))
    appended = build_feature_snapshots(marked([0] + [1] * 100), PipelineConfig())
    assert_frame_equal(before, at_start(appended))
    last = appended.collect().tail(1)
    assert last["stuck_count_24h"].item() == 2
    assert last["burst_count_24h"].item() == 2


def test_builder_does_not_trust_retrospective_flags_without_raw_signal_history() -> (
    None
):
    before = at_start(build_feature_snapshots(events([0]), PipelineConfig()))
    flagged = events([0, 1]).with_columns(
        pl.lit(["stuck", "burst", "historical_artifact"]).alias("quality_flags"),
        pl.lit(True).alias("stuck"),
        pl.lit(True).alias("burst"),
        pl.lit(True).alias("historical_artifact"),
    )
    assert_frame_equal(
        before, at_start(build_feature_snapshots(flagged, PipelineConfig()))
    )


def test_ongoing_incidents_connect_later_contexts_even_when_end_column_is_all_null() -> (
    None
):
    labels = pl.DataFrame(
        {
            "incident_id": ["ongoing-a", "later-b"],
            "object_id": ["mine", "mine"],
            "started_at": [START, START + timedelta(days=3)],
            "ended_at": [None, None],
        }
    ).lazy()
    snapshots = labels.select(
        "object_id", pl.col("started_at").alias("scoring_timestamp")
    )
    result = attach_horizon_targets(snapshots, labels).collect()
    assert result["target_now"].to_list() == [True, True]
    assert result["episode_group_id"].to_list() == ["ongoing-a", "ongoing-a"]
