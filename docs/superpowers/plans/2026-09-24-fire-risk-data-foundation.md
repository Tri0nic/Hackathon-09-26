# Fire Risk Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить воспроизводимый Python pipeline, который потоково читает журналы СМВУ, нормализует события, сохраняет данные 2021 года с точечной маркировкой аномалий, извлекает пикеты, объединяет события в эпизоды и формирует единый контракт временного и будущего `y`.

**Architecture:** Python-пакет `fire_risk` разделён на контракты, адаптеры чтения, нормализацию, проверки качества, пикеты, эпизоды и метки. Все преобразования являются чистыми функциями или ленивыми pipeline-операциями; исходные CSV не изменяются. Результаты пишутся в версионированный Parquet-слой.

**Tech Stack:** Python 3.12, Polars, PyArrow, Pydantic 2, Typer, pytest, Hypothesis, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-24-fire-risk-mvp-design.md`

## Global Constraints

- Исходные журналы 2019–2026 и справочники читаются без изменения.
- Обработка полного объёма 14,82 ГБ не должна требовать загрузки всех строк в память.
- Канал связывается с объектом только через `ид_объект` из обновлённого справочника.
- Значение канала классифицируется как `numeric`, `known_state`, `malfunction` или `unknown`.
- Данные 2021 года не исключаются целиком; карантин применяется к конкретному каналу и интервалу.
- Газовые числовые значения хранятся как процент объёма метана; порог тревоги равен 1%.
- Исходное обозначение пикета и исходное значение канала всегда сохраняются.
- Proxy labels и будущие реальные решения приводятся к одному `IncidentLabel`.
- Для снимка в момент `t` признаки используют только данные с timestamp `≤ t`.

## Review Focus

- Повреждённая CSV-строка должна попасть в quarantine, не останавливая чтение остальных строк; проверяется в Task 2.
- Неизвестный `channel_id` должен сохраниться с флагом качества, а не исчезнуть при join; проверяется в Task 3.
- Техническая дата 1970 года и sentinel-код не должны стать валидным измерением; проверяется в Task 4.
- Аномальный канал в один день 2021 года не должен привести к исключению всего года; проверяется в Task 5.
- Канал без распознанного пикета должен сохраниться в `unlocated`, а события после gap должны начать новый эпизод; проверяется в Tasks 6 и 7.

---

## File Structure

```text
services/ml/
├── pyproject.toml
├── README.md
├── src/fire_risk/
│   ├── __init__.py
│   ├── config.py
│   ├── contracts.py
│   ├── cli.py
│   └── data/
│       ├── __init__.py
│       ├── csv_reader.py
│       ├── references.py
│       ├── normalize.py
│       ├── quality.py
│       ├── pickets.py
│       ├── device_metadata.py
│       ├── episodes.py
│       └── labels.py
└── tests/
    ├── fixtures/
    │   ├── events.csv
    │   ├── events_malformed.csv
    │   ├── channels.csv
    │   └── states.csv
    ├── test_contracts.py
    ├── test_csv_reader.py
    ├── test_references.py
    ├── test_normalize.py
    ├── test_quality.py
    ├── test_pickets.py
    ├── test_device_metadata.py
    ├── test_episodes.py
    ├── test_labels.py
    └── test_cli.py
```

## Task 1: ML package scaffold and canonical contracts

**Files:**
- Create: `services/ml/pyproject.toml`
- Create: `services/ml/src/fire_risk/__init__.py`
- Create: `services/ml/src/fire_risk/config.py`
- Create: `services/ml/src/fire_risk/contracts.py`
- Create: `services/ml/tests/test_contracts.py`

**Interfaces:**
- Consumes: none.
- Produces: `ValueKind`, `SensorEventRaw`, `SensorEventNormalized`, `IncidentEpisode`, `IncidentLabel`, `PipelineConfig`.

- [ ] **Step 1: Create package metadata and test configuration**

```toml
[project]
name = "fire-risk-ml"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["polars>=1.0", "pyarrow>=17", "pydantic>=2.8", "typer>=0.12"]

