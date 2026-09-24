import pytest

from fire_risk.config import PipelineConfig
from fire_risk.contracts import StateReference, ValueKind
from fire_risk.data.normalize import StateIndex, normalize_value


@pytest.mark.parametrize(
    ("sensor_type", "raw", "kind", "numeric", "flags"),
    [
        ("Газовый датчик", "0.75", ValueKind.NUMERIC, 0.75, []),
        ("Газовый датчик", "1.20", ValueKind.NUMERIC, 1.20, ["methane_alarm"]),
        (
            "Состояние охраны",
            "01.01.1970 03:00:00",
            ValueKind.MALFUNCTION,
            None,
            ["invalid_epoch_date"],
        ),
        ("Датчик температуры", "-100", ValueKind.MALFUNCTION, None, ["sentinel_value"]),
        (
            "Датчик дыма",
            "неизвестный текст",
            ValueKind.UNKNOWN,
            None,
            ["unmapped_state"],
        ),
    ],
)
def test_normalize_value(
    sensor_type: str,
    raw: str,
    kind: ValueKind,
    numeric: float | None,
    flags: list[str],
) -> None:
    value = normalize_value(sensor_type, raw, StateIndex({}), PipelineConfig())

    assert value.kind == kind
    assert value.numeric_value == numeric
    assert value.quality_flags == flags
    assert value.raw_value == raw


def test_configured_sentinel_is_scoped_to_sensor_type() -> None:
    config = PipelineConfig(sensor_sentinels={"Газовый датчик": {"-100"}})

    sentinel = normalize_value("Газовый датчик", "-100", StateIndex({}), config)
    other_type = normalize_value("Датчик температуры", "-100", StateIndex({}), config)

    assert sentinel.kind == ValueKind.MALFUNCTION
    assert sentinel.quality_flags == ["sentinel_value"]
    assert other_type.kind == ValueKind.NUMERIC
    assert other_type.numeric_value == -100.0


def test_invalid_epoch_date_precedes_matching_state() -> None:
    raw = "01.01.1970 03:00:00"
    states = StateIndex({("Состояние охраны", raw): {True}})

    value = normalize_value("Состояние охраны", raw, states, PipelineConfig())

    assert value.kind == ValueKind.MALFUNCTION
    assert value.quality_flags == ["invalid_epoch_date"]


def test_numeric_value_precedes_matching_state_and_alarm_is_inclusive() -> None:
    states = StateIndex({("Газовый датчик", "1.00"): {False}})

    value = normalize_value("Газовый датчик", "1.00", states, PipelineConfig())

    assert value.kind == ValueKind.NUMERIC
    assert value.numeric_value == 1.0
    assert value.quality_flags == ["methane_alarm"]


def test_exact_state_lookup_preserves_reference_code() -> None:
    reference = StateReference(
        sensor_type="Датчик дыма",
        state_set_id="smoke-states",
        state_name="Норма",
        alarm_flag=False,
    )
    states = StateIndex({("Датчик дыма", "Норма"): [reference]})

    value = normalize_value("Датчик дыма", "Норма", states, PipelineConfig())
    other_type = normalize_value("Газовый датчик", "Норма", states, PipelineConfig())

    assert value.kind == ValueKind.KNOWN_STATE
    assert value.state_code == "smoke-states"
    assert value.alarm_flag is False
    assert value.raw_value == "Норма"
    assert other_type.kind == ValueKind.UNKNOWN
    assert other_type.quality_flags == ["unmapped_state"]


def test_conflicting_state_mapping_is_unknown() -> None:
    index = StateIndex({("Газовый датчик", "Температура ниже 3ºC1"): {True, False}})

    value = normalize_value(
        "Газовый датчик", "Температура ниже 3ºC1", index, PipelineConfig()
    )

    assert value.kind == ValueKind.UNKNOWN
    assert value.quality_flags == ["conflicting_state_mapping"]
