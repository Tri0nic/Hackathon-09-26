"""Real fixture preparation, output provenance, and deterministic reruns."""

import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from typer.testing import CliRunner

from fire_risk.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
RUNNER = CliRunner()
OUTPUTS = [
    "normalized_events",
    "episodes",
    "episode_membership",
    "incident_labels",
    "feature_snapshots",
]


def prepare_args(
    output: Path,
    events: Path = FIXTURES / "events.csv",
    channels: Path = FIXTURES / "channels.csv",
    states: Path = FIXTURES / "states.csv",
) -> list[str]:
    return [
        "prepare",
        "--events",
        str(events),
        "--channels",
        str(channels),
        "--states",
        str(states),
        "--output",
        str(output),
        "--run-id",
        "test-run",
        "--label-observed-until",
        "2026-12-31T00:00:00+00:00",
    ]


def test_prepare_requires_explicit_label_observation_boundary(tmp_path: Path) -> None:
    args = prepare_args(tmp_path)
    del args[-2:]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 2
    assert "label-observed-until" in result.output


def test_prepare_records_label_observation_boundary(tmp_path: Path) -> None:
    result = RUNNER.invoke(app, prepare_args(tmp_path))
    assert result.exit_code == 0, result.output + str(result.exception)
    manifest = json.loads((tmp_path / "test-run" / "manifest.json").read_text())
    assert (
        manifest["configuration"]["label_observed_until"] == "2026-12-31T00:00:00+00:00"
    )


def test_prepare_writes_outputs_and_reproducible_manifest_without_mutating_sources(
    tmp_path: Path,
) -> None:
    sources = [FIXTURES / name for name in ["events.csv", "channels.csv", "states.csv"]]
    hashes = [sha256(path.read_bytes()).hexdigest() for path in sources]
    result = RUNNER.invoke(app, prepare_args(tmp_path))
    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "test-run"
    first_frames = {
        name: pl.read_parquet(directory / f"{name}.parquet") for name in OUTPUTS
    }
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["row_counts"] == {
        "normalized_events": 2,
        "episodes": 0,
        "episode_membership": 2,
        "incident_labels": 0,
        "feature_snapshots": 0,
    }
    assert manifest["run_id"] == "test-run"
    assert len(manifest["config_hash"]) == 64
    assert [(s["filename"], s["size_bytes"]) for s in manifest["sources"]] == [
        (p.name, p.stat().st_size) for p in sources
    ]
    coverage = json.loads((directory / "coverage.json").read_text())
    quality = json.loads((directory / "quality_report.json").read_text())
    assert coverage["unknown_channel_events"] == 2
    assert coverage["conflicting_state_events"] == 0
    assert quality["quarantined_rows"] == 0
    second = RUNNER.invoke(app, prepare_args(tmp_path))
    assert second.exit_code == 0, second.output + str(second.exception)
    rerun = json.loads((directory / "manifest.json").read_text())
    for value in [manifest, rerun]:
        for key in ["started_at", "completed_at"]:
            assert value.pop(key)
    assert manifest == rerun
    for name, frame in first_frames.items():
        assert_frame_equal(frame, pl.read_parquet(directory / f"{name}.parquet"))
    assert hashes == [sha256(path.read_bytes()).hexdigest() for path in sources]


def test_manifest_records_explicit_implementation_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FIRE_RISK_IMPLEMENTATION_REVISION", "build-final-validation")
    result = RUNNER.invoke(app, prepare_args(tmp_path))
    assert result.exit_code == 0, result.output + str(result.exception)
    manifest = json.loads((tmp_path / "test-run" / "manifest.json").read_text())
    assert manifest["implementation_revision"] == "build-final-validation"
    assert manifest["implementation_revision_source"] == "environment"