[project.optional-dependencies]
dev = ["pytest>=8", "hypothesis>=6", "ruff>=0.6", "mypy>=1.11"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write failing contract tests**

```python
from datetime import datetime
from fire_risk.contracts import SensorEventRaw, ValueKind


def test_raw_event_keeps_original_value() -> None:
    event = SensorEventRaw(
        event_id="1",
        channel_id="120578",
        registered_at=datetime(2026, 8, 1, 3, 9, 27),
        alarm_flag=True,
        raw_value="01.01.1970 03:00:00",
        source_year=2026,
    )
    assert event.raw_value == "01.01.1970 03:00:00"
    assert ValueKind.MALFUNCTION.value == "malfunction"
```

- [ ] **Step 3: Run the contract test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_contracts.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'fire_risk.contracts'`.

- [ ] **Step 4: Implement the contracts**

```python
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class ValueKind(StrEnum):
    NUMERIC = "numeric"
    KNOWN_STATE = "known_state"
    MALFUNCTION = "malfunction"
    UNKNOWN = "unknown"


class SensorEventRaw(BaseModel):
    event_id: str
    channel_id: str
    registered_at: datetime
    alarm_flag: bool
    raw_value: str
    source_year: int


class SensorEventNormalized(BaseModel):
    event_id: str
    channel_id: str
    object_id: str | None
    registered_at: datetime
    sensor_type: str | None
    sensor_name: str | None
    alarm_flag: bool
    value_kind: ValueKind
    numeric_value: float | None = None
    state_code: str | None = None
    raw_value: str
    picket_raw: str | None = None
    picket_sort_key: float | None = None
    quality_flags: list[str] = Field(default_factory=list)


class IncidentEpisode(BaseModel):
    episode_id: str
    object_id: str
    started_at: datetime
    ended_at: datetime
    severity: str
    channel_ids: list[str]
    sensor_types: list[str]
    picket_from: float | None = None
    picket_to: float | None = None
    quality_flags: list[str] = Field(default_factory=list)


class IncidentDecision(StrEnum):
    CONFIRMED_FIRE = "confirmed_fire"
    SMOKE_WITHOUT_FIRE = "smoke_without_fire"
    FALSE_ALARM = "false_alarm"
    MAINTENANCE = "maintenance"
    SENSOR_MALFUNCTION = "sensor_malfunction"
    UNKNOWN = "unknown"


class LabelSource(StrEnum):
    PROXY = "proxy"
    SYNTHETIC = "synthetic"
    DISPATCHER = "dispatcher"
    IMPORTED = "imported"


class IncidentLabel(BaseModel):
    incident_id: str
    object_id: str
    started_at: datetime
    ended_at: datetime | None = None
    incident_type: str
    decision: IncidentDecision
    confirmed_at: datetime | None = None
    source: LabelSource
    confidence: float = Field(ge=0.0, le=1.0)


class PipelineConfig(BaseModel):
    scoring_step_minutes: int = 15
    episode_gap_minutes: int = 30
    methane_alarm_percent: float = 1.0
```

Add `ChannelReference` and `StateReference` with the exact source fields from Sections 4.2–4.3 of the technical specification. Add contract tests that reject confidence outside `[0, 1]`, verify mutable list defaults are not shared, and confirm the six decision enum values match the specification.

- [ ] **Step 5: Run tests and static checks**

Run: `cd services/ml && python -m pytest tests/test_contracts.py -v && python -m ruff check src tests && python -m mypy src`  
Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add services/ml
git commit -m "feat(ml): define canonical data contracts"
```

## Task 2: Streaming CSV reader with quarantine

**Files:**
- Create: `services/ml/src/fire_risk/data/__init__.py`
- Create: `services/ml/src/fire_risk/data/csv_reader.py`
- Create: `services/ml/tests/fixtures/events.csv`
- Create: `services/ml/tests/fixtures/events_malformed.csv`
- Create: `services/ml/tests/test_csv_reader.py`

**Interfaces:**
- Consumes: `SensorEventRaw`.
- Produces: `scan_events(paths: list[Path]) -> pl.LazyFrame` and `partition_events(paths: list[Path]) -> tuple[pl.LazyFrame, pl.LazyFrame]`.

- [ ] **Step 1: Add a minimal valid fixture**

```csv
ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика
1,120578,2026-08-01,03:09:27,t,Обнаружен дым
2,120298,2026-08-01,03:10:00,f,28
```

- [ ] **Step 2: Write failing reader tests**

```python
from pathlib import Path
from fire_risk.data.csv_reader import scan_events


def test_scan_events_builds_registered_at() -> None:
    frame = scan_events([Path("tests/fixtures/events.csv")]).collect()
    assert frame.columns == [
        "event_id", "channel_id", "registered_at", "alarm_flag",
        "raw_value", "source_year",
    ]
    assert frame["source_year"].to_list() == [2026, 2026]
```

- [ ] **Step 3: Run the reader test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_csv_reader.py -v`  
Expected: FAIL because `scan_events` does not exist.

- [ ] **Step 4: Implement lazy scanning and canonical renaming**

Use `pl.scan_csv(..., encoding="utf8", infer_schema=False)`; concatenate `дата + " " + время`, parse strictly into `registered_at`, map `t/true/1` to `True`, and cast identifiers to strings. Keep the returned value lazy.

- [ ] **Step 5: Add malformed-row quarantine test**

```python
def test_invalid_timestamp_is_quarantined_without_dropping_valid_rows() -> None:
    valid, bad = partition_events([Path("tests/fixtures/events_malformed.csv")])
    assert valid.collect().height == 1
    assert bad.collect().select("quality_reason").item() == "invalid_timestamp"
```

- [ ] **Step 6: Implement `partition_events` and rerun tests**

Run: `cd services/ml && python -m pytest tests/test_csv_reader.py -v`  
Expected: PASS, including one valid and one quarantined row.

- [ ] **Step 7: Commit**

```bash
git add services/ml/src/fire_risk/data services/ml/tests
git commit -m "feat(data): stream event journals with quarantine"
```

## Task 3: Reference joins and coverage report

**Files:**
- Create: `services/ml/src/fire_risk/data/references.py`
- Create: `services/ml/tests/fixtures/channels.csv`
- Create: `services/ml/tests/fixtures/states.csv`
- Create: `services/ml/tests/test_references.py`

**Interfaces:**
- Consumes: canonical event `LazyFrame`, channel and state CSV paths.
- Produces: `join_channels(events, channels) -> pl.LazyFrame` and `build_coverage_report(events, channels, states) -> CoverageReport`.

- [ ] **Step 1: Write a failing unknown-channel preservation test**

```python
def test_unknown_channel_is_preserved_with_quality_flag() -> None:
    joined = join_channels(events_fixture(), channels_fixture()).collect()
    row = joined.filter(pl.col("channel_id") == "missing").row(0, named=True)
    assert row["object_id"] is None
    assert "unknown_channel" in row["quality_flags"]
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_references.py -v`  
Expected: FAIL because `references.py` does not exist.

- [ ] **Step 3: Implement left joins and duplicate validation**

Load channel IDs as strings, reject duplicate `channel_id` values with a `ReferenceIntegrityError`, left-join events, and append `unknown_channel` to `quality_flags` when `object_id` is null.

- [ ] **Step 4: Add coverage report assertions**

```python
def test_coverage_report_counts_unknown_pairs() -> None:
    report = build_coverage_report(events_fixture(), channels_fixture(), states_fixture())
    assert report.total_events == 3
    assert report.unknown_channel_events == 1
    assert report.unmapped_type_value_pairs[("Датчик дыма", "Обнаружен дым")] == 1
```

- [ ] **Step 5: Implement report and run tests**

Run: `cd services/ml && python -m pytest tests/test_references.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ml/src/fire_risk/data/references.py services/ml/tests
git commit -m "feat(data): join references and report coverage"
```

## Task 4: Value normalization

**Files:**
- Create: `services/ml/src/fire_risk/data/normalize.py`
- Create: `services/ml/tests/test_normalize.py`

**Interfaces:**
- Consumes: joined event rows and normalized state mapping.
- Produces: `normalize_value(sensor_type: str, raw_value: str, states: StateIndex, config: PipelineConfig) -> NormalizedValue`.

- [ ] **Step 1: Write failing parameterized tests**

```python
@pytest.mark.parametrize(
    ("sensor_type", "raw", "kind", "numeric", "flags"),
    [
        ("Газовый датчик", "0.75", ValueKind.NUMERIC, 0.75, []),
        ("Газовый датчик", "1.20", ValueKind.NUMERIC, 1.20, ["methane_alarm"]),
        ("Состояние охраны", "01.01.1970 03:00:00", ValueKind.MALFUNCTION, None, ["invalid_epoch_date"]),
        ("Датчик температуры", "-100", ValueKind.MALFUNCTION, None, ["sentinel_value"]),
        ("Датчик дыма", "неизвестный текст", ValueKind.UNKNOWN, None, ["unmapped_state"]),
    ],
)
def test_normalize_value(sensor_type, raw, kind, numeric, flags):
    value = normalize_value(sensor_type, raw, state_index(), PipelineConfig())
    assert value.kind == kind
    assert value.numeric_value == numeric
    assert value.quality_flags == flags
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd services/ml && python -m pytest tests/test_normalize.py -v`  
Expected: FAIL because `normalize_value` does not exist.

- [ ] **Step 3: Implement ordered normalization rules**

Apply rules in this order: known invalid date → configured sentinel → parse numeric → exact state lookup by `(sensor_type, raw_value)` → unknown. For gas numeric values, add `methane_alarm` at `>= config.methane_alarm_percent`.

- [ ] **Step 4: Add contradictory-state test**

```python
def test_conflicting_state_mapping_is_unknown() -> None:
    index = StateIndex({("Газовый датчик", "Температура ниже 3ºC1"): {True, False}})
    value = normalize_value("Газовый датчик", "Температура ниже 3ºC1", index, PipelineConfig())
    assert value.kind == ValueKind.UNKNOWN
    assert value.quality_flags == ["conflicting_state_mapping"]
```

- [ ] **Step 5: Run all normalization tests**

Run: `cd services/ml && python -m pytest tests/test_normalize.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ml/src/fire_risk/data/normalize.py services/ml/tests/test_normalize.py
git commit -m "feat(data): normalize mixed sensor values"
```

## Task 5: Channel-day anomaly detection for 2021

**Files:**
- Create: `services/ml/src/fire_risk/data/quality.py`
- Create: `services/ml/tests/test_quality.py`

**Interfaces:**
- Consumes: normalized event `LazyFrame`.
- Produces: `profile_channel_days(events) -> pl.LazyFrame` and `mark_historical_artifacts(events, profiles, thresholds) -> pl.LazyFrame`.

- [ ] **Step 1: Write a failing targeted-quarantine test**

```python
def test_anomalous_day_does_not_exclude_entire_2021() -> None:
    marked = mark_historical_artifacts(events_across_two_days(), thresholds_fixture()).collect()
    bad = marked.filter(pl.col("registered_at").dt.date() == date(2021, 5, 4))
    good = marked.filter(pl.col("registered_at").dt.date() == date(2021, 5, 5))
    assert bad["exclude_from_fire_training"].all()
    assert not good["exclude_from_fire_training"].any()
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_quality.py -v`  
Expected: FAIL because quality functions do not exist.

- [ ] **Step 3: Implement channel-day profiles**

Calculate event count, alarms, unique values, maximum repeats per second, longest identical-state run and event-rate deviation from the channel's rolling median. Thresholds are supplied through a typed `QualityThresholds` config.

- [ ] **Step 4: Implement interval flags without year-level exclusion**

Add `burst`, `stuck`, `historical_artifact` and `exclude_from_fire_training` per event by joining channel-day profiles. Never filter by `source_year == 2021` alone.

- [ ] **Step 5: Run quality and regression tests**

Run: `cd services/ml && python -m pytest tests/test_quality.py tests/test_csv_reader.py tests/test_normalize.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ml/src/fire_risk/data/quality.py services/ml/tests/test_quality.py
git commit -m "feat(data): quarantine channel-level historical artifacts"
```

## Task 6: Picket parser and deterministic device age

**Files:**
- Create: `services/ml/src/fire_risk/data/pickets.py`
- Create: `services/ml/src/fire_risk/data/device_metadata.py`
- Create: `services/ml/tests/test_pickets.py`
- Create: `services/ml/tests/test_device_metadata.py`

**Interfaces:**
- Consumes: channel names and first-seen dates.
- Produces: `parse_picket(name: str) -> ParsedPicket`, `estimate_device_metadata(channel, first_seen, seed) -> DeviceMetadata`.

- [ ] **Step 1: Write failing picket examples**

```python
@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("Дым Д1 ПК3", "ПК3"),
        ("ТД ПК 87", "ПК 87"),
        ("Дым ПК145+3", "ПК145+3"),
        ("ГРО ПК86-85", "ПК86-85"),
        ("УИР-Р ПК29–231", "ПК29–231"),
    ],
)
def test_parse_picket_preserves_raw(name, raw):
    assert parse_picket(name).raw == raw
