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
    """Choose equal safe/dangerous rows and return them in source-time order."""
    safe: list[dict[str, Any]] = []
    dangerous: list[dict[str, Any]] = []
    safe_limit = count // 2
    dangerous_limit = count - safe_limit
    ordered = sorted(rows, key=lambda row: (row["scoring_timestamp"], str(row["object_id"])))
    for row in ordered:
        features = {name: _feature_value(row.get(name)) for name in feature_names}
        result = predictor.predict(features, top_k=1)
        bucket = dangerous if any(result.decisions.values()) else safe
        limit = dangerous_limit if bucket is dangerous else safe_limit
        if len(bucket) < limit:
            bucket.append(row)
        if len(safe) == safe_limit and len(dangerous) == dangerous_limit:
            break
    if len(safe) != safe_limit or len(dangerous) != dangerous_limit:
        raise ValueError("candidate pool does not contain enough safe and dangerous rows")
    return sorted([*safe, *dangerous], key=lambda row: (row["scoring_timestamp"], str(row["object_id"])))


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
        sensors = context.get("sensors") or [
            {
                "id": f"summary-{index:02}",
                "name": "Сводные показания объекта",
                "sensorType": "Сводный канал",
                "picket": None,
                "value": "Исторический срез",
                "state": "normal",
            }
        ]
        scenarios.append(
            {
                "id": f"held-out-{index:02}",
                "sourceTimestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "objectId": str(row["object_id"]),
                "objectName": context.get("objectName", f"Объект {row['object_id']}"),
                "district": context.get("district", _district(str(row["object_id"]))),
                "dangerousSection": context.get("dangerousSection", "Не определён"),
                "sensors": sensors,
                "features": {name: _feature_value(row.get(name)) for name in feature_names},
            }
        )
    return {"featureNames": feature_names, "scenarios": scenarios}


def _district(object_id: str) -> str:
    digest = hashlib.sha256(object_id.encode("utf-8")).digest()[0]
    return DISTRICTS[digest % len(DISTRICTS)]


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
    predicate = pl.lit(False)
    for row in rows:
        timestamp: datetime = row["scoring_timestamp"]
        predicate = predicate | (
            (pl.col("object_id") == str(row["object_id"]))
            & (pl.col("registered_at") > timestamp - timedelta(minutes=30))
            & (pl.col("registered_at") <= timestamp)
        )
    columns = [
        "object_id", "registered_at", "channel_id", "sensor_name", "sensor_type",
        "object_name", "raw_value", "numeric_value", "state_code", "alarm_flag",
        "picket_raw", "picket_sort_key",
    ]
    nearby = pl.scan_parquet(events_path).filter(predicate).select(columns).collect().to_dicts()
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        timestamp: datetime = row["scoring_timestamp"]
        matching = [
            event for event in nearby
            if str(event["object_id"]) == str(row["object_id"])
            and timestamp - timedelta(minutes=30) < event["registered_at"] <= timestamp
        ]
        latest: dict[str, dict[str, Any]] = {}
        for event in sorted(matching, key=lambda item: item["registered_at"]):
            latest[str(event["channel_id"])] = event
        chosen = sorted(latest.values(), key=lambda item: (not bool(item.get("alarm_flag")), item.get("picket_sort_key") or 0))[:6]
        sensors = [
            {
                "id": str(event["channel_id"]),
                "name": str(event.get("sensor_name") or event["channel_id"]),
                "sensorType": str(event.get("sensor_type") or "Датчик"),
                "picket": event.get("picket_raw"),
                "value": _display_value(event),
                "state": "danger" if event.get("alarm_flag") else (str(event.get("state_code") or "normal").lower()),
            }
            for event in chosen
        ]
        first = chosen[0] if chosen else None
        contexts[_context_key(row["object_id"], timestamp)] = {
            "objectName": str(first.get("object_name") if first else f"Объект {row['object_id']}"),
            "district": _district(str(row["object_id"])),
            "dangerousSection": f"ПК {first['picket_raw']}" if first and first.get("picket_raw") else "Не определён",
            "sensors": sensors,
        }
    return contexts


def export_catalog(snapshots: Path, events: Path, inventory: Path, model_dir: Path, output: Path) -> None:
    if not inventory.exists():
        raise FileNotFoundError(inventory)
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    feature_names = [str(name) for name in manifest["features"]]
    predictor = load_predictor(model_dir)
    selected = select_balanced_rows(_candidate_rows(snapshots, feature_names), feature_names, predictor)
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
