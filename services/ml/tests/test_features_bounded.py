"""Disk-backed features retain full-history semantics across local days."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fire_risk.config import PipelineConfig
from fire_risk.data.features import attach_horizon_targets, build_feature_snapshots
from fire_risk.data.quality import QualityThresholds


def history() -> pl.DataFrame:
    start = datetime(2021, 1, 30, 23, 45, tzinfo=ZoneInfo("Europe/Moscow"))
    rows = []
    for index, (minutes, channel, raw, kind, numeric) in enumerate(
        [
            (0, "s", "on", "known_state", None),
            (15, "s", "on", "known_state", None),
            (16, "s", "on", "known_state", None),
            (17, "s", "on", "known_state", None),
            (30, "g", "1", "numeric", 1.0),
            (45, "g", "2", "numeric", 2.0),
            (1440, "s", "broken", "malfunction", None),
            (1455, "g", "3", "numeric", 3.0),
            (2880, "s", "broken", "malfunction", None),
            (5760, "g", "4", "numeric", 4.0),
            (5775, "s", "off", "known_state", None),
        ]
    ):
        rows.append(
            {
                "object_id": "a",
                "registered_at": start + timedelta(minutes=minutes),
                "channel_id": channel,
                "sensor_type": "methane" if channel == "g" else "smoke",
                "event_id": f"e{index:03}",
                "raw_value": raw,
                "value_kind": kind,
                "numeric_value": numeric,
                "alarm_flag": raw == "on",
                "quality_flags": [],
            }
        )
    rows.append(
        {**rows[0], "object_id": "b", "channel_id": "other", "event_id": "other"}
    )
    return pl.DataFrame(rows, schema_overrides={"quality_flags": pl.List(pl.String)})


@pytest.mark.parametrize("step", [15, 17])
def test_bounded_features_equal_full_history_across_days_and_sparse_gaps(
    tmp_path: Path,
    step: int,
) -> None:
    data = history()
    inventory = pl.DataFrame(
        {
            "object_id": ["a", "a", "a", "b"],
            "channel_id": ["s", "g", "never", "other"],
            "sensor_type": ["smoke", "methane", "heat", "smoke"],
        }
    ).lazy()
    config = PipelineConfig(scoring_step_minutes=step)
    thresholds = QualityThresholds(3, 2, 2.0, 3)
    expected = build_feature_snapshots(
        data.lazy(), config, inventory, thresholds=thresholds
    ).collect()
    path = tmp_path / "input.parquet"
    data.reverse().write_parquet(path, row_group_size=2)
    result = build_feature_snapshots(
        pl.scan_parquet(path),
        config,
        inventory,
        thresholds=thresholds,
        temp_dir=tmp_path / "bounded",
    )
    actual = result.collect().sort(["object_id", "scoring_timestamp"])
    assert_frame_equal(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
    first = actual.filter(pl.col("object_id") == "a").row(0, named=True)
    assert first["gas_slope_per_hour_24h"] is None
    assert first["historical_daily_event_baseline"] is None
    assert first["stale_channel_count"] == (2 if step == 15 else 3)
    physical = result.show_graph(
        show=False, raw_output=True, engine="streaming", plan_stage="physical"
    )
    assert physical is not None and str(path) not in physical
    assert "in-memory-join" not in physical and "rolling" not in physical


def test_bounded_feature_event_intermediates_are_local_days(tmp_path: Path) -> None:
    data = pl.concat([history().head(1)] * 50_000)
    chunks = []
    for day in range(4):
        chunks.append(
            data.with_columns(
                pl.datetime_range(
                    datetime(2024, 1, 1 + day, tzinfo=ZoneInfo("Europe/Moscow")),
                    datetime(2024, 1, 1 + day, tzinfo=ZoneInfo("Europe/Moscow"))
                    + timedelta(seconds=49_999),
                    interval="1s",
                    eager=True,
                ).alias("registered_at")
            )
        )
    # Build a genuinely disk-backed repeated-value source without a large collect.
    path = tmp_path / "input.parquet"
    pl.concat(chunks).with_row_index("index").with_columns(
        pl.col("index").cast(pl.String).alias("event_id")
    ).drop("index").write_parquet(path, row_group_size=257)
    result = build_feature_snapshots(
        pl.scan_parquet(path),
        PipelineConfig(scoring_step_minutes=60),
        thresholds=QualityThresholds(),
        temp_dir=tmp_path / "bounded",
    )
    actual = result.collect()
    assert actual["event_count_24h"].max() == 50_000
    assert actual["scoring_timestamp"].n_unique() == actual.height
    daily = list((tmp_path / "bounded").rglob("prepared/*.parquet"))
    assert len(daily) == 4
    assert (
        max(pl.scan_parquet(p).select(pl.len()).collect().item() for p in daily)
        == 50_000
    )


def test_bounded_targets_preserve_cross_day_incident_context(tmp_path: Path) -> None:
    source = history()
    config = PipelineConfig(scoring_step_minutes=60)
    snapshots = build_feature_snapshots(
        source.lazy(), config, thresholds=QualityThresholds()
    ).collect()
    first = snapshots["scoring_timestamp"].min()
    labels = pl.DataFrame(
        {
            "object_id": ["a", "a"],
            "incident_id": ["one", "two"],
            "started_at": [first + timedelta(hours=23), first + timedelta(hours=26)],
            "ended_at": [first + timedelta(hours=25), first + timedelta(hours=27)],
        }
    ).lazy()
    observed = first + timedelta(hours=90)
    expected = attach_horizon_targets(snapshots.lazy(), labels, observed).collect()
    actual = attach_horizon_targets(
        snapshots.lazy(), labels, observed, temp_dir=tmp_path
    ).collect()
    assert_frame_equal(actual.sort(["object_id", "scoring_timestamp"]), expected)


def test_bounded_current_day_features_ignore_appended_future_events(
    tmp_path: Path,
) -> None:
    source = history()
    cutoff = source["registered_at"].max()
    future = source.filter(pl.col("object_id") == "a").tail(1).with_columns(
        pl.lit(cutoff + timedelta(minutes=1)).alias("registered_at"),
        pl.lit("future").alias("event_id"),
        pl.lit("broken").alias("raw_value"),
        pl.lit("malfunction").alias("value_kind"),
    )
    outputs = []
    for name, rows in [("before", source), ("after", pl.concat([source, future]))]:
        outputs.append(
            build_feature_snapshots(
                rows.lazy(),
                PipelineConfig(),
                thresholds=QualityThresholds(2, 2, 2.0, 2),
                temp_dir=tmp_path / name,
            )
            .filter(pl.col("scoring_timestamp") <= cutoff)
            .collect()
            .sort(["object_id", "scoring_timestamp"])
        )
    assert_frame_equal(*outputs)