```

- [ ] **Step 2: Add unlocated test**

```python
def test_name_without_picket_is_unlocated() -> None:
    result = parse_picket("Датчик в венткамере")
    assert result.raw is None
    assert result.sort_key is None
    assert result.location_group == "unlocated"
```

- [ ] **Step 3: Run tests and implement parser**

Run before implementation: `cd services/ml && python -m pytest tests/test_pickets.py -v`  
Expected: FAIL. Implement Unicode-aware regex patterns, preserve the matched text, and calculate only a relative sort key. Rerun and expect PASS.

- [ ] **Step 4: Write deterministic age test**

```python
def test_generated_age_is_stable_for_channel_and_seed() -> None:
    first = estimate_device_metadata(channel_fixture(), date(2019, 1, 1), seed=42)
    second = estimate_device_metadata(channel_fixture(), date(2019, 1, 1), seed=42)
    assert first.estimated_install_date == second.estimated_install_date
    assert first.age_source == "generated_demo"
    assert first.is_synthetic is True
```

- [ ] **Step 5: Implement metadata estimation and run tests**

For channels first seen after the left-censoring cutoff, use `first_seen`; otherwise sample a deterministic prehistory from configured ranges by sensor type. Persist `age_source` and `is_synthetic`.

Run: `cd services/ml && python -m pytest tests/test_pickets.py tests/test_device_metadata.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ml/src/fire_risk/data/pickets.py services/ml/src/fire_risk/data/device_metadata.py services/ml/tests
git commit -m "feat(data): parse pickets and estimate demo device age"
```

## Task 7: Episode builder

**Files:**
- Create: `services/ml/src/fire_risk/data/episodes.py`
- Create: `services/ml/tests/test_episodes.py`

**Interfaces:**
- Consumes: normalized, quality-marked events sorted by object and time.
- Produces: `build_episodes(events: pl.LazyFrame, gap: timedelta) -> tuple[pl.LazyFrame, pl.LazyFrame]` returning episodes and event-to-episode membership.

- [ ] **Step 1: Write failing grouping tests**

```python
def test_repeated_events_inside_gap_form_one_episode() -> None:
    episodes, membership = build_episodes(events_at_minutes(0, 4, 12), timedelta(minutes=30))
    assert episodes.collect().height == 1
    assert membership.collect()["episode_id"].n_unique() == 1


