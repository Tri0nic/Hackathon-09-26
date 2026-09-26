import numpy as np
import pytest
from fire_risk.ml.training import (
    Calibration,
    TrainingConfig,
    _signature,
    calibrate,
    enforce_monotonic,
    fit_calibration,
    threshold_for_recall,
)


def test_threshold_for_recall_keeps_minimum_precision() -> None:
    labels = np.array([0, 0, 0, 1, 1, 1])
    probabilities = np.array([0.1, 0.2, 0.4, 0.5, 0.8, 0.9])

    threshold = threshold_for_recall(probabilities, labels, target_recall=2 / 3)
    predictions = probabilities >= threshold

    assert predictions.tolist() == [False, False, False, False, True, True]


def test_calibration_produces_probabilities_and_validation_threshold() -> None:
    raw = np.array([-4.0, -1.0, 1.0, 4.0])
    labels = np.array([0, 0, 1, 1])

    fitted = fit_calibration(raw, labels)
    probabilities = calibrate(raw, fitted)

    assert np.all((0.0 <= probabilities) & (probabilities <= 1.0))
    assert 0.0 < fitted.threshold < 1.0
    predictions = probabilities >= fitted.threshold
    assert predictions.tolist() == [False, False, True, True]


def test_calibration_rejects_single_class_validation_data() -> None:
    with pytest.raises(ValueError, match="both classes"):
        fit_calibration(np.array([-1.0, 1.0]), np.array([1, 1]))


def test_monotonicity_leaves_now_independent_and_uses_cumulative_maximum() -> None:
    probabilities = {
        "now": np.array([0.9, 0.2]),
        "6h": np.array([0.6, 0.1]),
        "12h": np.array([0.2, 0.5]),
        "24h": np.array([0.4, 0.3]),
    }

    corrected = enforce_monotonic(probabilities)

    assert corrected["now"].tolist() == [0.9, 0.2]
    assert corrected["6h"].tolist() == [0.6, 0.1]
    assert corrected["12h"].tolist() == [0.6, 0.5]
    assert corrected["24h"].tolist() == [0.6, 0.5]


def test_training_defaults_are_bounded_for_the_hackathon_run() -> None:
    config = TrainingConfig(input_path="snapshots.parquet", output_dir="models")

    assert config.seed == 42
    assert config.train_max_rows == 1_000_000
    assert config.calibration_max_rows == 300_000
    assert config.iterations == 600
    assert config.depth == 8
    assert config.early_stopping_rounds == 75
    assert config.progress_interval == 25


def test_manual_calibration_is_numerically_stable() -> None:
    fitted = Calibration(coefficient=1000.0, intercept=0.0, threshold=0.5)

    result = calibrate(np.array([-1000.0, 1000.0]), fitted)

    assert np.isfinite(result).all()
    assert result[0] < 1e-300
    assert result[1] == 1.0


def test_resume_signature_changes_with_implementation() -> None:
    config = TrainingConfig(input_path="snapshots.parquet", output_dir="models")
    identity = {"sha256": "data"}

    first = _signature(config, identity, ["signal"], "implementation-a")
    second = _signature(config, identity, ["signal"], "implementation-b")

    assert first != second
