"""Reference-owned inventory, including channels absent from the journal."""

from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fire_risk.data.inventory import build_object_inventory
from fire_risk.data.references import scan_channel_reference


def reference() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "object_id": ["mine", "mine", "mine", "other"],
            "channel_id": ["smoke-1", "smoke-2", "heat", "unknown"],
            "sensor_type": ["Датчик дыма", "Датчик дыма", "heat", "Other type"],
        }
    ).lazy()


def test_inventory_counts_reference_channels_and_preserves_exact_types(
    tmp_path: Path,
) -> None:
    totals, by_type = build_object_inventory(reference())
    result = totals.collect()
    assert result["object_id"].to_list() == ["mine", "other"]
    assert result["inventory_channel_count"].to_list() == [3, 1]
    assert result["inventory_smoke_channel_count"].to_list() == [2, 0]
    assert result["inventory_heat_channel_count"].to_list() == [1, 0]
    assert result["inventory_gas_channel_count"].to_list() == [0, 0]
    assert by_type.collect().rows() == [
        ("mine", "heat", 1),
        ("mine", "Датчик дыма", 2),
        ("other", "Other type", 1),
    ]
    for original, reordered in zip(
        (totals, by_type), build_object_inventory(reference().reverse()), strict=True
    ):
        assert_frame_equal(original.collect(), reordered.collect())
    by_type.sink_parquet(tmp_path / "inventory_by_type.parquet")
    assert_frame_equal(
        by_type.collect(), pl.read_parquet(tmp_path / "inventory_by_type.parquet")
    )


def test_inventory_rejects_duplicate_channel_ids_even_across_objects() -> None:
    duplicate = reference().head(1).with_columns(pl.lit("different").alias("object_id"))
    with pytest.raises(ValueError, match="Duplicate channel_id"):
        build_object_inventory(pl.concat([reference(), duplicate]))


def test_empty_reference_retains_typed_inventory_tables() -> None:
    totals, by_type = build_object_inventory(reference().head(0))
    assert totals.collect().is_empty()
    assert by_type.collect().is_empty()
    assert totals.collect_schema()["inventory_channel_count"] == pl.Int64
    assert by_type.collect_schema()["channel_count"] == pl.Int64


def test_authoritative_russian_headers_and_types_populate_signal_families(
    tmp_path: Path,
) -> None:
    types = [
        "Тепловой датчик",
        "Датчик температуры",
        "Состояние УИР-Р",
        "Состояние насоса",
    ]
    path = tmp_path / "reference.csv"
    pl.DataFrame(
        {
            "ид_канала_данных": ["h1", "h2", "u", "p"],
            "тип_инж_системы": ["fire"] * 4,
            "тип_датчика": types,
            "название_датчика": types,
            "ид_объект": ["mine"] * 4,
            "иерархия_уровень": [3] * 4,
            "диспетчерское_название_объекта": ["mine"] * 4,
            "объект_ур2": ["2"] * 4,
            "объект_ур2_имя": ["two"] * 4,
            "объект_ур1": ["1"] * 4,
            "объект_ур1_имя": ["one"] * 4,
            "родитель": ["2"] * 4,
            "Имя": types,
        }
    ).write_csv(path)
    totals, raw_types = build_object_inventory(scan_channel_reference(path))
    assert totals.select(
        "inventory_channel_count",
        "inventory_heat_channel_count",
        "inventory_uir_channel_count",
        "inventory_pump_channel_count",
    ).collect().row(0) == (4, 2, 1, 1)
    assert set(raw_types.collect()["sensor_type"]) == set(types)
