from datetime import UTC, datetime

from fastapi.testclient import TestClient

import fire_risk.ml_api as ml_api
from fire_risk.ml_api import parse_prediction_request


class FakeResult:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "model_version": "model-v1",
            "calculated_at": datetime(2026, 9, 29, 9, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
            "p_now": 0.1,
            "p_6h": 0.4,
            "p_12h": 0.6,
            "p_24h": 0.8,
            "decisions": {"now": False, "6h": True, "12h": True, "24h": True},
            "factors": [],
        }


class FakePredictor:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], int]] = []

    def predict(self, features: dict[str, object], top_k: int = 5) -> FakeResult:
        self.calls.append((features, top_k))
        return FakeResult()


def manifest() -> dict[str, object]:
    return {
        "model_version": "model-v1",
        "created_at": "2026-09-26T18:51:08Z",
        "label_source": "held_out_proxy",
        "warning": "Proxy labels",
        "horizons": {"now": {"metrics": {"roc_auc": 0.9, "precision": 0.8, "recall": 0.7}}},
    }


def test_prediction_request_accepts_dotnet_camel_case() -> None:
    features, top_k = parse_prediction_request({"features": {"x": 1.5}, "topK": 3})

    assert features == {"x": 1.5}
    assert top_k == 3


def test_model_summary_exposes_selected_artifact_and_real_now_metrics() -> None:
    source_manifest = {
        "model_version": "catboost-e87d5604945b",
        "created_at": "2026-09-26T18:51:08Z",
        "label_source": "synthetic_customer_requested",
        "warning": "Synthetic demo-label reproduction, not real-fire quality.",
        "horizons": {
            "now": {
                "metrics": {
                    "roc_auc": 0.987,
                    "precision": 0.812,
                    "recall": 0.704,
                }
            }
        },
    }

    assert ml_api.model_summary(source_manifest) == {
        "modelVersion": "catboost-e87d5604945b",
        "artifact": "catboost-synthetic-v1",
        "createdAt": "2026-09-26T18:51:08Z",
        "labelSource": "synthetic_customer_requested",
        "warning": "Synthetic demo-label reproduction, not real-fire quality.",
        "rocAuc": 0.987,
        "precision": 0.812,
        "recall": 0.704,
        "alertsPerDay": 0.0,
        "horizons": {
            "now": {
                "roc_auc": 0.987,
                "precision": 0.812,
                "recall": 0.704,
            }
        },
    }


def test_health() -> None:
    response = TestClient(ml_api.create_app(FakePredictor(), manifest())).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_model_summary() -> None:
    response = TestClient(ml_api.create_app(FakePredictor(), manifest())).get("/ml/models/current")

    assert response.status_code == 200
    assert response.json()["modelVersion"] == "model-v1"
    assert response.json()["rocAuc"] == 0.9


def test_predict_accepts_top_k_spellings() -> None:
    predictor = FakePredictor()
    client = TestClient(ml_api.create_app(predictor, manifest()))

    camel = client.post("/ml/predict", json={"features": {"x": 1.5}, "topK": 3})
    snake = client.post("/ml/predict", json={"features": {"x": 2.5}, "top_k": 4})

    assert camel.status_code == 200
    assert snake.status_code == 200
    assert predictor.calls == [({"x": 1.5}, 3), ({"x": 2.5}, 4)]
    assert camel.json()["model_version"] == "model-v1"


def test_predict_rejects_invalid_body() -> None:
    client = TestClient(ml_api.create_app(FakePredictor(), manifest()))

    missing = client.post("/ml/predict", json={"topK": 3})
    non_positive = client.post("/ml/predict", json={"features": {}, "topK": 0})

    assert missing.status_code == 422
    assert non_positive.status_code == 422
    assert missing.json()["detail"]


def test_openapi_and_docs() -> None:
    client = TestClient(ml_api.create_app(FakePredictor(), manifest()))

    schema = client.get("/openapi.json")
    docs = client.get("/docs")

    assert schema.status_code == 200
    assert {"/health", "/ml/models/current", "/ml/predict"} <= set(schema.json()["paths"])
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]
