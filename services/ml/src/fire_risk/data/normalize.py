"""Apply ordered, source-preserving rules to a single sensor value."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from math import isfinite

from fire_risk.contracts import PipelineConfig, StateReference, ValueKind

type StateEntry = bool | StateReference

_INVALID_EPOCH_DATE = "01.01.1970 03:00:00"
_GAS_SENSOR_TYPE = "Газовый датчик"


class StateIndex:
    """Exact sensor-type/value lookup retaining distinct reference variants."""

    def __init__(
        self,
        entries: Mapping[tuple[str, str], Collection[StateEntry]],
    ) -> None:
        self._entries = {
            key: frozenset(
                (entry.state_set_id, entry.alarm_flag)
                if isinstance(entry, StateReference)
                else (None, entry)
                for entry in variants
            )
            for key, variants in entries.items()
        }

    def variants(
        self, sensor_type: str, raw_value: str
    ) -> frozenset[tuple[str | None, bool]]:
        return self._entries.get((sensor_type, raw_value), frozenset())


@dataclass(frozen=True)
class NormalizedValue:
    kind: ValueKind
    raw_value: str
    numeric_value: float | None = None
    state_code: str | None = None
    alarm_flag: bool | None = None
    rule_code: str = ""
    quality_flags: list[str] = field(default_factory=list)


def normalize_value(
    sensor_type: str,
    raw_value: str,
    states: StateIndex,
    config: PipelineConfig,
) -> NormalizedValue:
    """Classify one raw value without rewriting its source text."""
    if raw_value == _INVALID_EPOCH_DATE:
        return NormalizedValue(
            kind=ValueKind.MALFUNCTION,
            raw_value=raw_value,
            rule_code="invalid_epoch_date",
            quality_flags=["invalid_epoch_date"],
        )

    if raw_value in config.sensor_sentinels.get(sensor_type, set()):
        return NormalizedValue(
            kind=ValueKind.MALFUNCTION,
            raw_value=raw_value,
            rule_code="sentinel_value",
            quality_flags=["sentinel_value"],
        )

    try:
        numeric = float(raw_value)
    except ValueError:
        numeric = None
    if numeric is not None and isfinite(numeric):
        flags = (
            ["methane_alarm"]
            if sensor_type == _GAS_SENSOR_TYPE
            and numeric >= config.methane_alarm_percent
            else []
        )
        return NormalizedValue(
            kind=ValueKind.NUMERIC,
            raw_value=raw_value,
            numeric_value=numeric,
            rule_code="numeric",
            quality_flags=flags,
        )

    variants = states.variants(sensor_type, raw_value)
    if len({alarm_flag for _, alarm_flag in variants}) > 1:
        return NormalizedValue(
            kind=ValueKind.UNKNOWN,
            raw_value=raw_value,
            rule_code="conflicting_state_mapping",
            quality_flags=["conflicting_state_mapping"],
        )
    if variants:
        state_code, alarm_flag = min(variants, key=lambda item: item[0] or "")
        return NormalizedValue(
            kind=ValueKind.KNOWN_STATE,
            raw_value=raw_value,
            state_code=state_code,
            alarm_flag=alarm_flag,
            rule_code="state_mapping",
        )
    return NormalizedValue(
        kind=ValueKind.UNKNOWN,
        raw_value=raw_value,
        rule_code="unmapped_state",
        quality_flags=["unmapped_state"],
    )
