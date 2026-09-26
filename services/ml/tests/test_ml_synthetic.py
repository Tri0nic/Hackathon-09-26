from datetime import UTC, datetime

import polars as pl
from fire_risk.ml.synthetic import with_synthetic_targets


def test_synthetic_targets_are_deterministic_and_nested() -> None:
    source = pl.DataFrame(
        {
            "object_id": ["a", "b", "c"],
            "scoring_timestamp": [datetime(2024, 1, 1, hour, tzinfo=UTC) for hour in range(3)],
            "event_count_5m": [0, 10, 100],
            "event_count_30m": [0, 50, 500],
            "alarm_count_30m": [0, 1, 5],
            "temperature_max_30m": [20.0, 30.0, 60.0],
            "gas_max_30m": [0.0, 0.3, 2.0],
            "smoke_heat_30m": [False, True, True],
            **{f"target_{h}": [False] * 3 for h in ("now", "6h", "12h", "24h")},
        }
    ).lazy()

    first = with_synthetic_targets(source).collect()
    second = with_synthetic_targets(source).collect()

    assert first.select("target_now", "target_6h", "target_12h", "target_24h").equals(
        second.select("target_now", "target_6h", "target_12h", "target_24h")
    )
    assert first.filter(
        pl.col("target_now") & ~pl.col("target_6h")
        | pl.col("target_6h") & ~pl.col("target_12h")
        | pl.col("target_12h") & ~pl.col("target_24h")
    ).is_empty()