def test_event_after_gap_starts_new_episode() -> None:
    episodes, _ = build_episodes(events_at_minutes(0, 31), timedelta(minutes=30))
    assert episodes.collect().height == 2
```

- [ ] **Step 2: Run tests and verify failure**

Run: `cd services/ml && python -m pytest tests/test_episodes.py -v`  
Expected: FAIL because `build_episodes` does not exist.

- [ ] **Step 3: Implement object-scoped sessionization**

Within each `object_id`, sort by `registered_at`, calculate the gap from the previous relevant event, start a new session when gap is greater than the configured threshold, and derive deterministic `episode_id` from object and start time.

- [ ] **Step 4: Add object-boundary and unlocated tests**

```python
def test_same_time_on_two_objects_creates_two_episodes() -> None:
    episodes, _ = build_episodes(two_objects_same_time(), timedelta(minutes=30))
    assert episodes.collect().height == 2


def test_event_without_picket_remains_in_episode() -> None:
    episodes, membership = build_episodes(unlocated_event(), timedelta(minutes=30))
    assert membership.collect().height == 1
    assert episodes.collect()["picket_from"].item() is None
```

- [ ] **Step 5: Run tests**

Run: `cd services/ml && python -m pytest tests/test_episodes.py -v`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/ml/src/fire_risk/data/episodes.py services/ml/tests/test_episodes.py
git commit -m "feat(data): group sensor events into object episodes"
```

