"""Stable Python inference contract for saved fire-risk artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from catboost import CatBoostClassifier, Pool  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from fire_risk.ml.training import HORIZONS, Calibration, calibrate, enforce_monotonic


class Factor(BaseModel):
    horizon: str
    feature: str
    value: float
    contribution: float


class Prediction(BaseModel):
    model_version: str
    calculated_at: datetime
    p_now: float = Field(ge=0.0, le=1.0)
    p_6h: float = Field(ge=0.0, le=1.0)
    p_12h: float = Field(ge=0.0, le=1.0)
    p_24h: float = Field(ge=0.0, le=1.0)
    decisions: dict[str, bool]
    factors: list[Factor]


class Predictor:
    def __init__(self, artifact_dir: Path, manifest: dict[str, Any]) -> None:
        self.artifact_dir = artifact_dir
        self.manifest = manifest
        self.features = [str(name) for name in manifest["features"]]
        self.metadata: dict[str, dict[str, Any]] = manifest["horizons"]
        self.models: dict[str, CatBoostClassifier] = {}
        for horizon in HORIZONS:
            model = CatBoostClassifier()
            model.load_model(artifact_dir / str(self.metadata[horizon]["model_file"]))
            self.models[horizon] = model

    def predict(self, features: dict[str, float | int | bool | None], top_k: int = 5) -> Prediction:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        raw_probabilities: dict[str, np.ndarray] = {}
        factors: list[Factor] = []
        for horizon in HORIZONS:
            metadata = self.metadata[horizon]
            fill_values: dict[str, float] = metadata["fill_values"]

            resolved: list[float] = []
            for name in self.features:
                value = features.get(name)
                resolved.append(fill_values[name] if value is None else float(value))
            values = np.asarray(resolved, dtype=np.float32)
            pool = Pool(values.reshape(1, -1), feature_names=self.features)
            raw_score = np.asarray(
                self.models[horizon].predict(pool, prediction_type="RawFormulaVal")
            )
            calibration = Calibration(**metadata["calibration"])
            raw_probabilities[horizon] = calibrate(raw_score, calibration)
            contributions = np.asarray(
                self.models[horizon].get_feature_importance(pool, type="ShapValues")
            )[0, :-1]
            ranked = np.argsort(np.abs(contributions))[::-1][:top_k]
            factors.extend(
                Factor(
                    horizon=horizon,
                    feature=self.features[index],
                    value=float(values[index]),
                    contribution=float(contributions[index]),
                )
                for index in ranked
            )
        probabilities = enforce_monotonic(raw_probabilities)
        scalar = {name: float(probabilities[name][0]) for name in HORIZONS}
        decisions = {
            name: scalar[name]
            >= float(self.metadata[name]["calibration"]["threshold"])
            for name in HORIZONS
        }
        return Prediction(
            model_version=str(self.manifest["model_version"]),
            calculated_at=datetime.now(UTC),
            p_now=scalar["now"],
            p_6h=scalar["6h"],
            p_12h=scalar["12h"],
            p_24h=scalar["24h"],
            decisions=decisions,
            factors=factors,
        )


def load_predictor(path: str | Path) -> Predictor:
    """Load a manifest path or an artifact directory."""
    candidate = Path(path)
    manifest_path = candidate / "manifest.json" if candidate.is_dir() else candidate
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_schema_version") != "1":
        raise ValueError("unsupported artifact schema")
    return Predictor(manifest_path.parent, manifest)
