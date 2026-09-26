"""Sequential CatBoost training, calibration, metrics, and artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from catboost import CatBoostClassifier  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)

from fire_risk.ml.data import sample_training, split_frame

HORIZONS = ("now", "6h", "12h", "24h")


@dataclass(frozen=True)
class Calibration:
    coefficient: float
    intercept: float
    threshold: float


@dataclass(frozen=True)
class TrainingConfig:
    input_path: str | Path
    output_dir: str | Path
    task_type: str = "GPU"
    seed: int = 42
    train_max_rows: int = 1_000_000
    calibration_max_rows: int = 300_000
    test_max_rows: int | None = None
    iterations: int = 600
    depth: int = 8
    learning_rate: float = 0.08
    early_stopping_rounds: int = 75
    progress_interval: int = 25
    resume: bool = True


def calibrate(raw_scores: np.ndarray, calibration: Calibration) -> np.ndarray:
    """Apply numerically stable sigmoid calibration to raw model scores."""
    logits = np.clip(
        np.asarray(raw_scores, dtype=np.float64) * calibration.coefficient
        + calibration.intercept,
        -709.0,
        709.0,
    )
    return 1.0 / (1.0 + np.exp(-logits))


def fit_calibration(raw_scores: np.ndarray, labels: np.ndarray) -> Calibration:
    """Fit Platt scaling and select the validation-F1 threshold."""
    y = np.asarray(labels, dtype=np.int8)
    if np.unique(y).size != 2:
        raise ValueError("calibration requires both classes in validation data")
    estimator = LogisticRegression(random_state=0)
    estimator.fit(np.asarray(raw_scores).reshape(-1, 1), y)
    provisional = Calibration(
        coefficient=float(estimator.coef_[0, 0]),
        intercept=float(estimator.intercept_[0]),
        threshold=0.5,
    )
    probabilities = calibrate(raw_scores, provisional)
    precision, recall, thresholds = precision_recall_curve(y, probabilities)
    if thresholds.size == 0:
        threshold = 0.5
    else:
        denominator = precision[:-1] + recall[:-1]
        scores = np.divide(
            2 * precision[:-1] * recall[:-1],
            denominator,
            out=np.zeros_like(denominator),
            where=denominator > 0,
        )
        threshold = float(thresholds[int(np.argmax(scores))])
    return Calibration(provisional.coefficient, provisional.intercept, threshold)


def enforce_monotonic(
    probabilities: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Enforce cumulative forecast horizons while keeping now independent."""
    corrected = {name: np.asarray(values).copy() for name, values in probabilities.items()}
    corrected["12h"] = np.maximum(corrected["6h"], corrected["12h"])
    corrected["24h"] = np.maximum(corrected["12h"], corrected["24h"])
    return corrected


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _input_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "size": path.stat().st_size, "sha256": digest.hexdigest()}


def _cap_rows(frame: pl.LazyFrame, max_rows: int, seed: int) -> pl.DataFrame:
    count = frame.select(pl.len()).collect().item()
    if count <= max_rows:
        return frame.collect()
    fraction = min(1.0, (max_rows / count) * 1.25)
    threshold = int(((2**64) - 1) * fraction)
    return (
        frame.filter(
            pl.struct("object_id", "scoring_timestamp").hash(seed=seed)
            <= pl.lit(threshold, dtype=pl.UInt64)
        )
        .head(max_rows)
        .collect()
    )


def _matrix(
    frame: pl.DataFrame, features: list[str], medians: dict[str, float] | None = None
) -> tuple[np.ndarray, dict[str, float]]:
    values = frame.select(features).cast(pl.Float32).to_numpy()
    if medians is None:
        computed = np.nanmedian(values, axis=0)
        computed = np.where(np.isfinite(computed), computed, 0.0)
        medians = dict(zip(features, map(float, computed), strict=True))
    fill = np.asarray([medians[name] for name in features], dtype=np.float32)
    values = np.where(np.isfinite(values), values, fill)
    return values.astype(np.float32, copy=False), medians


def _metrics(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = probabilities >= threshold
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0
    )
    result: dict[str, Any] = {
        "rows": int(labels.size),
        "positives": int(labels.sum()),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "brier": float(brier_score_loss(labels, probabilities)),
        "threshold": threshold,
        "label_source": "proxy",
        "warning": "Proxy-label reproduction, not confirmed real-fire detection quality.",
    }
    result["roc_auc"] = (
        float(roc_auc_score(labels, probabilities)) if np.unique(labels).size == 2 else None
    )
    return result