def test_cli_wires_normalization_episodes_proxy_targets_and_quality(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events.csv"
    events.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,f,Норма\n"
        "2,001,2024-01-03,01:00:00,t,Пожар\n"
        "3,002,2024-01-03,01:01:00,t,40\n"
        "4,002,not-a-date,00:00:00,f,20\n"
        "5,001,2024-01-03,02:00:00,f,Конфликт\n",
        encoding="utf-8",
    )
    channels = tmp_path / "channels.csv"
    pl.read_csv(FIXTURES / "channels.csv", infer_schema=False).with_columns(
        pl.lit("object-1").alias("object_id"),
        pl.Series("sensor_type", ["Датчик дыма", "Датчик температуры"]),
        pl.Series("sensor_name", ["Дым ПК3", "Тепло ПК4"]),
    ).write_csv(channels)
    states = tmp_path / "states.csv"
    states.write_text(
        "sensor_type,state_set_id,state_name,alarm_flag\n"
        "Датчик дыма,normal,Норма,false\n"
        "Датчик дыма,fire,Пожар,true\n"
        "Датчик дыма,a,Конфликт,true\n"
        "Датчик дыма,b,Конфликт,false\n",
        encoding="utf-8",
    )
    result = RUNNER.invoke(
        app, prepare_args(tmp_path / "out", events, channels, states)
    )
    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "out" / "test-run"
    normalized = pl.read_parquet(directory / "normalized_events.parquet")
    assert normalized["event_id"].to_list() == ["1", "2", "3", "5"]
    assert normalized["value_kind"].to_list() == [
        "known_state",
        "known_state",
        "numeric",
        "unknown",
    ]
    assert normalized["picket_raw"].to_list() == ["ПК3", "ПК3", "ПК4", "ПК3"]
    assert normalized["age_source"].to_list() == ["first_seen"] * 4
    assert pl.read_parquet(directory / "episodes.parquet").height == 3
    labels = pl.read_parquet(directory / "incident_labels.parquet")
    assert labels.height == 1
    assert labels["source"].item() == "proxy"
    assert labels["decision"].item() == "unknown"
    snapshots = pl.read_parquet(directory / "feature_snapshots.parquet")
    assert snapshots.height == 9
    assert snapshots["target_6h"][0] is True
    assert snapshots["event_count_5m"][0] == 1
    assert snapshots["target_now"][4] is True
    assert snapshots["episode_group_id"][0] == labels["incident_id"].item()
    coverage = json.loads((directory / "coverage.json").read_text())
    quality = json.loads((directory / "quality_report.json").read_text())
    assert coverage["conflicting_state_events"] == 1
    assert quality["invalid_timestamp_rows"] == 1
    assert quality["quarantined_rows"] == 1


def test_run_id_cannot_escape_output_directory(tmp_path: Path) -> None:
    args = prepare_args(tmp_path)
    args[args.index("--run-id") + 1] = "../escaped"
    result = RUNNER.invoke(app, args)
    assert result.exit_code != 0
    assert not (tmp_path.parent / "escaped").exists()


@pytest.mark.parametrize(
    ("threshold", "gas_alarm", "label_count"), [(1.0, True, 1), (1.5, False, 0)]
)
def test_methane_threshold_participates_in_episode_alarm_composition_and_proxy_labels(
    tmp_path: Path,
    threshold: float,
    gas_alarm: bool,
    label_count: int,
) -> None:
    source = tmp_path / "gas.csv"
    source.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,t,Обнаружен дым\n"
        "2,002,2024-01-03,00:01:00,f,1.20\n"
        "3,003,2024-01-03,00:02:00,t,Пуск\n"
        "4,002,2024-01-03,00:03:00,f,0.75\n",
        encoding="utf-8",
    )
    base = pl.read_csv(FIXTURES / "channels.csv", infer_schema=False).head(1)
    channels = tmp_path / "channels.csv"
    pl.concat(
        [
            base.with_columns(
                pl.lit(channel).alias("channel_id"), pl.lit(sensor).alias("sensor_type")
            )
            for channel, sensor in [
                ("001", "Датчик дыма"),
                ("002", "Газовый датчик"),
                ("003", "Насос"),
            ]
        ]
    ).write_csv(channels)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"methane_alarm_percent": threshold}), encoding="utf-8"
    )
    result = RUNNER.invoke(
        app,
        prepare_args(tmp_path / "out", source, channels) + ["--config", str(config)],
    )
    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "out" / "test-run"
    normalized = pl.read_parquet(directory / "normalized_events.parquet")
    assert normalized["alarm_flag"].to_list() == [True, gas_alarm, True, False]
    assert normalized["source_alarm_flag"].to_list() == [True, False, True, False]
    episodes = pl.read_parquet(directory / "episodes.parquet")
    assert (
        "Газовый датчик" in episodes["alarming_sensor_types"].item().to_list()
    ) is gas_alarm
    labels = pl.read_parquet(directory / "incident_labels.parquet")
    assert labels.height == label_count
    if label_count:
        assert labels["source"].item() == "proxy"


def test_cli_reports_malformed_required_values_ragged_rows_and_quotes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "malformed.csv"
    source.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,f,unmapped\n"
        "2,001,2024-01-03,00:01:00,f,\n"
        "3,001,2024-01-03,00:02:00,f\n"
        "4,001,2024-01-03,00:03:00,f,20,extra\n"
        '5,001,2024-01-03,00:04:00,f,"20"oops\n'
        '6,001,2024-01-03,00:05:00,f,"unfinished\n'
        "7,001,2024-01-03,00:06:00,f,Норма\n",
        encoding="utf-8",
    )
    result = RUNNER.invoke(app, prepare_args(tmp_path / "out", source))
    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "out" / "test-run"
    assert pl.read_parquet(directory / "normalized_events.parquet")[
        "event_id"
    ].to_list() == ["1", "7"]
    quality = json.loads((directory / "quality_report.json").read_text())
    assert quality["quarantined_rows"] == 5
    assert quality["invalid_timestamp_rows"] == 0
    assert quality["malformed_input_rows"] == 5
    assert quality["input_quality_reasons"] == {
        "missing_raw_value": 1,
        "too_few_fields": 1,
        "extra_fields": 1,
        "invalid_csv_quoting": 2,
    }


