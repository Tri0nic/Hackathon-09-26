from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[3] / "scripts" / "export-model-demo-scenarios.py"
SPEC = importlib.util.spec_from_file_location("model_demo_export", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakePredictor:
    def predict(self, features: dict[str, float], top_k: int = 5) -> SimpleNamespace:
        dangerous = features["signal"] >= 10
        return SimpleNamespace(decisions={"now": dangerous, "6h": False, "12h": False, "24h": False})


def test_balanced_selection_is_stable_and_does_not_export_model_outputs() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {"object_id": f"object-{index}", "scoring_timestamp": start + timedelta(hours=index), "signal": float(index)}
        for index in range(20)
    ]

    selected = MODULE.select_balanced_rows(rows, ["signal"], FakePredictor(), count=6)
    document = MODULE.build_document(selected, ["signal"], {})

    assert len(selected) == 6
    assert sum(row["signal"] >= 10 for row in selected) == 3
    assert [row["scoring_timestamp"] for row in selected] == sorted(row["scoring_timestamp"] for row in selected)
    serialized = str(document).lower()
    assert "probability" not in serialized
    assert "decisions" not in serialized
    assert document["featureNames"] == ["signal"]
