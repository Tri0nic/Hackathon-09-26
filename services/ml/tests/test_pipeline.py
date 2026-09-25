"""Full-run safety, scoped resume identities, frozen calibration and reporting."""

import importlib
import importlib.util
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from fire_risk.config import PipelineConfig

FIXTURES = Path(__file__).parent / "fixtures"
STAGES = [
    "00-source-inventory.json",
    "10-channel-day-profiles.parquet",
    "20-calibrated-thresholds.json",
    "30-normalized-events.parquet",
    "31-object-inventory.parquet",
    "32-object-inventory-by-type.parquet",
    "40-episodes.parquet",
    "41-episode-membership.parquet",
    "50-incident-labels.parquet",
    "60-feature-snapshots.parquet",
    "70-coverage.json",
    "71-quality-report.json",
    "72-run-report.json",
    "manifest.json",
]


@pytest.fixture
def pipeline():
    assert importlib.util.find_spec("fire_risk.data.pipeline") is not None, (
        "Missing resumable full-run pipeline"
    )
    return importlib.import_module("fire_risk.data.pipeline")


@pytest.fixture
def full_config(tmp_path, pipeline):
    journals = []
    references = []
    base = pl.read_csv(FIXTURES / "channels.csv", infer_schema=False).head(1)
    for year in range(2019, 2027):
        for suffix, sensor in [("s", "Датчик дыма"), ("h", "Датчик температуры")]:
            references.append(
                base.with_columns(
                    pl.lit(f"{year}-{suffix}").alias("channel_id"),
                    pl.lit(f"object-{year}").alias("object_id"),
                    pl.lit(sensor).alias("sensor_type"),
                )
            )
        journal = tmp_path / f"ext-journal-{year}.csv"
        journal.write_text(
            "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
            f"{year}-1,{year}-s,{year}-01-03,00:00:00,t,Обнаружен дым\n"
            f"{year}-2,{year}-h,{year}-01-03,00:01:00,t,40\n"
            + (f"bad,{year}-s,broken,00:00:00,f,20\n" if year == 2021 else ""),
            encoding="utf-8",
        )
        journals.append(journal)
    channels = tmp_path / "channels.csv"
    pl.concat(references).write_csv(channels)
    return pipeline.FullRunConfig(
        events=tuple(journals),
        channels=channels,
        states=FIXTURES / "states.csv",
        output=tmp_path / "output",
        temp_dir=tmp_path / "spool",
        run_id="full",
        observed_until=datetime(2026, 1, 3, 3, tzinfo=UTC),
        seed=42,
        implementation_revision="fixture-build",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", 43),
        ("source_timezone", "UTC"),
        ("schema_version", "next-schema"),
        ("implementation_revision", "another-build"),
        ("settings", PipelineConfig(scoring_step_minutes=30)),
        ("observed_until", datetime(2026, 1, 3, 4, tzinfo=UTC)),
    ],
)
def test_run_identity_covers_every_semantic_input(pipeline, full_config, field, value):
    hashes = {"source": "a" * 64}
    original = pipeline.compute_run_identity(full_config, hashes)
    assert (
        pipeline.compute_run_identity(replace(full_config, **{field: value}), hashes)
        != original
    )
    assert pipeline.compute_run_identity(full_config, {"source": "b" * 64}) != original
    assert (
        pipeline.compute_run_identity(replace(full_config, resume=False), hashes)
        == original
    )


