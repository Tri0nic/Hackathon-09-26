from datetime import UTC, datetime

import polars as pl
from fire_risk.ml.evaluation import event_metrics


def test_event_metrics_deduplicate_false_alerts_by_object_day() -> None:
    rows = pl.DataFrame(
        {
            "object_id": ["a", "a", "b", "b", "c"],
            "scoring_timestamp": [
                datetime(2026, 1, 1, 4, tzinfo=UTC),
                datetime(2026, 1, 1, 10, tzinfo=UTC),
                datetime(2026, 1, 1, 3, tzinfo=UTC),
                datetime(2026, 1, 1, 5, tzinfo=UTC),
                datetime(2026, 1, 2, 8, tzinfo=UTC),
            ],
            "episode_group_id": ["event-1", "event-1", None, None, "event-2"],
            "target": [True, True, False, False, True],
            "target_now": [False, True, False, False, True],
            "alert": [True, False, True, True, False],
        }
    )

    result = event_metrics(rows)

    assert result["events"] == 2
    assert result["detected_events"] == 1
    assert result["false_alert_object_days"] == 1
    assert result["evaluated_object_days"] == 3
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5
    assert result["false_alerts_per_object_day"] == 1 / 3
    assert result["median_lead_time_hours"] == 6.0
