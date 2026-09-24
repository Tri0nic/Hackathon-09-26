"""Train isolation, robust calibration and the frozen artifact boundary."""

import importlib
import json
from datetime import date
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

from fire_risk.data.quality import QualityThresholds, mark_historical_artifacts


@pytest.fixture
def calibration() -> ModuleType:
    assert importlib.util.find_spec("fire_risk.data.calibration") is not None
    return importlib.import_module("fire_risk.data.calibration")


def profiles() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "channel_id": ["a", "b", "c", "d"],
            "day": [date(y, 6, 1) for y in (2019, 2021, 2022, 2024)],
            "source_year": [2019, 2021, 2022, 2024],
            "event_count": [10, 20, 30, 40],
            "max_repeats_per_second": [2, 4, 6, 8],
            "longest_identical_state_run": [3, 6, 9, 12],
            "event_rate_deviation": [1.0, 2.0, 3.0, 4.0],
            "historical_artifact": [False] * 4,
            "exclude_from_fire_training": [False] * 4,
        }
    )


def hashes() -> dict[str, str]:
    return {"train-b.csv": "b" * 64, "train-a.csv": "a" * 64}


@pytest.mark.parametrize("year", [2018, 2025, 2026, 2027, None])
@pytest.mark.parametrize("flagged", [False, True])
def test_rejects_any_out_of_split_row_before_exclusions(
    calibration: ModuleType, year: int | None, flagged: bool
) -> None:
    poison = (
        profiles()
        .head(1)
        .with_columns(
            pl.lit(year, dtype=pl.Int64).alias("source_year"),
            pl.lit(flagged).alias("historical_artifact"),
            pl.lit(1e15).alias("event_rate_deviation"),
        )
    )
    for source in (poison, pl.concat([profiles(), poison])):
        with pytest.raises(calibration.CalibrationLeakageError, match="source_year"):
            calibration.calibrate_thresholds(source.lazy(), hashes(), seed=42)


def test_train_selection_is_independent_of_validation_test_values(
    calibration: ModuleType, tmp_path: Path
) -> None:
    poison = (
        profiles()
        .head(2)
        .with_columns(
            pl.Series("source_year", [2025, 2026]),
            *[
                pl.lit(10**9, dtype=pl.Int64).alias(c)
                for c in (
                    "event_count",
                    "max_repeats_per_second",
                    "longest_identical_state_run",
                )
            ],
            pl.lit(1e15).alias("event_rate_deviation"),
        )
    )
    all_profiles = pl.concat([profiles(), poison])
    selected = all_profiles.filter(pl.col("source_year").is_between(2019, 2024))
    left = calibration.calibrate_thresholds(profiles(), hashes(), seed=42)
    right = calibration.calibrate_thresholds(selected, hashes(), seed=42)
    calibration.write_calibration(tmp_path / "left.json", left)
    calibration.write_calibration(tmp_path / "right.json", right)
    assert (tmp_path / "left.json").read_bytes() == (
        tmp_path / "right.json"
    ).read_bytes()


def test_calibration_retains_2021_and_ignores_only_preflagged_rows(
    calibration: ModuleType,
) -> None:
    source = profiles().with_columns(pl.lit(True).alias("stuck"))
    value = calibration.calibrate_thresholds(source, hashes(), seed=42)
    assert value.thresholds == QualityThresholds(39, 8, 3.85, 12)
    assert value != calibration.calibrate_thresholds(
        source.filter(pl.col("source_year") != 2021), hashes(), seed=42
    )
    for flag in ("historical_artifact", "exclude_from_fire_training"):
        excluded = source.head(1).with_columns(
            pl.lit(2021, dtype=pl.Int64).alias("source_year"),
            pl.lit(True).alias(flag),
            pl.lit(10**9, dtype=pl.Int64).alias("event_count"),
        )
        assert (
            calibration.calibrate_thresholds(
                pl.concat([source, excluded]), hashes(), seed=42
            )
            == value
        )