def test_failed_stage_preserves_old_artifact_and_removes_completion(tmp_path, pipeline):
    store = pipeline.StageStore(tmp_path, resume=True)
    store.run(
        "10-data.json", {"version": 1}, lambda path: path.write_text('{"old":true}')
    )
    marker = tmp_path / "10-data.json.complete.json"
    assert marker.exists()

    def fail(path):
        path.write_text("partial")
        raise OSError("simulated interrupted write")

    with pytest.raises(OSError, match="interrupted"):
        pipeline.StageStore(tmp_path, resume=True).run(
            "10-data.json", {"version": 2}, fail
        )
    assert json.loads((tmp_path / "10-data.json").read_text(encoding="utf-8")) == {
        "old": True
    }
    assert not marker.exists()
    rebuilt = pipeline.StageStore(tmp_path, resume=True)
    rebuilt.run(
        "10-data.json", {"version": 2}, lambda path: path.write_text('{"new":true}')
    )
    assert rebuilt.reused_stages == []
    assert json.loads((tmp_path / "10-data.json").read_text(encoding="utf-8")) == {
        "new": True
    }


@pytest.mark.parametrize("tamper", ["identity", "content", "missing_marker"])
def test_stage_never_reuses_tampered_artifact_or_identity(tmp_path, pipeline, tamper):
    def write(path):
        path.write_text("valid")

    pipeline.StageStore(tmp_path, resume=True).run("10-data.json", {}, write)
    marker = tmp_path / "10-data.json.complete.json"
    if tamper == "identity":
        record = json.loads(marker.read_text(encoding="utf-8"))
        record["input_identity"] = "mismatched"
        marker.write_text(json.dumps(record))
    elif tamper == "content":
        (tmp_path / "10-data.json").write_text("damaged")
    else:
        marker.unlink()
    store = pipeline.StageStore(tmp_path, resume=True)
    store.run("10-data.json", {}, write)
    assert store.reused_stages == []
    assert (tmp_path / "10-data.json").read_text(encoding="utf-8") == "valid"


def test_full_run_train_only_frozen_and_complete(pipeline, full_config):
    sources = [*full_config.events, full_config.channels, full_config.states]
    before = {
        str(path.resolve()): sha256(path.read_bytes()).hexdigest() for path in sources
    }
    result = pipeline.run_full(full_config)
    directory = result.directory
    assert all((directory / name).exists() for name in STAGES)
    profiles = pl.read_parquet(directory / STAGES[1])
    assert set(profiles["source_year"]) == set(range(2019, 2025))
    frozen = json.loads((directory / STAGES[2]).read_text(encoding="utf-8"))
    assert frozen["thresholds"] == {
        "min_burst_events": 2,
        "max_repeats_per_second": 2,
        "min_stuck_run": 2,
        "max_event_rate_deviation": 2.0,
    }
    assert not any(
        "2025.csv" in name or "2026.csv" in name for name in frozen["source_sha256"]
    )
    normalized = pl.read_parquet(directory / STAGES[3])
    assert set(normalized["source_year"]) == set(range(2019, 2027))
    assert normalized["registered_at"][0].isoformat() == "2019-01-02T21:00:00+00:00"
    features = pl.read_parquet(directory / "60-feature-snapshots.parquet")
    assert features["hour"].unique().to_list() == [0]
    report = json.loads((directory / "72-run-report.json").read_text(encoding="utf-8"))
    assert report["rows_by_source_year"]["2021"] == {"accepted": 2, "quarantined": 1}
    assert report["channel_object_coverage"] == {
        "matched_events": 16,
        "unknown_events": 0,
        "coverage_percent": 100.0,
    }
    assert report["unknown_states"]["conflicting_events"] == 0
    assert report["excluded_2021"]["pre_calibration_intervals"] == []
    assert report["quality_calibration"] == frozen
    assert report["proxy_incidents"]["total"] == 8
    assert set(report["proxy_incidents"]["by_year"]) == set(map(str, range(2019, 2027)))
    assert set(report["targets"]) == {"now", "6h", "12h", "24h"}
    assert report["targets"]["24h"]["censored"] == 2
    assert report["feature_rule_overlap"]["shared_signal_families"]
    assert "not detection quality for confirmed real fires" in report["warning"]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_sha256_before"] == manifest["source_sha256_after"] == before
    assert manifest["configuration"]["quality_thresholds"] == frozen["thresholds"]
    assert before == {
        str(path.resolve()): sha256(path.read_bytes()).hexdigest() for path in sources
    }
    for name in STAGES:
        marker = json.loads(
            (directory / f"{name}.complete.json").read_text(encoding="utf-8")
        )
        assert set(marker) == {
            "stage",
            "input_identity",
            "output_sha256",
            "schema_version",
            "statistics",
        }
        assert (
            marker["output_sha256"]
            == sha256((directory / name).read_bytes()).hexdigest()
        )