def test_cli_can_prepare_an_entirely_quarantined_journal(tmp_path: Path) -> None:
    source = tmp_path / "all-bad.csv"
    source.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,f,20,extra\n"
        "2,001,2024-01-03,00:01:00,f,\n"
        '3,001,2024-01-03,00:02:00,f,"20"oops\n',
        encoding="utf-8",
    )

    result = RUNNER.invoke(app, prepare_args(tmp_path / "out", source))

    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "out" / "test-run"
    assert pl.read_parquet(directory / "normalized_events.parquet").height == 0
    quality = json.loads((directory / "quality_report.json").read_text())
    assert quality["malformed_input_rows"] == 3
    assert quality["input_quality_reasons"] == {
        "extra_fields": 1,
        "missing_raw_value": 1,
        "invalid_csv_quoting": 1,
    }


def test_future_burst_does_not_retroactively_change_training_features(
    tmp_path: Path,
) -> None:
    source = tmp_path / "events.csv"
    header = "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
    past = "1,001,2021-01-03,00:00:00,t,Норма\n"
    source.write_text(header + past, encoding="utf-8")
    result = RUNNER.invoke(app, prepare_args(tmp_path / "out", source))
    assert result.exit_code == 0, result.output + str(result.exception)
    directory = tmp_path / "out" / "test-run"
    before = pl.read_parquet(directory / "feature_snapshots.parquet").head(1)
    source.write_text(
        header
        + past
        + "".join(f"{i},001,2021-01-03,00:01:00,t,Норма\n" for i in range(2, 102)),
        encoding="utf-8",
    )
    result = RUNNER.invoke(app, prepare_args(tmp_path / "out", source))
    assert result.exit_code == 0, result.output + str(result.exception)
    after = pl.read_parquet(directory / "feature_snapshots.parquet").head(1)
    target_columns = [name for name in before.columns if name.startswith("target_")] + [
        "episode_group_id"
    ]
    assert_frame_equal(before.drop(target_columns), after.drop(target_columns))
    final_snapshot = pl.read_parquet(directory / "feature_snapshots.parquet").tail(1)
    assert final_snapshot["historical_artifact_count_24h"].item() == 2
    quality = json.loads((directory / "quality_report.json").read_text())
    assert quality["historical_artifact_rows"] == 101


def test_configuration_changes_grid_and_manifest_hash(tmp_path: Path) -> None:
    source = tmp_path / "events.csv"
    source.write_text(
        "ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика\n"
        "1,001,2024-01-03,00:00:00,f,Норма\n"
        "2,001,2024-01-03,01:00:00,f,Норма\n",
        encoding="utf-8",
    )
    args = prepare_args(tmp_path / "out", source)
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0, result.output + str(result.exception)
    manifest_path = tmp_path / "out" / "test-run" / "manifest.json"
    before = json.loads(manifest_path.read_text())
    configuration = tmp_path / "config.json"
    configuration.write_text('{"scoring_step_minutes": 30}', encoding="utf-8")
    result = RUNNER.invoke(app, args + ["--config", str(configuration)])
    assert result.exit_code == 0, result.output + str(result.exception)
    after = json.loads(manifest_path.read_text())
    assert before["row_counts"]["feature_snapshots"] == 5
    assert after["row_counts"]["feature_snapshots"] == 3
    assert before["config_hash"] != after["config_hash"]


@pytest.mark.parametrize(
    "run_id",
    [
        "smoke-test.",
        "smoke-test..",
        "smoke-test ",
        "CON",
        "con.txt",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM9.log",
        "LPT1",
        "LPT9.backup",
        "test/run",
        "test\\run",
        "test:run",
    ],
)
def test_invalid_windows_run_ids_fail_before_writing_outputs(
    tmp_path: Path, run_id: str
) -> None:
    output = tmp_path / "out"
    args = prepare_args(output)
    args[args.index("--run-id") + 1] = run_id
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 2, result.output + str(result.exception)
    assert not output.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows filesystem case alias")
def test_run_id_cannot_alias_another_id_by_case(tmp_path: Path) -> None:
    existing = tmp_path / "test-run"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")
    args = prepare_args(tmp_path)
    args[args.index("--run-id") + 1] = "TEST-RUN"
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 2, result.output + str(result.exception)
    assert sorted(path.name for path in existing.iterdir()) == ["keep.txt"]
    assert marker.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("outside_output", [False, True])
def test_run_directory_alias_cannot_overwrite_another_directory(
    tmp_path: Path, outside_output: bool
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    target = (tmp_path if outside_output else output) / "original"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")
    alias = output / "test-run"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        alias.symlink_to(target, target_is_directory=True)
    result = RUNNER.invoke(app, prepare_args(output))
    assert result.exit_code == 2, result.output + str(result.exception)
    assert sorted(path.name for path in target.iterdir()) == ["keep.txt"]
    assert marker.read_text(encoding="utf-8") == "unchanged"
