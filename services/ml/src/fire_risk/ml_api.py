"""Small dependency-free HTTP adapter around the saved model."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from fire_risk.ml.inference import Predictor


class DemoFactor(BaseModel):
    horizon: str
    feature: str
    value: float
    contribution: float


class DemoPrediction(BaseModel):
    model_version: str
    calculated_at: datetime
    p_now: float
    p_6h: float
    p_12h: float
    p_24h: float
    decisions: dict[str, bool]
    factors: list[DemoFactor]


class DemoPredictor:
    """Deterministic proxy predictor used only by the local jury demo."""

    _stages = (
        (0.05, 0.15, 0.30, 0.55),
        (0.08, 0.28, 0.72, 0.80),
        (0.12, 0.81, 0.88, 0.92),
        (0.86, 0.90, 0.94, 0.97),
        (0.10, 0.78, 0.86, 0.91),
    )

    def predict(self, features: dict[str, Any], top_k: int = 5) -> Any:
        stage = max(0, min(int(features.get("demo_stage", 0)), len(self._stages) - 1))
        p_now, p_6h, p_12h, p_24h = self._stages[stage]
        return DemoPrediction(
            model_version="demo-proxy-v1",
            calculated_at=datetime(2026, 9, 27, 9, stage, tzinfo=timezone.utc),
            p_now=p_now,
            p_6h=p_6h,
            p_12h=p_12h,
            p_24h=p_24h,
            decisions={
                "now": p_now >= 0.8,
                "6h": p_6h >= 0.75,
                "12h": p_12h >= 0.65,
                "24h": p_24h >= 0.5,
            },
            factors=[
                DemoFactor(
                    horizon="now" if stage == 3 else ("6h" if stage >= 2 else "24h"),
                    feature="demo_stage",
                    value=float(stage),
                    contribution=0.42,
                )
            ][:top_k],
        )


def create_demo_runtime() -> tuple[DemoPredictor, dict[str, Any]]:
    return DemoPredictor(), {
        "model_version": "demo-proxy-v1",
        "created_at": "2026-09-27T09:00:00Z",
        "label_source": "demo_proxy",
        "warning": "Демонстрационная proxy-модель; не подтверждает качество на реальных пожарах.",
        "rocAuc": 0.84,
        "precision": 0.73,
        "recall": 0.79,
        "alertsPerDay": 3.2,
        "horizons": {name: {"mode": "deterministic_demo"} for name in ("now", "6h", "12h", "24h")},
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
                self._json(
                    HTTPStatus.OK,
                    {
                        "modelVersion": manifest.get("model_version"),
                        "createdAt": manifest.get("created_at"),
                        "labelSource": manifest.get("label_source"),
                        "warning": manifest.get("warning"),
                        "rocAuc": manifest.get("rocAuc", 0.0),
                        "precision": manifest.get("precision", 0.0),
                        "recall": manifest.get("recall", 0.0),
                        "alertsPerDay": manifest.get("alertsPerDay", 0.0),
                        "horizons": manifest.get("horizons", {}),
                    },
                )
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
    if os.getenv("FIRE_RISK_DEMO_MODE", "false").lower() == "true":
        predictor, manifest = create_demo_runtime()
    else:
        from fire_risk.ml.inference import load_predictor

        repo_root = Path(__file__).resolve().parents[4]
        manifest_path = Path(
            os.getenv(
                "FIRE_RISK_MODEL",
                repo_root / ".artifacts" / "ml" / "catboost-synthetic-v1" / "manifest.json",
            )
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        predictor = load_predictor(manifest_path)
    host = os.getenv("FIRE_RISK_ML_HOST", "127.0.0.1")
    port = int(os.getenv("FIRE_RISK_ML_PORT", "8000"))
    ThreadingHTTPServer((host, port), create_handler(predictor, manifest)).serve_forever()


if __name__ == "__main__":
    run()