def test_full_run_profiles_are_bounded_and_post_freeze_is_isolated(
    pipeline, full_config, monkeypatch
):
    original = pipeline.profile_channel_days
    observed = []

    def profile(events, *, temp_dir=None):
        assert temp_dir is not None, (
            "Full runs must bound event windows to daily spools"
        )
        years = sorted(events.select("source_year").unique().collect()["source_year"])
        frozen = full_config.output / full_config.run_id / STAGES[2]
        observed.append((years, frozen.exists()))
        return original(events, temp_dir=temp_dir)

    monkeypatch.setattr(pipeline, "profile_channel_days", profile)
    result = pipeline.run_full(full_config)
    assert observed == [
        (list(range(2019, 2025)), False),
        (list(range(2019, 2027)), True),
    ]
    report = json.loads((result.directory / "72-run-report.json").read_text())
    assert report["profile_passes"] == {
        "calibration_source_years": list(range(2019, 2025)),
        "application_source_years": list(range(2019, 2027)),
        "application_uses_frozen_thresholds": True,
        "event_partition": "source_timezone_month_then_day",
    }


def test_resume_is_deterministic_and_downstream_changes_reuse_profiles(
    pipeline, full_config
):
    first = pipeline.run_full(full_config)
    original = {name: (first.directory / name).read_bytes() for name in STAGES}
    second = pipeline.run_full(full_config)
    assert second.reused_stages == tuple(STAGES)
    assert original == {name: (first.directory / name).read_bytes() for name in STAGES}
    third = pipeline.run_full(
        replace(full_config, settings=PipelineConfig(episode_gap_minutes=0))
    )
    assert third.reused_stages == tuple(STAGES[:6])
    assert (third.directory / STAGES[1]).read_bytes() == original[STAGES[1]]
    assert pl.read_parquet(third.directory / "50-incident-labels.parquet").height == 0


def test_no_resume_rebuild_has_identical_parquet_hashes_and_nonclock_json(
    pipeline, full_config
):
    first = pipeline.run_full(full_config)
    original = {name: (first.directory / name).read_bytes() for name in STAGES}
    second = pipeline.run_full(replace(full_config, resume=False))
    assert second.reused_stages == ()
    for name in STAGES:
        after = (second.directory / name).read_bytes()
        if name.endswith(".json"):
            before_json, after_json = json.loads(original[name]), json.loads(after)
            for payload in [before_json, after_json]:
                for field in ["started_at", "completed_at"]:
                    payload.pop(field, None)
            assert before_json == after_json, name
        else:
            assert sha256(original[name]).hexdigest() == sha256(after).hexdigest(), name


def test_normalized_output_preserves_values_source_order_and_rebuild_hash(
    pipeline, full_config
):
    for path in full_config.events:
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1:3] = reversed(lines[1:3])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    first = pipeline.run_full(full_config)
    path = first.directory / STAGES[3]
    original = path.read_bytes()
    actual = pl.read_parquet(path)
    assert actual["event_id"].to_list() == [
        f"{year}-{number}" for year in range(2019, 2027) for number in (2, 1)
    ]
    assert actual["raw_value"].to_list() == ["40", "Обнаружен дым"] * 8
    assert actual["numeric_value"].to_list() == [40.0, None] * 8
    assert actual["alarm_flag"].to_list() == [True] * 16
    assert actual["source_year"].to_list() == [
        year for year in range(2019, 2027) for _ in range(2)
    ]
    pipeline.run_full(replace(full_config, resume=False))
    assert sha256(original).hexdigest() == sha256(path.read_bytes()).hexdigest()


