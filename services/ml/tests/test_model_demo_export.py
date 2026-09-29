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
        level = int(features["signal"])
        return SimpleNamespace(decisions={
            "now": level == 4,
            "6h": level == 3,
            "12h": level == 2,
            "24h": level == 1,
        })


def test_balanced_selection_is_stable_and_does_not_export_model_outputs() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {
            "object_id": f"object-{index:02}",
            "scoring_timestamp": start + timedelta(hours=index),
            "signal": float(0 if index < 12 else 1 + (index - 12) // 3),
        }
        for index in range(24)
    ]

    selected = MODULE.select_balanced_rows(rows, ["signal"], FakePredictor(), count=24)
    contexts = {
        (row["object_id"], row["scoring_timestamp"].isoformat()): {
            "assignedEmployees": [
                {"id": f"employee-{row['object_id']}", "name": "Илья Сергеевич Иванов", "role": "Техник"}
            ],
            "sensors": [
                {
                    "id": f"sensor-{sensor}",
                    "name": f"Датчик {sensor}",
                    "sensorType": "Датчик дыма",
                    "picket": f"ПК {sensor}",
                    "value": "Норма",
                    "state": "normal",
                    "lastSeenAt": (row["scoring_timestamp"] - timedelta(minutes=sensor)).isoformat(),
                }
                for sensor in range(1, 7)
            ]
        }
        for row in selected
    }
    document = MODULE.build_document(selected, ["signal"], contexts)

    assert len(selected) == 24
    assert [sum(row["signal"] == level for row in selected) for level in range(5)] == [12, 3, 3, 3, 3]
    assert [row["scoring_timestamp"] for row in selected] == sorted(row["scoring_timestamp"] for row in selected)
    assert all(len(scenario["sensors"]) == 6 for scenario in document["scenarios"])
    assert all(sensor["lastSeenAt"] for scenario in document["scenarios"] for sensor in scenario["sensors"])
    assert all(len(scenario["assignedEmployees"]) == 2 for scenario in document["scenarios"])
    assert all({employee["role"] for employee in scenario["assignedEmployees"]} == {"Техник", "Группа быстрого реагирования"} for scenario in document["scenarios"])
    serialized = str(document).lower()
    assert "probability" not in serialized
    assert "decisions" not in serialized
    assert document["featureNames"] == ["signal"]


def test_event_context_uses_latest_past_readings_and_exposes_status_and_time(tmp_path: Path) -> None:
    import polars as pl

    timestamp = datetime(2026, 1, 3, 12, tzinfo=UTC)
    rows = [{"object_id": "object-1", "scoring_timestamp": timestamp}]
    events = []
    sensor_types = [
        "Датчик дыма",
        "Датчик температуры",
        "Газовый датчик",
        "Ручной извещатель",
        "Состояние насоса",
        "Диагностика",
    ]
    for index, sensor_type in enumerate(sensor_types, 1):
        events.append({
            "object_id": "object-1",
            "registered_at": timestamp - (timedelta(days=2) if index == 1 else timedelta(minutes=index * 10)),
            "channel_id": str(index),
            "sensor_name": f"Датчик {index}",
            "sensor_type": sensor_type,
            "object_name": "Объект 1",
            "raw_value": "Неисправность" if index == 2 else f"Значение {index}",
            "numeric_value": None,
            "state_code": "Выключен" if index == 5 else "Норма",
            "alarm_flag": index == 3,
            "value_kind": "malfunction" if index == 2 else "known_state",
            "picket_raw": f"ПК {index}",
            "picket_sort_key": float(index),
        })
    events.append({**events[0], "registered_at": timestamp + timedelta(minutes=1), "raw_value": "Будущее", "alarm_flag": True})
    path = tmp_path / "events.parquet"
    pl.DataFrame(events).write_parquet(path)

    contexts = MODULE._event_contexts(path, rows)
    sensors = contexts[("object-1", timestamp.isoformat())]["sensors"]

    assert len(sensors) == 6
    assert next(sensor for sensor in sensors if sensor["id"] == "1")["value"] == "Значение 1"
    assert next(sensor for sensor in sensors if sensor["id"] == "1")["state"] == "warning"
    assert next(sensor for sensor in sensors if sensor["id"] == "2")["state"] == "malfunction"
    assert next(sensor for sensor in sensors if sensor["id"] == "3")["state"] == "danger"
    assert all(sensor["lastSeenAt"] <= timestamp.isoformat() for sensor in sensors)


def test_document_rejects_scenarios_without_six_real_sensors() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [{"object_id": "object-1", "scoring_timestamp": timestamp, "signal": 0.0}]

    try:
        MODULE.build_document(rows, ["signal"], {})
    except ValueError as error:
        assert "six sensor readings" in str(error)
    else:
        raise AssertionError("scenario without six sensors must be rejected")
