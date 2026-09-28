"""FastAPI adapter around the saved model."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import AliasChoices, BaseModel, Field

if TYPE_CHECKING:
    from fire_risk.ml.inference import Predictor


def model_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    horizons = manifest.get("horizons", {})
    now_metrics = horizons.get("now", {}).get("metrics", {})
    return {
        "modelVersion": manifest.get("model_version"),
        "artifact": "catboost-synthetic-v1",
        "createdAt": manifest.get("created_at"),
        "labelSource": manifest.get("label_source"),
        "warning": manifest.get("warning"),
        "rocAuc": now_metrics.get("roc_auc", 0.0),
        "precision": now_metrics.get("precision", 0.0),
        "recall": now_metrics.get("recall", 0.0),
        "alertsPerDay": 0.0,
        "horizons": {
            name: metadata.get("metrics", {})
            for name, metadata in horizons.items()
        },
    }


def parse_prediction_request(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    request = PredictionRequest.model_validate(payload)
    return request.features, request.top_k


class PredictionRequest(BaseModel):
    features: dict[str, float | int | bool | None]
    top_k: int = Field(
        default=5,
        gt=0,
        validation_alias=AliasChoices("topK", "top_k"),
        serialization_alias="topK",
    )


def create_app(predictor: "Predictor", manifest: dict[str, Any]) -> FastAPI:
    app = FastAPI(title="Fire Risk ML API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ml/models/current")
    def current_model() -> dict[str, Any]:
        return model_summary(manifest)

    @app.post("/ml/predict")
    def predict(request: PredictionRequest) -> dict[str, Any]:
        try:
            result = predictor.predict(request.features, top_k=request.top_k)
            return result.model_dump(mode="json")
        except Exception as error:  # model errors must not stop the service
            raise HTTPException(status_code=500, detail=str(error)) from error

    return app


def create_runtime_app() -> FastAPI:
    from fire_risk.ml.inference import load_predictor

    manifest_path = Path(
        os.getenv("FIRE_RISK_MODEL", "/app/model/catboost-synthetic-v1/manifest.json")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return create_app(load_predictor(manifest_path), manifest)


def main() -> None:
    host = os.getenv("FIRE_RISK_ML_HOST", "127.0.0.1")
    port = int(os.getenv("FIRE_RISK_ML_PORT", "8000"))
    uvicorn.run(create_runtime_app(), host=host, port=port)


run = main


if __name__ == "__main__":
    main()
