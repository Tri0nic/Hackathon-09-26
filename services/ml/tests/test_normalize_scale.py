"""Normalization semantics and cardinality-bound Python execution."""

from pathlib import Path
from time import perf_counter

import polars as pl
import pytest

from fire_risk.config import PipelineConfig
from fire_risk.data import pipeline


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    path = tmp_path / "states.csv"
    path.write_text(
        "sensor_type,state_set_id,state_name,alarm_flag\n"
        "smoke,normal,normal,false\n"
        "smoke,alarm,alarm,true\n"
        "smoke,set-a,conflict,true\n"
        "smoke,set-b,conflict,false\n",
        encoding="utf-8",
    )
    return path


def test_distinct_normalization_preserves_row_semantics_and_order(state_file):
    cases = [
        ("heat", "25", False, "numeric", 25.0, None, "numeric", False, []),
        (
            "smoke",
            "normal",
            True,
            "known_state",
            None,
            "normal",
            "state_mapping",
            False,
            [],
        ),
        (
            "smoke",
            "alarm",
            False,
            "known_state",
            None,
            "alarm",
            "state_mapping",
            True,
            [],
        ),
        (
            "smoke",
            "conflict",
            True,
            "unknown",
            None,
            None,
            "conflicting_state_mapping",
            True,
            ["conflicting_state_mapping"],
        ),
        (
            "heat",
            "01.01.1970 03:00:00",
            False,
            "malfunction",
            None,
            None,
            "invalid_epoch_date",
            False,
            ["invalid_epoch_date"],
        ),
        (
            "heat",
            "999",
            False,
            "malfunction",
            None,
            None,
            "sentinel_value",
            False,
            ["sentinel_value"],
        ),
        (
            "Газовый датчик",
            "1.5",
            False,
            "numeric",
            1.5,
            None,
            "numeric",
            True,
            ["methane_alarm"],
        ),
        (
            "heat",
            "NaN",
            False,
            "unknown",
            None,
            None,
            "unmapped_state",
            False,
            ["unmapped_state"],
        ),
        (
            None,
            None,
            True,
            "unknown",
            None,
            None,
            "unmapped_state",
            True,
            ["unmapped_state"],
        ),
    ]
    rows = []
    expected = []
    for row_id, case in enumerate(cases * 2):
        sensor, raw, alarm, kind, numeric, state, rule, normalized_alarm, flags = case
        rows.append(
            {
                "event_id": str(row_id),
                "sensor_type": sensor,
                "raw_value": raw,
                "sensor_name": "ПК 12" if row_id % 2 else None,
                "alarm_flag": alarm,
                "quality_flags": ["upstream"],
            }
        )
        expected.append(
            {
                "event_id": str(row_id),
                "source_alarm_flag": alarm,
                "value_kind": kind,
                "numeric_value": numeric,
                "state_code": state,
                "normalization_rule": rule,
                "alarm_flag": normalized_alarm,
                "quality_flags": ["upstream", *flags],
                "picket_raw": "ПК 12" if row_id % 2 else None,
                "picket_sort_key": 12.0 if row_id % 2 else None,
                "location_group": "picket" if row_id % 2 else "unlocated",
            }
        )
    source = pl.DataFrame(rows)
    actual = pipeline._normalize_events(
        source.lazy(), state_file, PipelineConfig(sensor_sentinels={"heat": {"999"}})
    ).collect(engine="streaming")
    assert actual.select(expected[0].keys()).to_dicts() == expected
    assert (
        actual.select(source.columns)
        .drop("alarm_flag", "quality_flags")
        .equals(source.drop("alarm_flag", "quality_flags"))
    )
    assert actual.schema["numeric_value"] == pl.Float64
    assert actual.schema["picket_sort_key"] == pl.Float64
    assert actual.schema["quality_flags"] == pl.List(pl.String)
    empty = pipeline._normalize_events(
        source.head(0).lazy(), state_file, PipelineConfig()
    ).collect()
    assert empty.schema == actual.schema


@pytest.mark.parametrize("project", [False, True])
def test_python_work_is_bounded_by_distinct_values_and_names(
    state_file, monkeypatch, project
):
    calls = {"value": 0, "picket": 0}
    normalize = pipeline.normalize_value
    picket = pipeline.parse_picket

    def count_value(*args, **kwargs):
        calls["value"] += 1
        return normalize(*args, **kwargs)

    def count_picket(*args, **kwargs):
        calls["picket"] += 1
        return picket(*args, **kwargs)

    monkeypatch.setattr(pipeline, "normalize_value", count_value)
    monkeypatch.setattr(pipeline, "parse_picket", count_picket)
    count = 1_000_000
    source = pl.DataFrame(
        {
            "sensor_type": ["smoke", "smoke", "heat", None] * (count // 4),
            "raw_value": ["normal", "alarm", "25", None] * (count // 4),
            "sensor_name": ["ПК 12", "unknown"] * (count // 2),
            "alarm_flag": [False] * count,
            "quality_flags": [[]] * count,
        },
        schema_overrides={"quality_flags": pl.List(pl.String)},
    )
    lazy = pipeline._normalize_events(source.lazy(), state_file, PipelineConfig())
    if project:
        lazy = lazy.select("alarm_flag")
    started = perf_counter()
    actual = lazy.collect(engine="streaming")
    elapsed = perf_counter() - started
    assert actual.height == count
    assert actual["alarm_flag"].sum() == count // 4
    assert calls["value"] == 4, calls
    assert calls["picket"] <= 2, calls
    if not project:
        assert calls["picket"] == 2
    print(
        f"Repeated-value normalization: {actual.height / elapsed:.0f} rows/s; {calls}"
    )
