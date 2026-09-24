from datetime import datetime, timezone

import pytest
from fire_risk.config import PipelineConfig
from fire_risk.contracts import (
    ChannelReference,
    IncidentDecision,
    IncidentEpisode,
    IncidentLabel,
    LabelSource,
    SensorEventNormalized,
    SensorEventRaw,
    StateReference,
    ValueKind,
)
from pydantic import ValidationError

WHEN = datetime(2026, 8, 1, 3, 9, 27, tzinfo=timezone.utc)


def test_raw_event_preserves_source_value_and_channel_identity() -> None:
    event = SensorEventRaw(
        event_id="1",
        channel_id="120578",
        registered_at=WHEN,
        alarm_flag=True,
        raw_value="01.01.1970 03:00:00",
        source_year=2026,
    )

    assert event.raw_value == "01.01.1970 03:00:00"
    assert event.channel_id == "120578"
    assert ValueKind.MALFUNCTION.value == "malfunction"


def test_channel_reference_accepts_every_source_field() -> None:
    channel = ChannelReference(
        channel_id="120578",
        engineering_system_type="fire protection",
        sensor_type="smoke",
        sensor_name="Smoke 1",
        object_id="object-1",
        object_level=2,
        object_name="East tunnel",
        level2_object_id="section-1",
        level2_object_name="Section 1",
        level1_object_id="line-1",
        level1_object_name="Line 1",
    )

    assert channel.model_dump() == {
        "channel_id": "120578",
        "engineering_system_type": "fire protection",
        "sensor_type": "smoke",
        "sensor_name": "Smoke 1",
        "object_id": "object-1",
        "object_level": 2,
        "object_name": "East tunnel",
        "level2_object_id": "section-1",
        "level2_object_name": "Section 1",
        "level1_object_id": "line-1",
        "level1_object_name": "Line 1",
    }


def test_state_reference_preserves_alarm_flag() -> None:
    state = StateReference(
        sensor_type="smoke",
        state_set_id="set-1",
        state_name="Alarm",
        alarm_flag=True,
    )

    assert state.model_dump() == {
        "sensor_type": "smoke",
        "state_set_id": "set-1",
        "state_name": "Alarm",
        "alarm_flag": True,
    }


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_incident_label_rejects_confidence_outside_unit_interval(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        IncidentLabel(
            incident_id="incident-1",
            object_id="object-1",
            started_at=WHEN,
            incident_type="fire pattern",
            decision=IncidentDecision.UNKNOWN,
            source=LabelSource.PROXY,
            confidence=confidence,
        )


def test_quality_flag_defaults_are_independent() -> None:
    normalized_payload = {
        "event_id": "1",
        "channel_id": "120578",
        "object_id": None,
        "registered_at": WHEN,
        "sensor_type": None,
        "sensor_name": None,
        "alarm_flag": False,
        "value_kind": ValueKind.UNKNOWN,
        "raw_value": "unexpected text",
    }
    first_event = SensorEventNormalized(**normalized_payload)
    second_event = SensorEventNormalized(**normalized_payload)
    first_event.quality_flags.append("unknown_channel")

    first_episode = IncidentEpisode(
        episode_id="episode-1",
        object_id="object-1",
        started_at=WHEN,
        ended_at=WHEN,
        severity="unknown",
        channel_ids=["120578"],
        sensor_types=["smoke"],
    )
    second_episode = IncidentEpisode(
        episode_id="episode-2",
        object_id="object-1",
        started_at=WHEN,
        ended_at=WHEN,
        severity="unknown",
        channel_ids=["120579"],
        sensor_types=["heat"],
    )
    first_episode.quality_flags.append("burst")

    assert second_event.quality_flags == []
    assert second_episode.quality_flags == []


def test_incident_decisions_match_label_contract() -> None:
    assert {decision.value for decision in IncidentDecision} == {
        "confirmed_fire",
        "smoke_without_fire",
        "false_alarm",
        "maintenance",
        "sensor_malfunction",
        "unknown",
    }


def test_pipeline_config_has_initial_scoring_and_alarm_thresholds() -> None:
    config = PipelineConfig()

    assert config.scoring_step_minutes == 15
    assert config.episode_gap_minutes == 30
    assert config.methane_alarm_percent == 1.0