## Task 8: Replaceable label providers

**Files:**
- Create: `services/ml/src/fire_risk/data/labels.py`
- Create: `services/ml/tests/test_labels.py`

**Interfaces:**
- Consumes: `IncidentEpisode` records or future decision-journal rows.
- Produces: `LabelProvider.get_incidents(start, end, object_ids) -> list[IncidentLabel]`, `ProxyLabelProvider`, `DecisionJournalLabelProvider`.

- [ ] **Step 1: Write the provider contract test**

```python
def test_proxy_and_decision_providers_return_same_contract() -> None:
    proxy = ProxyLabelProvider(proxy_config()).get_incidents(start, end, {"42"})
    real = DecisionJournalLabelProvider(decision_fixture()).get_incidents(start, end, {"42"})
    assert type(proxy[0]) is IncidentLabel
    assert type(real[0]) is IncidentLabel
    assert proxy[0].source == "proxy"
    assert real[0].source == "dispatcher"
```

- [ ] **Step 2: Run the contract test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_labels.py -v`  
Expected: FAIL because providers do not exist.

- [ ] **Step 3: Implement abstract and decision-journal providers**

Define a `Protocol` for `get_incidents`. Validate decisions against the exact enum in the spec, require `object_id` and `started_at`, and preserve unknown outcomes as `decision="unknown"` rather than dropping them.

- [ ] **Step 4: Implement proxy provider without feature coupling**

Proxy rules may inspect future episode composition but must not import the future feature-builder module. Store rule version and confidence on every label. Exclude episodes marked `historical_artifact` from fire proxy labels.

- [ ] **Step 5: Add malformed real-label test**

```python
def test_decision_without_object_is_rejected_with_row_number() -> None:
    with pytest.raises(LabelImportError, match="row 2.*object_id"):
        DecisionJournalLabelProvider(decision_without_object_fixture())
