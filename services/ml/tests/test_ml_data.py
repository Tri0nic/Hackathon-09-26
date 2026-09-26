from datetime import UTC, datetime

import polars as pl

from fire_risk.ml.data import feature_columns, sample_training, split_frame


def _snapshots() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "object_id": ["a", "a", "b", "c", "d", "e"],
            "scoring_timestamp": [
                datetime(2024, 12, 31, 23, tzinfo=UTC),
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2024, 6, 1, tzinfo=UTC),
                datetime(2025, 6, 1, tzinfo=UTC),
                datetime(2026, 6, 1, tzinfo=UTC),
                datetime(2025, 7, 1, tzinfo=UTC),
            ],
            "signal": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "flag": [True, False, True, False, True, False],
            "target_now_available": [True] * 6,
            "target_6h_available": [True, True, True, True, True, False],
            "target_12h_available": [True] * 6,
            "target_24h_available": [True] * 6,
            "target_now": [False, False, True, False, True, False],
            "target_6h": [False, True, True, False, True, None],
            "target_12h": [False, True, True, False, True, False],
            "target_24h": [False, True, True, False, True, False],
            "episode_group_id": ["cross", "cross", "train", "valid", "test", None],
        }
    ).lazy()


def test_split_excludes_cross_boundary_groups_and_censored_rows() -> None:
    split = split_frame(_snapshots(), "6h")

    assert split.train.select("object_id").collect().to_series().to_list() == ["b"]
    assert split.validation.select("object_id").collect().to_series().to_list() == ["c"]
    assert split.test.select("object_id").collect().to_series().to_list() == ["d"]
    assert split.features == ["signal", "flag"]


def test_feature_columns_never_exposes_identifiers_or_targets() -> None:
    assert feature_columns(_snapshots().collect_schema()) == ["signal", "flag"]


def test_class_aware_sampling_is_bounded_balanced_and_deterministic() -> None:
    frame = pl.DataFrame(
        {
            "object_id": [f"o-{i}" for i in range(24)],
            "scoring_timestamp": [
                datetime(2024, 1, 1, tzinfo=UTC)
            ] * 24,
            "target_6h": [True] * 4 + [False] * 20,
            "signal": list(range(24)),
        }
    )

    first = sample_training(frame, "target_6h", max_rows=6, seed=42)
    second = sample_training(frame.reverse(), "target_6h", max_rows=6, seed=42)

    assert first.height == 6
    assert first["target_6h"].sum() == 3
    assert first["object_id"].to_list() == second["object_id"].to_list()
