"""Real fixture preparation, output provenance, and deterministic reruns."""

import json
from hashlib import sha256
from pathlib import Path

import polars as pl
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
    ]


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
    args[-1] = "../escaped"
    result = RUNNER.invoke(app, args)
    assert result.exit_code != 0
    assert not (tmp_path.parent / "escaped").exists()


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
