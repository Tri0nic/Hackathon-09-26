"""Bounded episode fragments preserve cross-month chains and event membership."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fire_risk.data.episodes import build_episodes


def _events() -> pl.DataFrame:
    timestamps = [
        datetime(2024, 1, 31, 23, 40, tzinfo=UTC),
        datetime(2024, 2, 1, 0, 10, tzinfo=UTC),
        datetime(2024, 2, 29, 23, 50, tzinfo=UTC),
        datetime(2024, 3, 1, 0, 20, tzinfo=UTC),
        datetime(2024, 4, 1, tzinfo=UTC),
    ]
    return pl.DataFrame(
        {
            "event_id": [
                f"{obj}-{i}" for obj in ("A", "B", "unknown") for i in range(5)
            ],
            "object_id": [obj for obj in ("A", "B", None) for _ in range(5)],
            "channel_id": ["smoke-1", "gas-1", "heat-1", "smoke-1", "heat-1"] * 3,
            "registered_at": timestamps * 3,
            "sensor_type": ["smoke", "gas", "heat", "smoke", "heat"] * 3,
            "alarm_flag": [True, False, False, False, True] * 3,
            "value_kind": [
                "known_state",
                "numeric",
                "malfunction",
                "known_state",
                "numeric",
            ]
            * 3,
            "numeric_value": [None, 1.5, None, None, 40.0] * 3,
            "historical_artifact": [False, False, True, False, False] * 3,
            "exclude_from_fire_training": [False, False, True, False, False] * 3,
            "picket_sort_key": [1.0, 3.0, None, 2.0, 7.0] * 3,
            "quality_flags": [["unknown_state"], [], ["historical_artifact"], [], []]
            * 3,
        }
    ).reverse()


@pytest.mark.parametrize("gap", [timedelta(minutes=30), timedelta(days=40)])
def test_month_fragments_match_global_oracle_and_stitch_chains(
    tmp_path: Path, gap: timedelta
) -> None:
    source = _events()
    path = tmp_path / "input.parquet"
    source.write_parquet(path, row_group_size=1)
    expected_episodes, expected_membership = build_episodes(pl.scan_parquet(path), gap)
    episodes, membership = build_episodes(
        pl.scan_parquet(path), gap, temp_dir=tmp_path / "spool"
    )
    assert_frame_equal(episodes.collect(), expected_episodes.collect())
    assert_frame_equal(
        membership.sort("event_id").collect(), expected_membership.collect()
    )
    rows = episodes.collect()
    assert rows.height == (2 if gap.days else 6)
    first = rows.filter(pl.col("object_id") == "A").row(0, named=True)
    assert first["episode_id"] == "ep:1:A:2024-01-31T23:40:00.000000Z"
    assert first["started_at"] == datetime(2024, 1, 31, 23, 40, tzinfo=UTC)
    assert first["ended_at"] == (
        datetime(2024, 4, 1, tzinfo=UTC)
        if gap.days
        else datetime(2024, 2, 1, 0, 10, tzinfo=UTC)
    )
    assert membership.collect()["episode_id"].null_count() == 5
    reversed_path = tmp_path / "reversed.parquet"
    source.reverse().write_parquet(reversed_path, row_group_size=2)
    again, again_members = build_episodes(
        pl.scan_parquet(reversed_path), gap, temp_dir=tmp_path / "again"
    )
    assert_frame_equal(episodes.collect(), again.collect())
    assert_frame_equal(membership.collect(), again_members.collect())


def test_disk_backed_skewed_object_keeps_event_windows_within_month(
    tmp_path: Path,
) -> None:
    count = 200_000
    source = pl.DataFrame(
        {
            "event_id": [f"e-{i:06}" for i in range(count)],
            "object_id": ["large-object"] * count,
            "channel_id": ["channel"] * count,
            "registered_at": [
                datetime(2024, month, 1, tzinfo=UTC) for month in (1, 2, 3, 4)
            ]
            * (count // 4),
            "sensor_type": ["smoke"] * count,
            "alarm_flag": [True] * count,
            "picket_sort_key": [1.0] * count,
            "quality_flags": [[]] * count,
        },
        schema_overrides={"quality_flags": pl.List(pl.String)},
    )
    path = tmp_path / "skewed.parquet"
    source.write_parquet(path, row_group_size=1000)
    episodes, members = build_episodes(
        pl.scan_parquet(path), timedelta(days=40), temp_dir=tmp_path / "spool"
    )
    assert episodes.collect().height == 1
    assert members.select(pl.len()).collect().item() == count
    partitions = list((tmp_path / "spool").rglob("months/*/*.parquet"))
    assert len(partitions) == 4
    for part in partitions:
        assert (
            pl.scan_parquet(part)
            .select(pl.col("registered_at").dt.month().n_unique())
            .collect()
            .item()
            == 1
        )
        assert pl.scan_parquet(part).select(pl.len()).collect().item() == count // 4
    for frame in (episodes, members):
        plan = frame.show_graph(
            show=False, raw_output=True, engine="streaming", plan_stage="physical"
        )
        assert str(path) not in plan
        assert "registered_at" not in plan
        assert "in-memory-join" not in plan


def test_month_fragments_preserve_empty_and_all_unknown_schemas(tmp_path: Path) -> None:
    for index, source in enumerate(
        (
            _events().head(0),
            _events().with_columns(pl.lit(None, dtype=pl.String).alias("object_id")),
        )
    ):
        expected = build_episodes(source.lazy(), timedelta(minutes=30))
        actual = build_episodes(
            source.lazy(), timedelta(minutes=30), temp_dir=tmp_path / str(index)
        )
        for got, want in zip(actual, expected, strict=True):
            assert_frame_equal(
                got.collect().sort(got.collect_schema().names()[0]),
                want.collect().sort(want.collect_schema().names()[0]),
            )