def test_round_trip_canonical_versions_provenance_and_float(
    calibration: ModuleType, tmp_path: Path
) -> None:
    value = calibration.calibrate_thresholds(
        profiles(), hashes(), seed=42, implementation_revision="fixture-revision"
    )
    path = tmp_path / "thresholds.json"
    calibration.write_calibration(path, value)
    assert calibration.read_calibration(path) == value
    raw = path.read_bytes()
    payload = json.loads(raw)
    assert payload["train_periods"] == [
        "2019-01-01..2020-12-31",
        "2021-01-01..2021-12-31 (admissible intervals only)",
        "2022-01-01..2024-12-31",
    ]
    assert payload["implementation_revision"] == "fixture-revision"
    assert payload["seed"] == 42
    assert list(payload["source_sha256"]) == ["train-a.csv", "train-b.csv"]
    assert b'"max_event_rate_deviation":3.85' in raw
    assert (
        raw
        == (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode()
    )
    reordered = calibration.calibrate_thresholds(
        profiles().reverse(),
        dict(reversed(list(hashes().items()))),
        seed=42,
        implementation_revision="fixture-revision",
    )
    calibration.write_calibration(tmp_path / "reordered.json", reordered)
    assert raw == (tmp_path / "reordered.json").read_bytes()
    for field in ("schema_version", "calibration_version"):
        damaged = {**payload, field: "future-version"}
        path.write_text(json.dumps(damaged), encoding="utf-8")
        with pytest.raises(ValueError, match=field):
            calibration.read_calibration(path)


def test_sparse_profiles_have_safe_bounds_and_null_rate_fallback(
    calibration: ModuleType,
) -> None:
    source = (
        profiles()
        .head(1)
        .with_columns(
            pl.lit(1).alias("event_count"),
            pl.lit(1).alias("max_repeats_per_second"),
            pl.lit(1).alias("longest_identical_state_run"),
            pl.lit(None, dtype=pl.Float64).alias("event_rate_deviation"),
        )
    )
    value = calibration.calibrate_thresholds(source, hashes(), seed=42)
    assert value.thresholds == QualityThresholds(2, 2, 2.0, 2)
    assert value.rationale


def test_split_rejection_precedes_metric_evaluation(calibration: ModuleType) -> None:
    poisoned = (
        profiles()
        .with_columns(pl.Series("_invalid", ["not-a-number"] * 4))
        .lazy()
        .with_columns(
            pl.lit(2026).alias("source_year"),
            pl.col("_invalid").cast(pl.Float64).alias("event_rate_deviation"),
        )
    )
    with pytest.raises(calibration.CalibrationLeakageError, match="2026"):
        calibration.calibrate_thresholds(poisoned, hashes(), seed=42)


@pytest.mark.parametrize(
    "missing",
    [
        "min_burst_events",
        "max_repeats_per_second",
        "max_event_rate_deviation",
        "min_stuck_run",
    ],
)
def test_loading_rejects_partial_thresholds_instead_of_filling_defaults(
    calibration: ModuleType, tmp_path: Path, missing: str
) -> None:
    path = tmp_path / "partial.json"
    value = calibration.calibrate_thresholds(profiles(), hashes(), seed=42)
    calibration.write_calibration(path, value)
    payload = json.loads(path.read_text())
    del payload["thresholds"][missing]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="threshold"):
        calibration.read_calibration(path)


@pytest.mark.parametrize(
    "kind", ["empty", "excluded", "year_missing", "nan", "negative"]
)
def test_invalid_calibration_inputs_fail_closed(
    calibration: ModuleType, kind: str
) -> None:
    source = profiles()
    if kind == "empty":
        source = source.head(0)
    elif kind == "excluded":
        source = source.with_columns(pl.lit(True).alias("historical_artifact"))
    elif kind == "year_missing":
        source = source.drop("source_year")
    elif kind == "nan":
        source = source.with_columns(pl.lit(float("nan")).alias("event_rate_deviation"))
    else:
        source = source.with_columns(pl.lit(-1).alias("event_count"))
    with pytest.raises(ValueError):
        calibration.calibrate_thresholds(source, hashes(), seed=42)


@pytest.mark.parametrize("year", [2024, 2025, 2026])
def test_loaded_thresholds_apply_unchanged_to_every_split(
    calibration: ModuleType, tmp_path: Path, year: int
) -> None:
    value = calibration.calibrate_thresholds(profiles(), hashes(), seed=42)
    path = tmp_path / "frozen.json"
    calibration.write_calibration(path, value)
    raw = path.read_bytes()
    frozen = calibration.read_calibration(path)
    source = pl.DataFrame(
        {
            "channel_id": ["a"],
            "registered_at": [date(year, 6, 1)],
        }
    ).lazy()
    day = (
        profiles()
        .head(1)
        .with_columns(
            pl.lit(date(year, 6, 1)).alias("day"),
            pl.lit(39).alias("event_count"),
            pl.lit(8).alias("max_repeats_per_second"),
            pl.lit(12).alias("longest_identical_state_run"),
        )
        .drop("source_year", "historical_artifact", "exclude_from_fire_training")
    )
    result = mark_historical_artifacts(source, day.lazy(), frozen.thresholds).collect()
    assert result["burst"].item() is True
    assert result["stuck"].item() is True
    assert result["historical_artifact"].item() is False
    assert path.read_bytes() == raw