def _config_payload(config: TrainingConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["input_path"] = str(Path(config.input_path).resolve())
    payload["output_dir"] = str(Path(config.output_dir).resolve())
    return payload


def _implementation_revision() -> str:
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name("data.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _signature(
    config: TrainingConfig,
    identity: dict[str, Any],
    features: list[str],
    implementation_revision: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "config": _config_payload(config),
        "input": identity,
        "features": features,
        "implementation_revision": implementation_revision
        if implementation_revision is not None
        else _implementation_revision(),
    }
    payload["config"].pop("resume", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def train_all(config: TrainingConfig) -> Path:
    """Train four horizons sequentially and return the final manifest path."""
    input_path = Path(config.input_path)
    output_dir = Path(config.output_dir)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = _input_identity(input_path)
    implementation_revision = _implementation_revision()
    source = pl.scan_parquet(input_path)
    manifest_horizons: dict[str, Any] = {}
    features: list[str] | None = None

    for index, horizon in enumerate(HORIZONS, start=1):
        started = time.perf_counter()
        split = split_frame(source, horizon)
        features = split.features
        signature = _signature(config, identity, features, implementation_revision)
        model_path = output_dir / f"model_{horizon}.cbm"
        metadata_path = output_dir / f"model_{horizon}.json"
        if config.resume and model_path.is_file() and metadata_path.is_file():
            saved = json.loads(metadata_path.read_text(encoding="utf-8"))
            if saved.get("signature") == signature:
                print(f"[{index}/4] {horizon.upper()} reused: {model_path}", flush=True)
                manifest_horizons[horizon] = saved
                continue

        print(f"[{index}/4] {horizon.upper()} preparing data", flush=True)
        target = f"target_{horizon}"
        train = sample_training(split.train, target, config.train_max_rows, config.seed)
        validation = _cap_rows(split.validation, config.calibration_max_rows, config.seed)
        test = (
            _cap_rows(split.test, config.test_max_rows, config.seed)
            if config.test_max_rows is not None
            else split.test.collect()
        )
        if train[target].n_unique() != 2:
            raise ValueError(f"{horizon} train data must contain both classes")
        if validation[target].n_unique() != 2:
            raise ValueError(f"{horizon} validation data must contain both classes")

        x_train, medians = _matrix(train, features)
        x_validation, _ = _matrix(validation, features, medians)
        x_test, _ = _matrix(test, features, medians)
        y_train = train[target].cast(pl.Int8).to_numpy()
        y_validation = validation[target].cast(pl.Int8).to_numpy()
        y_test = test[target].cast(pl.Int8).to_numpy()
        print(
            f"[{index}/4] {horizon.upper()} train={len(y_train):,} "
            f"positive={int(y_train.sum()):,} validation={len(y_validation):,}",
            flush=True,
        )
        model = CatBoostClassifier(
            iterations=config.iterations,
            depth=config.depth,
            learning_rate=config.learning_rate,
            loss_function="Logloss",
            eval_metric="PRAUC",
            auto_class_weights="Balanced",
            task_type=config.task_type.upper(),
            random_seed=config.seed,
            od_type="Iter",
            od_wait=config.early_stopping_rounds,
            allow_writing_files=False,
            verbose=config.progress_interval,
        )
        model.fit(x_train, y_train, eval_set=(x_validation, y_validation))
        model.set_feature_names(features)
        raw_validation = np.asarray(
            model.predict(x_validation, prediction_type="RawFormulaVal")
        )
        fitted = fit_calibration(raw_validation, y_validation)
        raw_test = np.asarray(model.predict(x_test, prediction_type="RawFormulaVal"))
        probabilities = calibrate(raw_test, fitted)
        metrics = _metrics(y_test, probabilities, fitted.threshold)
        temporary_model = model_path.with_suffix(".cbm.tmp")
        model.save_model(temporary_model)
        os.replace(temporary_model, model_path)
        metadata = {
            "horizon": horizon,
            "signature": signature,
            "model_file": model_path.name,
            "features": features,
            "fill_values": medians,
            "calibration": asdict(fitted),
            "metrics": metrics,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        _atomic_json(metadata_path, metadata)
        manifest_horizons[horizon] = metadata
        print(
            f"[{index}/4] {horizon.upper()} saved: {model_path} "
            f"PR-AUC={metrics['pr_auc']:.4f}",
            flush=True,
        )

    assert features is not None
    configuration = _config_payload(config)
    configuration.pop("resume", None)
    model_version = (
        f"catboost-{_signature(config, identity, features, implementation_revision)[:12]}"
    )
    manifest = {
        "artifact_schema_version": "1",
        "model_version": model_version,
        "created_at": datetime.now(UTC).isoformat(),
        "feature_schema_version": "feature-snapshots-v1",
        "label_provider_version": "smvu-proxy-v2",
        "label_source": "proxy",
        "warning": "Metrics reproduce reconstructed proxy labels; they are not confirmed real-fire quality.",
        "training_period": "2019-01-01/2024-12-31",
        "validation_period": "2025-01-01/2025-12-31",
        "test_period": "2026-01-01/2026-12-31",
        "input": identity,
        "implementation_revision": implementation_revision,
        "configuration": configuration,
        "features": features,
        "packages": {
            "catboost": version("catboost"),
            "numpy": version("numpy"),
            "polars": pl.__version__,
            "scikit-learn": version("scikit-learn"),
        },
        "horizons": manifest_horizons,
    }
    manifest_path = output_dir / "manifest.json"
    _atomic_json(manifest_path, manifest)
    _atomic_json(
        output_dir / "metrics.json",
        {
            "model_version": model_version,
            "label_source": "proxy",
            "warning": manifest["warning"],
            "horizons": {
                horizon: manifest_horizons[horizon]["metrics"] for horizon in HORIZONS
            },
        },
    )
    return manifest_path