```

- [ ] **Step 6: Run the complete data-foundation test suite**

Run: `cd services/ml && python -m pytest -v && python -m ruff check src tests && python -m mypy src`  
Expected: all tests and checks pass.

- [ ] **Step 7: Commit**

```bash
git add services/ml/src/fire_risk/data/labels.py services/ml/tests/test_labels.py
git commit -m "feat(data): add replaceable incident label providers"
```

## Task 9: Reproducible Parquet outputs and CLI

**Files:**
- Create: `services/ml/src/fire_risk/cli.py`
- Create: `services/ml/tests/test_cli.py`
- Create: `services/ml/README.md`

**Interfaces:**
- Consumes: source paths and `PipelineConfig`.
- Produces: versioned `normalized_events.parquet`, `episodes.parquet`, `episode_membership.parquet`, `incident_labels.parquet`, `coverage.json`, `quality_report.json`.

- [ ] **Step 1: Write a failing end-to-end fixture test**

```python
def test_prepare_command_writes_versioned_outputs(tmp_path: Path) -> None:
    result = runner.invoke(app, [
        "prepare", "--events", "tests/fixtures/events.csv",
        "--channels", "tests/fixtures/channels.csv",
        "--states", "tests/fixtures/states.csv",
        "--output", str(tmp_path), "--run-id", "test-run",
    ])
    assert result.exit_code == 0
    assert (tmp_path / "test-run" / "normalized_events.parquet").exists()
    assert (tmp_path / "test-run" / "quality_report.json").exists()
```

- [ ] **Step 2: Run test and verify failure**

Run: `cd services/ml && python -m pytest tests/test_cli.py -v`  
Expected: FAIL because CLI does not exist.

- [ ] **Step 3: Implement the `prepare` command**

Wire the modules in task order, create a run manifest containing source file names, sizes, configuration hash, timestamps and row counts, then sink lazy results directly to Parquet.

- [ ] **Step 4: Document exact commands**

Document environment installation, fixture execution and full dataset execution in `services/ml/README.md`. Include the expected output tree and explain that source files are never modified.

- [ ] **Step 5: Run all checks and a fixture build**

Run: `cd services/ml && python -m pytest -v && python -m ruff check src tests && python -m mypy src && python -m fire_risk.cli prepare --events tests/fixtures/events.csv --channels tests/fixtures/channels.csv --states tests/fixtures/states.csv --output .artifacts --run-id smoke-test`  
Expected: tests/checks pass; `.artifacts/smoke-test/` contains all six outputs and a manifest.

- [ ] **Step 6: Commit**

```bash
git add services/ml
git commit -m "feat(data): add reproducible preparation pipeline"
```

## Phase completion gate

- [ ] Run: `cd services/ml && python -m pytest -v` — expected PASS.
- [ ] Run: `cd services/ml && python -m ruff check src tests` — expected PASS.
- [ ] Run: `cd services/ml && python -m mypy src` — expected PASS.
- [ ] Run the fixture CLI twice with the same `run-id` inputs and compare manifests excluding wall-clock fields — expected identical configuration and row counts.
- [ ] Inspect coverage and quality reports; unknown channels, conflicting states and quarantined rows must be explicit non-negative counts.
- [ ] Confirm no source CSV changed by comparing hashes before and after the fixture run.
- [ ] Request independent review against `tasks/prd-fire-risk-mvp.md` and the technical specification.
