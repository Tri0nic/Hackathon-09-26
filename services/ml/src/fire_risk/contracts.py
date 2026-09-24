"""Canonical records shared by data preparation and model training."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ValueKind(StrEnum):
    NUMERIC = "numeric"
    KNOWN_STATE = "known_state"
    MALFUNCTION = "malfunction"
    UNKNOWN = "unknown"


class SensorEventRaw(BaseModel):
    event_id: str
    channel_id: str
    registered_at: datetime
    alarm_flag: bool
    raw_value: str
    source_year: int


class ChannelReference(BaseModel):
    channel_id: str
    engineering_system_type: str
    sensor_type: str
    sensor_name: str
    object_id: str
    object_level: int
    object_name: str
    level2_object_id: str
    level2_object_name: str
    level1_object_id: str
    level1_object_name: str


class StateReference(BaseModel):
    sensor_type: str
    state_set_id: str
    state_name: str
    alarm_flag: bool


class SensorEventNormalized(BaseModel):
    event_id: str
    channel_id: str
    object_id: str | None
    registered_at: datetime
    sensor_type: str | None
    sensor_name: str | None
    alarm_flag: bool
    value_kind: ValueKind
    numeric_value: float | None = None
    state_code: str | None = None
    raw_value: str
    picket_raw: str | None = None
    picket_sort_key: float | None = None
    quality_flags: list[str] = Field(default_factory=list)


class IncidentEpisode(BaseModel):
    episode_id: str
    object_id: str
    started_at: datetime
    ended_at: datetime
    severity: str
    channel_ids: list[str]
    sensor_types: list[str]
    alarming_channel_ids: list[str] = Field(default_factory=list)
    alarming_sensor_types: list[str] = Field(default_factory=list)
    picket_from: float | None = None
    picket_to: float | None = None
    quality_flags: list[str] = Field(default_factory=list)


class IncidentDecision(StrEnum):
    CONFIRMED_FIRE = "confirmed_fire"
    SMOKE_WITHOUT_FIRE = "smoke_without_fire"
    FALSE_ALARM = "false_alarm"
    MAINTENANCE = "maintenance"
    SENSOR_MALFUNCTION = "sensor_malfunction"
    UNKNOWN = "unknown"


class LabelSource(StrEnum):
    PROXY = "proxy"
    SYNTHETIC = "synthetic"
    DISPATCHER = "dispatcher"
    IMPORTED = "imported"


class IncidentLabel(BaseModel):
    incident_id: str
    object_id: str
    started_at: datetime
    ended_at: datetime | None = None
    incident_type: str
    decision: IncidentDecision
    confirmed_at: datetime | None = None
    source: LabelSource
    confidence: float = Field(ge=0.0, le=1.0)
    rule_version: str | None = None


class PipelineConfig(BaseModel):
    scoring_step_minutes: int = 15
    episode_gap_minutes: int = 30
    methane_alarm_percent: float = 1.0
    sensor_sentinels: dict[str, set[str]] = Field(
        default_factory=lambda: {"Датчик температуры": {"-100"}}
    )
