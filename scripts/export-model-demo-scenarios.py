#!/usr/bin/env python3
"""Export a small, complete held-out sequence for the model demonstration."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from fire_risk.ml.inference import Predictor, load_predictor


DISTRICTS = ("САО", "ВАО", "ЦАО", "ЮАО")
TECHNICIANS_BY_DISTRICT = {
    "САО": (
        {"id": "tech-ivanov", "name": "Илья Сергеевич Иванов", "role": "Техник"},
        {"id": "tech-petrova", "name": "Мария Андреевна Петрова", "role": "Техник"},
    ),
    "ВАО": (
        {"id": "tech-smirnov", "name": "Павел Олегович Смирнов", "role": "Техник"},
        {"id": "tech-kuznetsova", "name": "Елена Игоревна Кузнецова", "role": "Техник"},
    ),
    "ЦАО": (
        {"id": "tech-sokolov", "name": "Алексей Дмитриевич Соколов", "role": "Техник"},
        {"id": "tech-lebedeva", "name": "Ольга Романовна Лебедева", "role": "Техник"},
    ),
    "ЮАО": (
        {"id": "tech-sokolov", "name": "Алексей Дмитриевич Соколов", "role": "Техник"},
    ),
}
RESPONSE_TEAM = (
    {"id": "response-orlova", "name": "Наталья Викторовна Орлова", "role": "Группа быстрого реагирования"},
    {"id": "response-volkov", "name": "Сергей Павлович Волков", "role": "Группа быстрого реагирования"},
)


def _feature_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    number = float(value)
    return number if math.isfinite(number) else None


def select_balanced_rows(
    rows: Iterable[dict[str, Any]],
    feature_names: list[str],
    predictor: Predictor,
    *,
    count: int = 24,
) -> list[dict[str, Any]]:
    """Choose 50% safe rows and equal BLACK/RED/YELLOW/GREEN risk groups."""
    if count % 8:
        raise ValueError("balanced demo count must be divisible by eight")
    limits = {"safe": count // 2, "black": count // 8, "red": count // 8, "yellow": count // 8, "green": count // 8}
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in limits}
    ordered = sorted(rows, key=lambda row: (row["scoring_timestamp"], str(row["object_id"])))
    for row in ordered:
        features = {name: _feature_value(row.get(name)) for name in feature_names}
        result = predictor.predict(features, top_k=1)
        bucket_name = _risk_bucket(result.decisions)
        if len(buckets[bucket_name]) < limits[bucket_name]:
            buckets[bucket_name].append(row)
        if all(len(buckets[name]) == limit for name, limit in limits.items()):
            break
    missing = [name for name, limit in limits.items() if len(buckets[name]) != limit]
    if missing:
        raise ValueError(f"candidate pool does not contain enough rows for: {', '.join(missing)}")
    return sorted([row for bucket in buckets.values() for row in bucket], key=lambda row: (row["scoring_timestamp"], str(row["object_id"])))


def _risk_bucket(decisions: dict[str, bool]) -> str:
    for horizon, bucket in (("now", "black"), ("6h", "red"), ("12h", "yellow"), ("24h", "green")):
        if decisions.get(horizon):
            return bucket
    return "safe"


def _context_key(object_id: object, timestamp: datetime) -> tuple[str, str]:
    return str(object_id), timestamp.isoformat()


def build_document(
    rows: list[dict[str, Any]],
    feature_names: list[str],
    contexts: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        timestamp: datetime = row["scoring_timestamp"]
        context = contexts.get(_context_key(row["object_id"], timestamp), {})
        sensors = context.get("sensors") or []
        if len(sensors) != 6 or any(not sensor.get("lastSeenAt") for sensor in sensors):
            raise ValueError(f"scenario {index} must contain exactly six sensor readings with timestamps")
        district = context.get("district", _district(str(row["object_id"])))
        employees = _assigned_employees(str(row["object_id"]), district)
        scenarios.append(
            {
                "id": f"held-out-{index:02}",
                "sourceTimestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "objectId": str(row["object_id"]),
                "objectName": context.get("objectName", f"Объект {row['object_id']}"),
                "district": district,
                "dangerousSection": context.get("dangerousSection", "Не определён"),
                "sensors": sensors,
                "assignedEmployees": employees,
                "features": {name: _feature_value(row.get(name)) for name in feature_names},
            }
        )
    return {"featureNames": feature_names, "scenarios": scenarios}


def _district(object_id: str) -> str:
    digest = hashlib.sha256(object_id.encode("utf-8")).digest()[0]
    return DISTRICTS[digest % len(DISTRICTS)]


def _assigned_employees(object_id: str, district: str) -> list[dict[str, str]]:
    digest = hashlib.sha256(object_id.encode("utf-8")).digest()
    technicians = TECHNICIANS_BY_DISTRICT[district]
    technician = technicians[digest[1] % len(technicians)]
    response = RESPONSE_TEAM[digest[2] % len(RESPONSE_TEAM)]
    return [dict(technician), dict(response)]


def _candidate_rows(path: Path, feature_names: list[str]) -> list[dict[str, Any]]:
    scan = pl.scan_parquet(path).filter(pl.col("scoring_timestamp").dt.year() == 2026)
    columns = ["object_id", "scoring_timestamp", *feature_names]
    risky = (
        scan.filter(
            (pl.col("alarm_count_5m") > 0)
            | (pl.col("malfunction_count_5m") > 0)
            | pl.col("smoke_heat_5m")
            | (pl.col("gas_alarm_count_5m") > 0)
        )
        .select(columns)
        .sort(["scoring_timestamp", "object_id"])
        .head(600)
        .collect()
    )
    normal = (
        scan.filter(
            (pl.col("alarm_count_24h") == 0)
            & (pl.col("malfunction_count_24h") == 0)
            & (~pl.col("smoke_heat_24h"))
        )
        .select(columns)
        .sort(["scoring_timestamp", "object_id"])
        .head(600)
        .collect()
    )
    return pl.concat([normal, risky]).unique(["object_id", "scoring_timestamp"]).to_dicts()


def _display_value(event: dict[str, Any]) -> str:
    raw = str(event.get("raw_value") or "").strip()
    if raw:
        return raw
    numeric = event.get("numeric_value")
    if numeric is not None:
        return f"{float(numeric):.2f}"
    return str(event.get("state_code") or "Нет значения")


def _event_contexts(events_path: Path, rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    import pyarrow.dataset as ds

    columns = [
        "object_id", "registered_at", "channel_id", "sensor_name", "sensor_type",
        "object_name", "raw_value", "numeric_value", "state_code", "alarm_flag",
        "value_kind", "picket_raw", "picket_sort_key",
    ]
    cutoffs_by_object: dict[str, list[tuple[int, datetime]]] = {}
    for index, row in enumerate(rows):
        cutoffs_by_object.setdefault(str(row["object_id"]), []).append((index, row["scoring_timestamp"]))
    cutoffs = pl.DataFrame({
        "_scenario_index": list(range(len(rows))),
        "object_id": [str(row["object_id"]) for row in rows],
        "_source_timestamp": [row["scoring_timestamp"] for row in rows],
    })
    latest_by_scenario: list[dict[str, dict[str, Any]]] = [{} for _ in rows]
    dataset = ds.dataset(events_path, format="parquet")
    object_ids = list(cutoffs_by_object)
    maximum_timestamp = max(row["scoring_timestamp"] for row in rows)
    scanner = dataset.scanner(
        columns=columns,
        filter=ds.field("object_id").isin(object_ids) & (ds.field("registered_at") <= maximum_timestamp),
        batch_size=65_536,
    )
    for batch in scanner.to_batches():
        frame = pl.from_arrow(batch)
        if frame.is_empty():
            continue
        batch_latest = (
            frame.join(cutoffs, on="object_id", how="inner")
            .filter(pl.col("registered_at") <= pl.col("_source_timestamp"))
            .sort(["_scenario_index", "channel_id", "registered_at"])
            .group_by(["_scenario_index", "channel_id"], maintain_order=True)
            .last()
        )
        for event in batch_latest.to_dicts():
            event_timestamp = event["registered_at"]
            scenario_index = event["_scenario_index"]
            channel_id = str(event["channel_id"])
            current = latest_by_scenario[scenario_index].get(channel_id)
            if current is None or current["registered_at"] < event_timestamp:
                latest_by_scenario[scenario_index][channel_id] = event
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    fire_words = ("дым", "температур", "тепл", "газ", "пожар", "ручн")
    for scenario_index, row in enumerate(rows):
        timestamp: datetime = row["scoring_timestamp"]
        matching = list(latest_by_scenario[scenario_index].values())
        chosen = sorted(matching, key=lambda item: (
            not bool(item.get("alarm_flag")),
            str(item.get("value_kind") or "") != "malfunction",
            not any(word in str(item.get("sensor_type") or "").lower() for word in fire_words),
            item.get("picket_sort_key") or 0,
        ))[:6]
        sensors = [
            {
                "id": str(event["channel_id"]),
                "name": str(event.get("sensor_name") or event["channel_id"]),
                "sensorType": str(event.get("sensor_type") or "Датчик"),
                "picket": event.get("picket_raw"),
                "value": _display_value(event),
                "state": (
                    "danger" if event.get("alarm_flag")
                    else "malfunction" if event.get("value_kind") == "malfunction"
                    else "warning" if timestamp - event["registered_at"] > timedelta(hours=24)
                    else "normal"
                ),
                "lastSeenAt": event["registered_at"].isoformat(),
            }
            for event in chosen
        ]
        first = chosen[0] if chosen else None
        district = _district(str(row["object_id"]))
        contexts[_context_key(row["object_id"], timestamp)] = {
            "objectName": str(first.get("object_name") if first else f"Объект {row['object_id']}"),
            "district": district,
            "dangerousSection": str(first["picket_raw"]) if first and first.get("picket_raw") else "Не определён",
            "sensors": sensors,
            "assignedEmployees": _assigned_employees(str(row["object_id"]), district),
        }
    return contexts


def export_catalog(snapshots: Path, events: Path, inventory: Path, model_dir: Path, output: Path) -> None:
    if not inventory.exists():
        raise FileNotFoundError(inventory)
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    feature_names = [str(name) for name in manifest["features"]]
    predictor = load_predictor(model_dir)
    eligible_objects = set(
        pl.read_parquet(inventory)
        .filter(
            (pl.col("inventory_channel_count") >= 6)
            & (
                pl.col("inventory_smoke_channel_count")
                + pl.col("inventory_heat_channel_count")
                + pl.col("inventory_gas_channel_count")
                + pl.col("inventory_manual_channel_count")
                > 0
            )
        )
        .get_column("object_id")
        .cast(pl.String)
        .to_list()
    )
    candidates = [row for row in _candidate_rows(snapshots, feature_names) if str(row["object_id"]) in eligible_objects]
    selected = select_balanced_rows(candidates, feature_names, predictor)
    document = build_document(selected, feature_names, _event_contexts(events, selected))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_catalog(args.snapshots, args.events, args.inventory, args.model_dir, args.output)


if __name__ == "__main__":
    main()
