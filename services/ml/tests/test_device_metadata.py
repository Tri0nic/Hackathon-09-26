from datetime import date

import pytest

from fire_risk.contracts import ChannelReference
from fire_risk.data.device_metadata import DeviceAgeConfig, estimate_device_metadata


def channel_fixture(
    channel_id: str = "channel-1", sensor_type: str = "Датчик дыма"
) -> ChannelReference:
    return ChannelReference(
        channel_id=channel_id,
        engineering_system_type="fire",
        sensor_type=sensor_type,
        sensor_name="Дым ПК3",
        object_id="object-1",
        object_level=3,
        object_name="Шахта",
        level2_object_id="level-2",
        level2_object_name="Участок",
        level1_object_id="level-1",
        level1_object_name="Предприятие",
    )


def test_generated_age_is_stable_for_channel_and_seed() -> None:
    first = estimate_device_metadata(channel_fixture(), date(2019, 1, 1), seed=42)
    second = estimate_device_metadata(channel_fixture(), date(2019, 1, 1), seed=42)
    assert first == second
    assert first.channel_id == "channel-1"
    assert first.estimated_install_date < date(2019, 1, 1)
    assert first.age_source == "generated_demo"
    assert first.is_synthetic is True


def test_first_seen_after_cutoff_is_preserved_as_source_estimate() -> None:
    config = DeviceAgeConfig(as_of=date(2025, 1, 1))
    result = estimate_device_metadata(
        channel_fixture(), date(2020, 1, 1), seed=42, config=config
    )
    assert result.estimated_install_date == date(2020, 1, 1)
    assert result.estimated_age_years == 5.0
    assert result.age_source == "first_seen"
    assert result.is_synthetic is False


def test_cutoff_day_uses_synthetic_prehistory_from_sensor_range() -> None:
    config = DeviceAgeConfig(
        left_censoring_cutoff=date(2019, 1, 1),
        as_of=date(2026, 1, 1),
        age_ranges_years={"Датчик дыма": (2, 3), "Газовый датчик": (8, 9)},
    )
    smoke = estimate_device_metadata(
        channel_fixture(), date(2019, 1, 1), seed=42, config=config
    )
    gas = estimate_device_metadata(
        channel_fixture(sensor_type="Газовый датчик"),
        date(2019, 1, 1),
        seed=42,
        config=config,
    )
    assert 2 <= (config.left_censoring_cutoff - smoke.estimated_install_date).days / 365.25 <= 3
    assert 8 <= (config.left_censoring_cutoff - gas.estimated_install_date).days / 365.25 <= 9
    assert smoke.estimated_age_years > 0


def test_channel_identity_changes_demo_draw() -> None:
    config = DeviceAgeConfig(age_ranges_years={"Датчик дыма": (1, 20)})
    first = estimate_device_metadata(
        channel_fixture("channel-1"), date(2019, 1, 1), seed=42, config=config
    )
    second = estimate_device_metadata(
        channel_fixture("channel-2"), date(2019, 1, 1), seed=42, config=config
    )
    assert first.estimated_install_date != second.estimated_install_date


def test_future_first_seen_is_rejected() -> None:
    with pytest.raises(ValueError, match="as_of"):
        estimate_device_metadata(
            channel_fixture(), date(2027, 1, 1), seed=42
        )
