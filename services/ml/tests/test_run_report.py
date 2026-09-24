"""Auditable proxy composition, censored target counts, and feature overlap."""

import json
from datetime import UTC, datetime

import polars as pl

from fire_risk.contracts import IncidentLabel
from fire_risk.data import run_report


def _labels() -> list[IncidentLabel]:
    return [
        IncidentLabel.model_validate(
            {
                "incident_id": str(index),
                "object_id": object_id,
                "started_at": datetime(year, 1, 1, tzinfo=UTC),
                "incident_type": "fire pattern",
                "decision": "unknown",
                "source": "proxy",
                "confidence": 0.5,
                "rule_version": "smvu-proxy-v2",
                "rule_id": rule_id,
                "sensor_combination": sensors,
            }
        )
        for index, (year, object_id, rule_id, sensors) in enumerate(
            [
                (2026, "b", "smoke_heat", ["smoke", "heat"]),
                (2025, "a", "smoke_heat", ["heat", "smoke"]),
                (2026, "b", "smoke_supporting_pump", ["smoke", "pump"]),
            ]
        )
    ]


def _targets() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "target_now_available": [True, True, True, True],
            "target_now": [False, False, False, False],
            "target_6h_available": [True, True, True, False],
            "target_6h": [True, False, False, None],
            "target_12h_available": [True, True, False, False],
            "target_12h": [True, False, None, None],
            "target_24h_available": [True, False, False, False],
            "target_24h": [True, None, None, None],
        }
    )


def test_run_report_explains_proxy_semantics_and_target_counts() -> None:
    report = run_report.build_label_report(_labels(), _targets(), ["smoke_heat_5m"])
    assert report["proxy_rule_version"] == "smvu-proxy-v2"
    assert report["targets"] == {
        "now": {"available": 4, "censored": 0, "positive": 0, "negative": 4},
        "6h": {"available": 3, "censored": 1, "positive": 1, "negative": 2},
        "12h": {"available": 2, "censored": 2, "positive": 1, "negative": 1},
        "24h": {"available": 1, "censored": 3, "positive": 1, "negative": 0},
    }
    assert report["class_balance"] == {
        "now": {"negative": 4, "positive": 0, "positive_share": 0.0},
        "6h": {"negative": 2, "positive": 1, "positive_share": 1 / 3},
        "12h": {"negative": 1, "positive": 1, "positive_share": 0.5},
        "24h": {"negative": 0, "positive": 1, "positive_share": 1.0},
    }
    assert "not detection quality for confirmed real fires" in report["warning"]


def test_report_groups_incidents_and_explains_shared_signal_families() -> None:
    columns = [
        "smoke_heat_5m",
        "smoke_manual_30m",
        "smoke_uir_3h",
        "gas_max_24h",
        "pump_alarm_6h",
        "temperature_mean_5m",
        "event_count_5m",
    ]
    report = run_report.build_label_report(_labels(), _targets(), columns)
    assert report["proxy_incidents"] == {
        "by_year": {"2025": 1, "2026": 2},
        "by_object": {"a": 1, "b": 2},
        "by_rule": {"smoke_heat": 2, "smoke_supporting_pump": 1},
        "by_sensor_combination": [
            {"count": 2, "sensor_combination": ["heat", "smoke"]},
            {"count": 1, "sensor_combination": ["pump", "smoke"]},
        ],
        "total": 3,
    }
    overlap = report["feature_rule_overlap"]
    assert overlap["shared_signal_families"] == [
        "gas",
        "heat",
        "manual",
        "pump",
        "smoke",
        "uir",
    ]
    assert overlap["feature_columns_by_family"]["heat"] == [
        "smoke_heat_5m",
        "temperature_mean_5m",
    ]
    assert (
        run_report.build_label_report(_labels(), _targets(), ["event_count_5m"])[
            "feature_rule_overlap"
        ]["shared_signal_families"]
        == []
    )
    shuffled = run_report.build_label_report(
        list(reversed(_labels())), _targets().reverse().lazy(), list(reversed(columns))
    )
    assert json.dumps(report) == json.dumps(shuffled)
    pending = [report]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            assert list(item) == sorted(item)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def test_empty_report_keeps_version_and_nullable_class_balance() -> None:
    report = run_report.build_label_report([], _targets().head(0), [])
    assert report["proxy_rule_version"] == "smvu-proxy-v2"
    assert report["proxy_incidents"]["total"] == 0
    assert report["targets"]["6h"] == {
        "available": 0,
        "censored": 0,
        "positive": 0,
        "negative": 0,
    }
    assert report["class_balance"]["6h"]["positive_share"] is None
