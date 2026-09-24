"""Join reference metadata and report coverage of observed event values."""

import csv
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import polars as pl

from fire_risk.contracts import StateMapping, StateReference
from fire_risk.data.normalize import StateIndex


class ReferenceIntegrityError(ValueError):
    """A reference table cannot be joined without ambiguous results."""


_CHANNEL_FIELDS = (
    "channel_id",
    "engineering_system_type",
    "sensor_type",
    "sensor_name",
    "object_id",
    "object_level",
    "object_name",
    "level2_object_id",
    "level2_object_name",
    "level1_object_id",
    "level1_object_name",
)

CHANNEL_RU_TO_CANONICAL: Mapping[str, str] = MappingProxyType(
    {
        "ид_канала_данных": "channel_id",
        "тип_инж_системы": "engineering_system_type",
        "тип_датчика": "sensor_type",
        "название_датчика": "sensor_name",
        "ид_объект": "object_id",
        "иерархия_уровень": "object_level",
        "диспетчерское_название_объекта": "object_name",
        "объект_ур2": "level2_object_id",
        "объект_ур2_имя": "level2_object_name",
        "объект_ур1": "level1_object_id",
        "объект_ур1_имя": "level1_object_name",
    }
)
_CHANNEL_RU_METADATA = frozenset({"родитель", "Имя"})
STATE_RU_TO_CANONICAL: Mapping[str, str] = MappingProxyType(
    {
        "тип_датчика": "sensor_type",
        "ид_набор_состояний": "state_set_id",
        "название_состояния": "state_name",
        "тревожное": "alarm_flag",
    }
)


def _reference_columns(
    path: Path, russian: Mapping[str, str], metadata: frozenset[str] = frozenset()
) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        headers = next(csv.reader(source), [])
    canonical = set(russian.values())
    source_names = set(russian) | metadata
    actual = set(headers)
    expected = source_names if actual & set(russian) else canonical
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    duplicates = sorted({name for name in headers if headers.count(name) > 1})
    if missing or unexpected or duplicates:
        raise ReferenceIntegrityError(
            f"Invalid reference schema for {path}: missing={missing}; "
            f"unexpected={unexpected}; duplicate={duplicates}"
        )
    return dict(russian) if expected == source_names else {name: name for name in canonical}


def scan_channel_reference(path: Path) -> pl.LazyFrame:
    """Read either complete channel-reference schema as canonical fields."""
    columns = _reference_columns(path, CHANNEL_RU_TO_CANONICAL, _CHANNEL_RU_METADATA)
    return (
        pl.scan_csv(path, infer_schema=False)
        .select([pl.col(source).alias(target) for source, target in columns.items()])
        .select(_CHANNEL_FIELDS)
        .with_columns(
            pl.col("channel_id").cast(pl.String),
            pl.col("object_id").cast(pl.String),
            pl.col("level2_object_id").cast(pl.String),
            pl.col("level1_object_id").cast(pl.String),
            pl.col("object_level").cast(pl.Int64),
        )
    )


def scan_state_reference(path: Path) -> pl.LazyFrame:
    """Read, normalize, and consolidate state-reference mappings."""
    columns = _reference_columns(path, STATE_RU_TO_CANONICAL)
    alarm_tokens = {"true": True, "t": True, "1": True, "false": False, "f": False, "0": False}
    reference = pl.scan_csv(path, infer_schema=False).select(
        [pl.col(source).alias(target) for source, target in columns.items()]
    )
    invalid_alarm_values = (
        reference.select("alarm_flag")
        .filter(
            pl.col("alarm_flag").is_null()
            | ~pl.col("alarm_flag").str.to_lowercase().is_in(list(alarm_tokens))
        )
        .unique()
        .collect()["alarm_flag"]
        .to_list()
    )
    if invalid_alarm_values:
        raise ReferenceIntegrityError(
            f"Invalid alarm_flag values in {path}: {invalid_alarm_values}; "
            "expected true/t/1 or false/f/0"
        )
    return (
        reference
        .with_columns(
            pl.col("state_set_id").cast(pl.String),
            pl.col("alarm_flag")
            .str.to_lowercase()
            .replace_strict(alarm_tokens, return_dtype=pl.Boolean),
        )
        .unique()
        .group_by("sensor_type", "state_name")
        .agg(
            pl.col("state_set_id").unique().sort().alias("state_set_ids"),
            pl.col("alarm_flag").first().alias("alarm_flag"),
            pl.col("alarm_flag").n_unique().alias("_alarm_variants"),
        )
        .with_columns(
            (pl.col("_alarm_variants") > 1).alias("is_conflicting"),
            pl.when(pl.col("_alarm_variants") == 1)
            .then(pl.col("alarm_flag"))
            .otherwise(None)
            .alias("alarm_flag"),
        )
        .drop("_alarm_variants")
    )


