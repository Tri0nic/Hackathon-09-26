import subprocess
import sys
from datetime import UTC, datetime

import polars as pl

from fire_risk.ml.inference import load_predictor
from fire_risk.ml.training import TrainingConfig, train_all


def test_cli_keeps_explicit_train_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "fire_risk.ml_cli", "train", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "fire_risk.ml_cli train [OPTIONS]" in result.stdout


def test_artifact_round_trip_has_stable_monotonic_prediction(tmp_path) -> None:
    rows: list[dict[str, object]] = []
    for year in range(2019, 2027):
        for index in range(6):
            positive = index % 2 == 1
            rows.append(
                {
                    "object_id": f"object-{index % 2}",
                    "scoring_timestamp": datetime(
                        year, 2, index + 1, tzinfo=UTC
                    ),
                    "feature_a": float(index),
                    "feature_b": float(index * 2),
                    "target_now_available": True,
                    "target_6h_available": True,
                    "target_12h_available": True,
                    "target_24h_available": True,
                    "target_now": positive,
                    "target_6h": positive,
                    "target_12h": positive,
                    "target_24h": positive,
                    "episode_group_id": None,
                }
            )
    parquet = tmp_path / "snapshots.parquet"
    pl.DataFrame(rows).write_parquet(parquet)
    artifact = tmp_path / "artifact"

    manifest = train_all(
        TrainingConfig(
            input_path=parquet,
            output_dir=artifact,
            task_type="CPU",
            train_max_rows=24,
            calibration_max_rows=6,
            iterations=5,
            depth=2,
            learning_rate=0.2,
            early_stopping_rounds=2,
            progress_interval=5,
        )
    )
    prediction = load_predictor(manifest).predict(
        {"feature_a": 1.0, "ignored": 999.0}, top_k=2
    )

    assert prediction.model_version.startswith("catboost-")
    assert prediction.calculated_at.tzinfo is not None
    assert 0.0 <= prediction.p_now <= 1.0
    assert 0.0 <= prediction.p_6h <= prediction.p_12h <= prediction.p_24h <= 1.0
    assert set(prediction.decisions) == {"now", "6h", "12h", "24h"}
    assert any(
        factor.feature == "feature_a" and factor.value == 1.0
        for factor in prediction.factors
    )
