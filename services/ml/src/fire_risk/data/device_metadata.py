"""Reproducible demonstration age estimates for sensor channels."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
from math import ceil, floor
from typing import Literal

from fire_risk.contracts import ChannelReference


@dataclass(frozen=True)
class DeviceAgeConfig:
    """Explicit observation boundary, reporting date, and demo prehistory ranges."""

    left_censoring_cutoff: date = date(2019, 1, 1)
    as_of: date = date(2026, 9, 24)
    age_ranges_years: dict[str, tuple[int, int]] = field(
        default_factory=lambda: {
            "Датчик дыма": (2, 12),
            "Датчик температуры": (2, 15),
            "Газовый датчик": (1, 10),
        }
    )
    default_age_range_years: tuple[int, int] = (1, 12)


@dataclass(frozen=True)
class DeviceMetadata:
    channel_id: str
    estimated_install_date: date
    estimated_age_years: float
    age_source: Literal["first_seen", "generated_demo"]
    is_synthetic: bool


def estimate_device_metadata(
    channel: ChannelReference,
    first_seen: date,
    seed: int,
    config: DeviceAgeConfig | None = None,
) -> DeviceMetadata:
    """Estimate channel age; first-seen is a proxy, earlier dates are demo data."""
    settings = config or DeviceAgeConfig()
    if settings.as_of < settings.left_censoring_cutoff:
        raise ValueError("as_of must be on or after left_censoring_cutoff")
    if first_seen > settings.as_of:
        raise ValueError("first_seen must be on or before as_of")

    if first_seen > settings.left_censoring_cutoff:
        install_date = first_seen
        source: Literal["first_seen", "generated_demo"] = "first_seen"
    else:
        years = settings.age_ranges_years.get(
            channel.sensor_type, settings.default_age_range_years
        )
        if years[0] <= 0 or years[0] > years[1]:
            raise ValueError("age range must have positive, ascending year bounds")
        minimum_days = ceil(years[0] * 365.25)
        maximum_days = floor(years[1] * 365.25)
        digest = sha256(f"{seed}\0{channel.channel_id}".encode()).digest()
        days = minimum_days + int.from_bytes(digest, "big") % (
            maximum_days - minimum_days + 1
        )
        install_date = settings.left_censoring_cutoff - timedelta(days=days)
        source = "generated_demo"

    return DeviceMetadata(
        channel_id=channel.channel_id,
        estimated_install_date=install_date,
        estimated_age_years=round((settings.as_of - install_date).days / 365.25, 1),
        age_source=source,
        is_synthetic=source == "generated_demo",
    )
