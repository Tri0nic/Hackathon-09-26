"""Replaceable sources for incident labels."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from fire_risk.contracts import (
    IncidentDecision,
    IncidentEpisode,
    IncidentLabel,
    LabelSource,
)

_SENSOR_CATEGORY = {
    "smoke": "smoke",
    "датчик дыма": "smoke",
    "heat": "heat",
    "датчик температуры": "heat",
    "manual_call_point": "manual_call_point",
    "ручной извещатель": "manual_call_point",
    "uir-r": "uir-r",
    "уир-р": "uir-r",
    "gas": "gas",
    "газовый датчик": "gas",
    "pump": "pump",
    "насос": "pump",
}


class LabelProvider(Protocol):
    """Return labels whose start is in the requested interval and object set."""

    def get_incidents(
        self, start: datetime, end: datetime, object_ids: set[str]
    ) -> list[IncidentLabel]: ...


class LabelImportError(ValueError):
    """A decision journal row cannot be converted to an incident label."""


@dataclass(frozen=True)
class ProxyLabelConfig:
    episodes: Sequence[IncidentEpisode]
    rule_version: str = "smvu-proxy-v1"
    confidence: float = 0.5


class ProxyLabelProvider:
    def __init__(self, config: ProxyLabelConfig) -> None:
        self._config = config

    def get_incidents(
        self, start: datetime, end: datetime, object_ids: set[str]
    ) -> list[IncidentLabel]:
        _validate_period(start, end)
        return [
            IncidentLabel(
                incident_id=episode.episode_id,
                object_id=episode.object_id,
                started_at=episode.started_at,
                ended_at=episode.ended_at,
                incident_type="SMVU fire pattern",
                decision=IncidentDecision.UNKNOWN,
                source=LabelSource.PROXY,
                confidence=self._config.confidence,
                rule_version=self._config.rule_version,
            )
            for episode in self._config.episodes
            if episode.object_id in object_ids
            and start <= episode.started_at < end
            and "historical_artifact" not in episode.quality_flags
            and _is_fire_pattern(episode)
        ]


class DecisionJournalLabelProvider:
    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self._labels = [
            self._parse_row(index, row) for index, row in enumerate(rows, 1)
        ]

    @staticmethod
    def _parse_row(index: int, row: Mapping[str, object]) -> IncidentLabel:
        object_id = row.get("object_id")
        if not isinstance(object_id, str) or not object_id.strip():
            raise LabelImportError(f"row {index}: object_id is required")
        raw_start = row.get("started_at")
        if raw_start is None or raw_start == "":
            raise LabelImportError(f"row {index}: started_at is required")
        try:
            started_at = TypeAdapter(datetime).validate_python(raw_start)
            if started_at.tzinfo is None or started_at.utcoffset() is None:
                raise ValueError("timezone is required")
        except (ValidationError, ValueError) as exc:
            raise LabelImportError(f"row {index}: invalid started_at: {exc}") from exc
        raw_decision = row.get("decision")
        try:
            decision = IncidentDecision(str(raw_decision))
        except ValueError:
            decision = IncidentDecision.UNKNOWN
        try:
            return IncidentLabel.model_validate(
                {
                    "incident_id": row.get("incident_id") or f"journal:{index}",
                    "object_id": object_id,
                    "started_at": started_at,
                    "ended_at": row.get("ended_at"),
                    "incident_type": row.get("incident_type") or "decision journal",
                    "decision": decision,
                    "confirmed_at": row.get("confirmed_at"),
                    "source": row.get("source") or LabelSource.DISPATCHER,
                    "confidence": row.get("confidence", 1.0),
                }
            )
        except ValidationError as exc:
            raise LabelImportError(
                f"row {index}: invalid incident label: {exc}"
            ) from exc

    def get_incidents(
        self, start: datetime, end: datetime, object_ids: set[str]
    ) -> list[IncidentLabel]:
        _validate_period(start, end)
        return [
            label
            for label in self._labels
            if label.object_id in object_ids and start <= label.started_at < end
        ]


def _validate_period(start: datetime, end: datetime) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (start, end)):
        raise ValueError("start and end must be timezone-aware")
    if end < start:
        raise ValueError("end must not precede start")


def _is_fire_pattern(episode: IncidentEpisode) -> bool:
    if episode.severity != "alarm":
        return False
    types = {
        _SENSOR_CATEGORY.get(sensor_type.strip().casefold(), "other")
        for sensor_type in episode.sensor_types
    }
    if "smoke" not in types:
        return False
    if types.intersection({"heat", "manual_call_point", "uir-r"}):
        return True
    return "gas" in types and ("pump" in types or len(set(episode.channel_ids)) >= 3)
