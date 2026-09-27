import fire_risk.ml_api as ml_api
from fire_risk.ml_api import parse_prediction_request


def test_prediction_request_accepts_dotnet_camel_case() -> None:
    features, top_k = parse_prediction_request({"features": {"x": 1.5}, "topK": 3})

    assert features == {"x": 1.5}
    assert top_k == 3


def test_demo_runtime_is_deterministic_and_marks_proxy_source() -> None:
    predictor, manifest = ml_api.create_demo_runtime()

    first = predictor.predict({"demo_stage": 3.0}, top_k=3)
    second = predictor.predict({"demo_stage": 3.0}, top_k=3)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.decisions == {"now": True, "6h": True, "12h": True, "24h": True}
    assert manifest["label_source"] == "demo_proxy"