def load_state_index(path: Path) -> StateIndex:
    """Build exact type/value lookups from consolidated state mappings."""
    entries: dict[tuple[str, str], list[bool | StateReference]] = {}
    for row in scan_state_reference(path).collect().iter_rows(named=True):
        mapping = StateMapping.model_validate(row)
        key = (mapping.sensor_type, mapping.state_name)
        if mapping.is_conflicting:
            entries[key] = [True, False]
        else:
            assert mapping.alarm_flag is not None
            entries[key] = [
                StateReference(
                    sensor_type=mapping.sensor_type,
                    state_set_id=state_set_id,
                    state_name=mapping.state_name,
                    alarm_flag=mapping.alarm_flag,
                )
                for state_set_id in mapping.state_set_ids
            ]
    return StateIndex(entries)


@dataclass(frozen=True)
class CoverageReport:
    total_events: int
    unknown_channel_events: int
    unmapped_type_value_pairs: dict[tuple[str, str | None], int]
    conflicting_type_value_pairs: dict[tuple[str, str | None], int] = field(
        default_factory=dict
    )


def join_channels(events: pl.LazyFrame, channels: Path) -> pl.LazyFrame:
    """Keep every event while adding the exact channel-reference fields."""
    reference = scan_channel_reference(channels)
    duplicates = (
        reference.group_by("channel_id")
        .len()
        .filter(pl.col("len") > 1)
        .select("channel_id")
        .collect()
    )
    if not duplicates.is_empty():
        raise ReferenceIntegrityError(
            f"Duplicate channel_id values: {duplicates['channel_id'].to_list()}"
        )

    if "quality_flags" not in events.collect_schema().names():
        events = events.with_columns(
            pl.lit([], dtype=pl.List(pl.String)).alias("quality_flags")
        )
    return events.join(reference, on="channel_id", how="left").with_columns(
        pl.when(pl.col("object_id").is_null())
        .then(pl.concat_list("quality_flags", pl.lit(["unknown_channel"])))
        .otherwise(pl.col("quality_flags"))
        .alias("quality_flags")
    )


def build_coverage_report(
    events: pl.LazyFrame, channels: Path, states: Path
) -> CoverageReport:
    """Count channel misses and observed values absent from the state reference."""
    joined = join_channels(events, channels).with_columns(
        pl.col("raw_value").cast(pl.String)
    )
    totals = (
        joined.select(
            pl.len().alias("total_events"),
            pl.col("object_id").is_null().sum().alias("unknown_channel_events"),
        )
        .collect()
        .row(0, named=True)
    )

    state_mappings = scan_state_reference(states).with_columns(
        pl.col("state_name").alias("raw_value")
    )
    valid_state_pairs = state_mappings.filter(~pl.col("is_conflicting")).select(
        "sensor_type", "raw_value"
    )
    conflicting_state_pairs = state_mappings.filter(pl.col("is_conflicting")).select(
        "sensor_type", "raw_value"
    )
    typed_events = joined.filter(pl.col("sensor_type").is_not_null())
    unmapped = (
        typed_events.join(
            valid_state_pairs, on=["sensor_type", "raw_value"], how="anti"
        )
        .group_by("sensor_type", "raw_value")
        .len()
        .collect()
    )
    conflicting = (
        typed_events.join(
            conflicting_state_pairs, on=["sensor_type", "raw_value"], how="inner"
        )
        .group_by("sensor_type", "raw_value")
        .len()
        .collect()
    )
    pairs = {
        (sensor_type, raw_value): count
        for sensor_type, raw_value, count in unmapped.iter_rows()
    }
    conflicts = {
        (sensor_type, raw_value): count
        for sensor_type, raw_value, count in conflicting.iter_rows()
    }
    return CoverageReport(
        total_events=totals["total_events"],
        unknown_channel_events=totals["unknown_channel_events"],
        unmapped_type_value_pairs=pairs,
        conflicting_type_value_pairs=conflicts,
    )