def test_disk_backed_normalized_sink_has_no_global_wide_sort(
    pipeline, full_config, monkeypatch
):
    sink = pl.LazyFrame.sink_parquet
    plans = []

    def observe(frame, path, *args, **kwargs):
        if isinstance(path, Path) and path.name.startswith(".30-normalized-events"):
            query = sink(frame, path, lazy=True)
            physical = query.show_graph(
                show=False, raw_output=True, engine="streaming", plan_stage="physical"
            )
            plans.append(
                "\n".join(
                    line
                    for line in physical.splitlines()
                    if any(
                        node in line
                        for node in ('label="sort', "sink", "in-memory-join")
                    )
                )
            )
        return sink(frame, path, *args, **kwargs)

    monkeypatch.setattr(pl.LazyFrame, "sink_parquet", observe)
    pipeline.run_full(full_config)
    assert len(plans) == 1
    assert 'label="sort' not in plans[0], plans[0]
    assert "in-memory-sink" not in plans[0], plans[0]
    assert "in-memory-join" not in plans[0], plans[0]
    assert "parquet-sink" in plans[0], plans[0]


def test_explicit_temp_directory_contains_csv_spools_and_environment_is_restored(
    pipeline, full_config, monkeypatch
):
    from fire_risk.data import csv_reader

    real = csv_reader._sanitize_csv
    spools = []

    def observed(*args, **kwargs):
        path = real(*args, **kwargs)
        spools.append(path)
        assert path.is_relative_to(full_config.temp_dir)
        assert os.environ["POLARS_TEMP_DIR"] == str(full_config.temp_dir.resolve())
        return path

    monkeypatch.setattr(csv_reader, "_sanitize_csv", observed)
    monkeypatch.setenv("POLARS_TEMP_DIR", "original-temp")
    pipeline.run_full(full_config)
    assert spools
    assert os.environ["POLARS_TEMP_DIR"] == "original-temp"
    assert not any(path.exists() for path in spools)


def test_source_change_during_run_blocks_manifest(pipeline, full_config, monkeypatch):
    original = pipeline.StageStore.run

    def mutate(store, name, *args, **kwargs):
        path = original(store, name, *args, **kwargs)
        if name == "72-run-report.json":
            with full_config.events[0].open("a", encoding="utf-8") as handle:
                handle.write("\n")
        return path

    monkeypatch.setattr(pipeline.StageStore, "run", mutate)
    with pytest.raises(ValueError, match="Source.*changed"):
        pipeline.run_full(full_config)
    assert not (
        full_config.output / full_config.run_id / "manifest.json.complete.json"
    ).exists()


def test_implementation_revision_finds_the_repository_after_module_move(
    pipeline, monkeypatch
):
    monkeypatch.delenv("FIRE_RISK_IMPLEMENTATION_REVISION", raising=False)
    provenance = pipeline._implementation_revision()
    assert provenance["implementation_revision_source"] == "git_head"
    assert len(provenance["implementation_revision"]) == 40


def test_validation_extremes_never_refit_train_thresholds(pipeline, full_config):
    validation = full_config.events[-2]
    with validation.open("a", encoding="utf-8") as handle:
        handle.writelines(
            f"extra-{index},2025-s,2025-01-03,00:00:00,t,Обнаружен дым\n"
            for index in range(30)
        )
    result = pipeline.run_full(replace(full_config, events=full_config.events[-3:]))
    frozen = json.loads(
        (result.directory / "20-calibrated-thresholds.json").read_text(encoding="utf-8")
    )
    assert frozen["thresholds"]["min_burst_events"] == 2
    assert frozen["thresholds"]["min_stuck_run"] == 2
    normalized = pl.read_parquet(result.directory / "30-normalized-events.parquet")
    assert normalized.filter(pl.col("channel_id") == "2025-s")["burst"].all()
    assert not normalized.filter(pl.col("source_year") == 2026)["burst"].any()
