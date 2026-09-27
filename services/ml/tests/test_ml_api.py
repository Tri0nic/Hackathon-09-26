import fire_risk.ml_api as ml_api
from fire_risk.ml_api import parse_prediction_request


def test_prediction_request_accepts_dotnet_camel_case() -> None:
    features, top_k = parse_prediction_request({"features": {"x": 1.5}, "topK": 3})

    assert features == {"x": 1.5}
    assert top_k == 3


def test_model_summary_exposes_selected_artifact_and_real_now_metrics() -> None:
    manifest = {
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

    assert ml_api.model_summary(manifest) == {
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
