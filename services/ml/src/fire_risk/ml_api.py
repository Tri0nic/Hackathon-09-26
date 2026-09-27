"""Small dependency-free HTTP adapter around the saved model."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    features = payload.get("features")
    if not isinstance(features, dict):
        raise ValueError("features must be an object")
    top_k = int(payload.get("topK", payload.get("top_k", 5)))
    if top_k <= 0:
        raise ValueError("topK must be positive")
    return features, top_k


def create_handler(predictor: "Predictor", manifest: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
            elif self.path == "/ml/models/current":
                self._json(HTTPStatus.OK, model_summary(manifest))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/ml/predict":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                features, top_k = parse_prediction_request(payload)
                result = predictor.predict(features, top_k=top_k)
                self._json(HTTPStatus.OK, result.model_dump(mode="json"))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception as error:  # model errors are reported without stopping the server
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def run() -> None:
    from fire_risk.ml.inference import load_predictor

    manifest_path = Path(
        os.getenv(
            "FIRE_RISK_MODEL",
            "/app/model/catboost-synthetic-v1/manifest.json",
        )
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    predictor = load_predictor(manifest_path)
    host = os.getenv("FIRE_RISK_ML_HOST", "127.0.0.1")
    port = int(os.getenv("FIRE_RISK_ML_PORT", "8000"))
    ThreadingHTTPServer((host, port), create_handler(predictor, manifest)).serve_forever()


if __name__ == "__main__":
    run()
