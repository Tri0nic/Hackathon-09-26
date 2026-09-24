"""Stable object inventories derived exclusively from channel references."""

import polars as pl

SIGNAL_FAMILIES = {
    "smoke": ["smoke", "датчик дыма"],
    "heat": ["heat", "датчик температуры"],
    "gas": ["gas", "газовый датчик"],
    "manual": ["manual_call_point", "ручной извещатель"],
    "uir": ["uir-r", "уир-р"],
    "pump": ["pump", "насос"],
}


def family_expression(family: str) -> pl.Expr:
    """Match the same normalized MVP aliases in events and reference rows."""
    return (
        pl.col("sensor_type")
        .str.strip_chars()
        .str.to_lowercase()
        .is_in(SIGNAL_FAMILIES[family])
        .fill_null(False)
    )


def build_object_inventory(
    channels: pl.LazyFrame,
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """Return sorted scalar totals and an exact object/type count mapping.

    The long mapping is independently serializable as Parquet. Unknown sensor
    types remain in this table and in the total, even without an MVP family.
    Duplicate IDs are rejected rather than silently inflating denominators.
    """
    duplicates = (
        channels.group_by("channel_id")
        .len()
        .filter(pl.col("len") > 1)
        .select("channel_id")
        .sort("channel_id")
        .collect(engine="streaming")
    )
    if not duplicates.is_empty():
        raise ValueError(
            f"Duplicate channel_id values: {duplicates['channel_id'].to_list()}"
        )
    reference = channels.filter(pl.col("object_id").is_not_null())
    totals = (
        reference.group_by("object_id")
        .agg(
            pl.len().cast(pl.Int64).alias("inventory_channel_count"),
            *[
                family_expression(family)
                .sum()
                .cast(pl.Int64)
                .alias(f"inventory_{family}_channel_count")
                for family in SIGNAL_FAMILIES
            ],
        )
        .sort("object_id")
    )
    by_type = (
        reference.group_by("object_id", "sensor_type")
        .agg(pl.len().cast(pl.Int64).alias("channel_count"))
        .sort("object_id", "sensor_type")
    )
    return totals, by_type
