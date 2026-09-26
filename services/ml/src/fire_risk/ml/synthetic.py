"""Deterministic customer-requested synthetic labels for demo evaluation."""

import polars as pl


def with_synthetic_targets(source: pl.LazyFrame) -> pl.LazyFrame:
    """Replace targets with nested labels sampled from an observable risk score."""
    score = (
        pl.col("event_count_30m").fill_null(0).clip(0, 200) * 0.02
        + pl.col("event_count_5m").fill_null(0).clip(0, 50) * 0.04
        + pl.col("alarm_count_30m").fill_null(0).clip(0, 10) * 0.5
        + (pl.col("temperature_max_30m").fill_null(20) - 20).clip(0, 20) * 0.1
        + pl.col("gas_max_30m").fill_null(0).clip(0, 2) * 1.0
        + pl.col("smoke_heat_30m").fill_null(False).cast(pl.Float64) * 2.0
    )
    uniform = (
        pl.struct("object_id", "scoring_timestamp").hash(seed=20260926).cast(pl.Float64)
        / float(2**64 - 1)
    )
    settings = {
        "now": (5.0, 2.0),
        "6h": (4.0, 1.3),
        "12h": (3.0, 1.23),
        "24h": (2.5, 1.22),
    }
    expressions = []
    cumulative_probability: pl.Expr | None = None
    for horizon, (threshold, slope) in settings.items():
        probability = 1.0 / (1.0 + (-(score - threshold) * slope).exp())
        cumulative_probability = (
            probability
            if cumulative_probability is None
            else pl.max_horizontal(cumulative_probability, probability)
        )
        expressions.append(
            (uniform < cumulative_probability).alias(f"target_{horizon}")
        )
    return source.with_columns(*expressions)
