"""Event-level evaluation for a trained proxy-label artifact."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from catboost import CatBoostClassifier  # type: ignore[import-untyped]

from fire_risk.ml.data import split_frame
from fire_risk.ml.training import (
    HORIZONS,
    Calibration,
    _atomic_json,
    _matrix,
    calibrate,
)


def event_metrics(rows: pl.DataFrame) -> dict[str, int | float | None]:
    """Aggregate alerts to proxy incidents and false-alert object-days."""
    event_ids = rows.filter(pl.col("target") & pl.col("episode_group_id").is_not_null())[
        "episode_group_id"
    ].unique()
    detected = rows.filter(
        pl.col("target") & pl.col("alert") & pl.col("episode_group_id").is_not_null()
    )["episode_group_id"].unique()
    false_days = (
        rows.filter(pl.col("alert") & ~pl.col("target"))
        .select(
            "object_id",
            pl.col("scoring_timestamp")
            .dt.convert_time_zone("Europe/Moscow")
            .dt.date()
            .alias("date"),
        )
        .unique()
        .height
    )
    object_days = (
        rows.select(
            "object_id",
            pl.col("scoring_timestamp")
            .dt.convert_time_zone("Europe/Moscow")
            .dt.date()
            .alias("date"),
        )
        .unique()
        .height
    )
    true_positive = detected.len()
    event_count = event_ids.len()
    precision = true_positive / (true_positive + false_days) if true_positive + false_days else 0.0
    recall = true_positive / event_count if event_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    starts = (
        rows.filter(pl.col("target_now") & pl.col("episode_group_id").is_not_null())
        .group_by("episode_group_id")
        .agg(pl.col("scoring_timestamp").min().alias("started_at"))
    )
    first_alerts = (
        rows.filter(
            pl.col("target") & pl.col("alert") & pl.col("episode_group_id").is_not_null()
        )
        .group_by("episode_group_id")
        .agg(pl.col("scoring_timestamp").min().alias("alerted_at"))
    )
    lead_hours = (
        first_alerts.join(starts, on="episode_group_id", how="inner")
        .select(
            (
                (pl.col("started_at") - pl.col("alerted_at")).dt.total_seconds() / 3600
            )
            .clip(lower_bound=0)
            .alias("lead_hours")
        )["lead_hours"]
        .to_list()
    )
    return {
        "events": event_count,
        "detected_events": true_positive,
        "false_alert_object_days": false_days,
        "evaluated_object_days": object_days,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_alerts_per_object_day": false_days / object_days if object_days else 0.0,
        "median_lead_time_hours": float(np.median(lead_hours)) if lead_hours else None,
    }


def evaluate_artifact(input_path: Path, artifact_dir: Path) -> Path:
    """Evaluate all horizons on the common, fully observed 2026 cohort."""
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    split = split_frame(pl.scan_parquet(input_path), "24h")
    frame = split.test.collect()
    probabilities: dict[str, np.ndarray] = {}
    for horizon in HORIZONS:
        metadata = manifest["horizons"][horizon]
        model = CatBoostClassifier()
        model.load_model(artifact_dir / metadata["model_file"])
        matrix, _ = _matrix(frame, metadata["features"], metadata["fill_values"])
        raw = np.asarray(model.predict(matrix, prediction_type="RawFormulaVal"))
        probabilities[horizon] = calibrate(raw, Calibration(**metadata["calibration"]))

    probabilities["12h"] = np.maximum(probabilities["6h"], probabilities["12h"])
    probabilities["24h"] = np.maximum(probabilities["12h"], probabilities["24h"])
    reports: dict[str, Any] = {}
    base = frame.select(
        "object_id", "scoring_timestamp", "episode_group_id", "target_now"
    )
    for horizon in HORIZONS:
        threshold = manifest["horizons"][horizon]["calibration"]["threshold"]
        rows = base.with_columns(
            frame[f"target_{horizon}"].alias("target"),
            pl.Series("alert", probabilities[horizon] >= threshold),
        )
        reports[horizon] = event_metrics(rows)

    payload = {
        "model_version": manifest["model_version"],
        "created_at": datetime.now(UTC).isoformat(),
        "label_source": "proxy",
        "warning": "Proxy-label reproduction, not confirmed real-fire detection quality.",
        "cohort": "Common fully observed 2026 test rows (target_24h_available).",
        "alert_unit": "One false alert per object per Moscow calendar day.",
        "horizons": reports,
    }
    output = artifact_dir / "event_metrics.json"
    _atomic_json(output, payload)
    return output
