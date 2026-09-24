# Fire Risk DATA Acceptance v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the DATA foundation so the complete 2019–2026 corpus can be processed from the authoritative Russian references into causal features, provider-bounded targets, a versioned proxy incident journal, and deterministic resumable artifacts.

**Architecture:** Keep event ingestion and canonical domain contracts separate from reference-schema adaptation. Build all features from normalized events plus an immutable channel inventory, build all labels through a replaceable `LabelProvider`, calibrate quality thresholds only from train-period channel-day profiles, and orchestrate the full run as identity-checked atomic stages. Generated profiles, thresholds, Parquet, and reports remain ignored artifacts; only code, schemas, tests, and documentation enter Git.

**Tech Stack:** Python 3.12, Polars, PyArrow, Pydantic 2, Typer, pytest, Ruff, mypy, SHA-256.

**Spec:** `docs/superpowers/specs/2026-09-24-fire-risk-data-acceptance-v2-design.md`

## Global Constraints

- Work only on `feature/data-foundation`; do not merge `main`.
- Treat all journal and reference CSV files as immutable and never add them to Git.
- Use `--source-timezone Europe/Moscow` for the full run, while keeping the option configurable and recording it as an assumption.
- Use only 2019–2020, admissible 2021 intervals, and 2022–2024 to calibrate thresholds; 2025 and 2026 are read only after thresholds are frozen.
- A horizon is available exactly when `t + horizon <= LabelProvider.observed_until`; unavailable targets are null and excluded from that horizon's training set.
- Feature values at `t` may use only events with `registered_at <= t`; future state endings and later channel events are forbidden.
- Same-alarm state mappings with several `state_set_id` values are known states and retain every sorted ID; only simultaneous normalized `true` and `false` is a conflict.
- Save channel-day profiles and calibrated thresholds as reusable intermediates, and invalidate a stage plus its downstream stages when its recorded identity changes.
- Equal source SHA-256 values, canonical configuration, seed, schema versions, and implementation revision must produce equal data and non-clock statistics.
- After every task run its focused tests, the full pytest suite, Ruff, and mypy; obtain an independent reviewer verdict before committing and starting the next task.

## Review Focus

- UTF-8 BOM, canonically equivalent Unicode header spelling, or shuffled exact Russian columns must either adapt deterministically or fail with the actual missing/unexpected names; Task 1 pins this behavior.
- A provider coverage boundary inside an incident-free tail must censor by `observed_until`, not by the final event or label; Task 2 pins this behavior.
- A channel present in inventory but never observed by `t` must remain in the freshness denominator and be stale; Task 4 pins this behavior.
- A saved calibration profile containing 2025 or 2026 must be rejected rather than silently contaminating thresholds; Task 6 pins this behavior.
- An interrupted stage or an identity mismatch must never be treated as complete, and an atomic temporary output must not shadow the last valid artifact; Task 7 pins this behavior.

---

## File Structure

```text
services/ml/
├── README.md                              # full-run command, assumptions, artifacts
├── src/fire_risk/
│   ├── contracts.py                       # canonical reference, mapping, and label contracts
│   ├── cli.py                             # thin Typer entry point
│   └── data/
│       ├── references.py                  # Russian/canonical adapters and coverage
│       ├── normalize.py                   # state lookup and conflict behavior
│       ├── labels.py                      # provider boundary and proxy rules
│       ├── features.py                    # causal temporal features and targets
│       ├── inventory.py                   # object channel inventory and freshness
│       ├── calibration.py                 # train-only threshold fitting and serialization
│       ├── run_report.py                  # deterministic report aggregations
│       └── pipeline.py                    # resumable two-pass stage orchestration
└── tests/
    ├── fixtures/
    │   ├── channels_russian.csv
    │   └── states_russian.csv
    ├── test_references.py
    ├── test_normalize.py
    ├── test_labels.py
    ├── test_features.py
    ├── test_inventory.py
    ├── test_calibration.py
    ├── test_run_report.py
    ├── test_pipeline.py
    └── test_cli.py
```

## Task 1: Authoritative Russian reference adapters

**Files:**
- Modify: `services/ml/src/fire_risk/contracts.py`
- Modify: `services/ml/src/fire_risk/data/references.py`
- Modify: `services/ml/src/fire_risk/data/normalize.py`
- Create: `services/ml/tests/fixtures/channels_russian.csv`
- Create: `services/ml/tests/fixtures/states_russian.csv`
- Modify: `services/ml/tests/test_references.py`
- Modify: `services/ml/tests/test_normalize.py`

**Interfaces:**
- Consumes: a path whose header is either the exact authoritative Russian schema or the canonical schema.
- Produces: `scan_channel_reference(path: Path) -> pl.LazyFrame`, `scan_state_reference(path: Path) -> pl.LazyFrame`, and `load_state_index(path: Path) -> StateIndex`.
- Produces mapping rows with `sensor_type: str`, `state_name: str`, `alarm_flag: bool | None`, `state_set_ids: list[str]`, and `is_conflicting: bool`.

- [ ] **Step 1: Add minimal real-header fixtures**

```csv
ид_канала_данных,тип_инж_системы,тип_датчика,название_датчика,ид_объект,иерархия_уровень,диспетчерское_название_объекта,родитель,Имя,объект_ур2,объект_ур2_имя,объект_ур1,объект_ур1_имя
120578,ПС,Датчик дыма,Дым ПК3,42,3,Объект 42,10,Источник 120578,20,Участок,1,Линия
```

```csv
тип_датчика,ид_набор_состояний,название_состояния,тревожное
КД Дверь,2,Норма,false
КД Дверь,1,Норма,false
КД Дверь,1,Норма,false
Газовый датчик,13,Температура ниже 3ºC1,false
Газовый датчик,13,Температура ниже 3ºC1,true
```

- [ ] **Step 2: Write failing adapter and integrity tests**

```python
def test_exact_russian_channel_headers_map_without_manual_rename() -> None:
    row = scan_channel_reference(FIXTURES / "channels_russian.csv").collect().row(
        0, named=True
    )
    assert row["channel_id"] == "120578"
    assert row["object_id"] == "42"
    assert row["object_name"] == "Объект 42"


def test_same_alarm_multiple_state_sets_are_known_and_preserved() -> None:
    mapping = scan_state_reference(FIXTURES / "states_russian.csv").collect()
    row = mapping.filter(pl.col("state_name") == "Норма").row(0, named=True)
    assert row["alarm_flag"] is False
    assert row["state_set_ids"] == ["1", "2"]
    assert row["is_conflicting"] is False


def test_true_false_state_variants_are_the_only_conflict() -> None:
    index = load_state_index(FIXTURES / "states_russian.csv")
    value = normalize_value(
        "Газовый датчик", "Температура ниже 3ºC1", index, PipelineConfig()
    )
    assert value.kind == ValueKind.UNKNOWN
    assert value.quality_flags == ["conflicting_state_mapping"]
```

Add cases for canonical headers, UTF-8 BOM, shuffled columns, exact duplicate collapse, a partial Russian schema, and one unexpected header. Partial/unknown schemas must raise `ReferenceIntegrityError` listing missing and unexpected columns.

- [ ] **Step 3: Run the tests and confirm the expected failures**

Run: `cd services/ml && python -m pytest tests/test_references.py tests/test_normalize.py -v`  
Expected: FAIL because the existing scanners select only canonical headers and treat multiple state-set IDs as conflicts.

- [ ] **Step 4: Implement schema detection and canonical projection**

Define immutable maps in `references.py`:

```python
CHANNEL_RU_TO_CANONICAL = {
    "ид_канала_данных": "channel_id",
    "тип_инж_системы": "engineering_system_type",
    "тип_датчика": "sensor_type",
    "название_датчика": "sensor_name",
    "ид_объект": "object_id",
    "иерархия_уровень": "object_level",
    "диспетчерское_название_объекта": "object_name",
    "объект_ур2": "level2_object_id",
    "объект_ур2_имя": "level2_object_name",
    "объект_ур1": "level1_object_id",
    "объект_ур1_имя": "level1_object_name",
}
STATE_RU_TO_CANONICAL = {
    "тип_датчика": "sensor_type",
    "ид_набор_состояний": "state_set_id",
    "название_состояния": "state_name",
    "тревожное": "alarm_flag",
}
```

Read headers with `utf-8-sig`, validate the complete schema before scanning, retain `родитель` and `Имя` only as accepted source metadata, and cast IDs to strings. Normalize alarm tokens through one strict expression, call `.unique()` to collapse exact rows, group on `(sensor_type, state_name)`, sort/deduplicate `state_set_ids`, and set `is_conflicting` only when `alarm_flag.n_unique() > 1`.

- [ ] **Step 5: Route all reference consumers through the adapters**

Replace direct `pl.scan_csv(channels)` and `pl.read_csv(states)` calls in `join_channels`, `build_coverage_report`, and CLI normalization with the new interfaces. Make the coverage report count same-alarm/multiple-set pairs as covered and true/false pairs as conflicts.

- [ ] **Step 6: Verify Task 1**

Run: `cd services/ml && python -m pytest tests/test_references.py tests/test_normalize.py -v`  
Run: `cd services/ml && python -m pytest -v`  
Run: `cd services/ml && python -m ruff check src tests`  
Run: `cd services/ml && python -m mypy src`  
Expected: every command exits 0.

- [ ] **Step 7: Independent review and commit**

Assign a fresh reviewer to compare Task 1 against Sections 2–3 and 12.1–12.5 of the v2 spec. Fix every Critical/Important finding, rerun Step 6, then commit:

```bash
git add services/ml/src/fire_risk/contracts.py services/ml/src/fire_risk/data/references.py services/ml/src/fire_risk/data/normalize.py services/ml/tests
git commit -m "feat(data): adapt authoritative Russian references"
```

## Task 2: Provider-owned observation boundary and censored targets

**Files:**
- Modify: `services/ml/src/fire_risk/data/labels.py`
- Modify: `services/ml/src/fire_risk/data/features.py`
- Modify: `services/ml/tests/test_labels.py`
- Modify: `services/ml/tests/test_features.py`

**Interfaces:**
- Consumes: `LabelProvider.observed_until: datetime` and provider incident rows.
- Produces: `attach_horizon_targets(snapshots, incidents, observed_until) -> pl.LazyFrame` with nullable `target_now`, `target_6h`, `target_12h`, `target_24h` and non-null Boolean `target_*_available` columns.
- Preserves: `LabelProvider.get_incidents(start, end, object_ids) -> list[IncidentLabel]` so a real provider replaces the proxy without changing features.

- [ ] **Step 1: Write failing provider-boundary tests**

```python
def test_providers_expose_explicit_timezone_aware_observed_until() -> None:
    boundary = datetime(2026, 12, 31, tzinfo=UTC)
    provider = ProxyLabelProvider(
        ProxyLabelConfig(episodes=[], observed_until=boundary)
    )
    assert provider.observed_until == boundary


def test_observed_until_is_not_inferred_from_last_incident() -> None:
    boundary = datetime(2026, 12, 31, tzinfo=UTC)
    provider = DecisionJournalLabelProvider([], observed_until=boundary)
    assert provider.get_incidents(start, boundary, {"42"}) == []
    assert provider.observed_until == boundary
```

Also assert that a naive boundary is rejected and that a query end after the boundary does not mutate the stored boundary.

- [ ] **Step 2: Write failing independent-horizon censoring tests**

```python
def test_targets_are_null_when_their_complete_window_is_unobserved() -> None:
    score = datetime(2026, 1, 1, tzinfo=UTC)
    result = attach_horizon_targets(
        snapshots_at(score), no_incidents(), score + timedelta(hours=10)
    ).collect().row(0, named=True)
    assert result["target_now_available"] is True
    assert result["target_6h_available"] is True
    assert result["target_12h_available"] is False
    assert result["target_24h_available"] is False
    assert result["target_6h"] is False
    assert result["target_12h"] is None
    assert result["target_24h"] is None
```

Add exact-boundary cases for 6h/12h/24h and a regression asserting that censored rows cannot be selected as negative training rows by filtering `target_*_available`.

- [ ] **Step 3: Run the tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_labels.py tests/test_features.py -v`  
Expected: FAIL because providers lack the explicit boundary and the target builder converts absent futures to `False`.

- [ ] **Step 4: Implement the provider contract and target mask**

Add `observed_until` to `LabelProvider`, `ProxyLabelConfig`, both concrete providers, and validate timezone awareness. In `attach_horizon_targets`, compute availability before target values:

```python
available = pl.col("scoring_timestamp") + pl.duration(hours=hours) <= observed_until
pl.when(available).then(raw_target).otherwise(None).alias(f"target_{hours}h")
available.alias(f"target_{hours}h_available")
```

Use `scoring_timestamp <= observed_until` for `now`; preserve target monotonicity only among available horizons. Do not inspect event or incident maxima when calculating availability.

- [ ] **Step 5: Verify Task 2**

Run the focused tests, then full pytest, Ruff, and mypy using the four commands from Task 1 Step 6. Expected: all exit 0.

- [ ] **Step 6: Independent review and commit**

Assign a fresh reviewer to Sections 4 and 12.6–12.7. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/data/labels.py services/ml/src/fire_risk/data/features.py services/ml/tests/test_labels.py services/ml/tests/test_features.py
git commit -m "feat(data): censor targets at provider coverage boundary"
```

## Task 3: Causal duration, slope, variability, and entropy features

**Files:**
- Modify: `services/ml/src/fire_risk/data/features.py`
- Modify: `services/ml/tests/test_features.py`

**Interfaces:**
- Consumes: normalized event rows and the existing object scoring grid.
- Produces per-window duration, slope, variability, and entropy columns for `5m`, `30m`, `3h`, `6h`, and `24h`.
- Guarantees: appending rows after `t` cannot alter any value at `t`.

- [ ] **Step 1: Write failing state-duration tests**

Build one channel with state changes at `t-40m`, `t-10m`, and `t+5m`. Assert at `t` that duration starts at `t-10m`, ends at `t`, clips independently to each window, and never uses the future transition. Add malfunction-state rows and assert `malfunction_duration_seconds_<window>` and maxima follow the same rule.

- [ ] **Step 2: Write failing slope tests**

```python
def test_slopes_use_only_points_at_or_before_t_and_need_two_times() -> None:
    before = snapshot(gas_points=[(-20, 0.2), (-10, 0.4)], future=[(5, 9.0)])
    assert before["gas_slope_per_hour_30m"] == pytest.approx(1.2)
    assert before["gas_slope_per_hour_5m"] is None
```

Add equivalent temperature coverage and a repeated-timestamp case whose zero time variance yields null.

- [ ] **Step 3: Write failing window-local variability and entropy tests**

Use distinct distributions in 5m and 30m windows. Assert numeric sample standard deviation is calculated per signal family and per window, entropy uses `(channel_id, raw_value)` categories, one category gives `0.0`, and an empty window gives null. Append a future category and assert the past frame is unchanged.

- [ ] **Step 4: Run the feature tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_features.py -v`  
Expected: FAIL because the new columns do not exist.

- [ ] **Step 5: Implement causal expressions**

Extend the internal event timeline with per-channel previous-state timestamps computed only after sorting by `(object_id, channel_id, registered_at, event_id)`. At each snapshot, aggregate active duration from the last known change and clip with `min(t - change_at, window)`. Calculate least-squares slope in hours as covariance(time, value) divided by time variance and guard fewer than two distinct timestamps. Calculate `std(ddof=1)` and Shannon entropy `-sum(p * log2(p))` inside each rolling window.

Keep feature names stable:

```text
active_state_duration_seconds_<window>
max_active_state_duration_seconds_<window>
malfunction_duration_seconds_<window>
max_malfunction_duration_seconds_<window>
gas_slope_per_hour_<window>
temperature_slope_per_hour_<window>
gas_variability_<window>
temperature_variability_<window>
state_entropy_<window>
```

- [ ] **Step 6: Verify Task 3**

Run focused tests, full pytest, Ruff, and mypy. Expected: all exit 0.

- [ ] **Step 7: Independent review and commit**

Assign a fresh reviewer to Sections 5.2–5.4 and 12.8–12.10. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/data/features.py services/ml/tests/test_features.py
git commit -m "feat(data): add causal temporal feature families"
```

## Task 4: Reference inventory and causal freshness

**Files:**
- Create: `services/ml/src/fire_risk/data/inventory.py`
- Modify: `services/ml/src/fire_risk/data/features.py`
- Create: `services/ml/tests/test_inventory.py`
- Modify: `services/ml/tests/test_features.py`

**Interfaces:**
- Consumes: canonical channel reference and event history.
- Produces: `build_object_inventory(channels: pl.LazyFrame) -> tuple[pl.LazyFrame, pl.LazyFrame]`, returning object totals and an object/type mapping table.
- Extends: `build_feature_snapshots(events, config, inventory=None) -> pl.LazyFrame` with inventory and 24-hour freshness columns.

- [ ] **Step 1: Write failing inventory tests**

```python
def test_inventory_counts_reference_channels_not_observed_events() -> None:
    totals, by_type = build_object_inventory(reference_with_three_channels())
    assert totals.collect()["inventory_channel_count"].item() == 3
    assert by_type.collect().filter(pl.col("sensor_type") == "Датчик дыма")[
        "channel_count"
    ].item() == 2
```

Assert duplicate channel IDs are rejected and output ordering is stable by object/type.

- [ ] **Step 2: Write failing freshness tests**

Create three inventory channels: one seen within 24h at `t`, one last seen earlier, and one never seen. Assert `fresh_channel_count=1`, `stale_channel_count=2`, `stale_channel_share=2/3`, and that events after `t` do not change the result. Add per-family smoke/heat/gas inventory and freshness assertions.

- [ ] **Step 3: Run tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_inventory.py tests/test_features.py -v`  
Expected: FAIL because inventory/freshness interfaces are absent.

- [ ] **Step 4: Implement inventory tables and as-of freshness**

Build inventory only from reference rows. For each scoring timestamp, obtain each inventory channel's latest event with `registered_at <= t` using a backward as-of join. Treat null last-seen as stale; otherwise fresh means `last_seen > t - 24h`. Aggregate totals and stable scalar family counts, and retain the exact per-type table as its own Parquet output.

- [ ] **Step 5: Verify Task 4**

Run focused tests, full pytest, Ruff, and mypy. Expected: all exit 0.

- [ ] **Step 6: Independent review and commit**

Assign a fresh reviewer to Sections 5.5 and 12.11–12.12. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/data/inventory.py services/ml/src/fire_risk/data/features.py services/ml/tests/test_inventory.py services/ml/tests/test_features.py
git commit -m "feat(data): derive inventory and causal freshness"
```

## Task 5: Versioned proxy incident journal and label statistics

**Files:**
- Modify: `services/ml/src/fire_risk/contracts.py`
- Modify: `services/ml/src/fire_risk/data/labels.py`
- Create: `services/ml/src/fire_risk/data/run_report.py`
- Modify: `services/ml/tests/test_labels.py`
- Create: `services/ml/tests/test_run_report.py`

**Interfaces:**
- Consumes: alarm-composition episodes after quality exclusions.
- Produces: proxy `IncidentLabel` rows containing `rule_version`, deterministic `rule_id`, and sorted `sensor_combination`.
- Produces: `build_label_report(labels, targets, feature_columns) -> dict[str, object]`.

- [ ] **Step 1: Write failing proxy-rule tests**

Parameterize the approved rules: smoke+heat, smoke+manual call point, smoke+UIR-R, smoke/heat+supporting pump, methane alarm+another fire signal, and configured coordinated mass alarm across distinct channels/types. For every rule assert stable incident ID, rule ID, version, confidence, and sorted sensor combination.

Add negative cases where the same patterns include only technical malfunction states, any `historical_artifact`, or `exclude_from_fire_training=True`; no proxy incident may be produced. Assert the proxy module does not import `features`.

- [ ] **Step 2: Write failing report tests**

```python
def test_run_report_explains_proxy_semantics_and_target_counts() -> None:
    report = build_label_report(labels(), targets(), feature_columns())
    assert report["proxy_rule_version"] == "smvu-proxy-v2"
    assert report["targets"]["6h"] == {
        "available": 3, "censored": 1, "positive": 1, "negative": 2
    }
    assert "not detection quality for confirmed real fires" in report["warning"]
```

Assert incident distributions are grouped by year, object, rule, and sorted sensor combination; class balance exists for now/6h/12h/24h; and feature/rule overlap lists shared signal families without importing feature values into label generation.

- [ ] **Step 3: Run tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_labels.py tests/test_run_report.py -v`  
Expected: FAIL because v2 proxy metadata and report aggregation are absent.

- [ ] **Step 4: Implement proxy v2 and deterministic report aggregation**

Make pattern evaluation a pure function over alarming episode composition and quality flags. Record the exact matching rule, use stable sorted inputs for incident IDs, and retain the `LabelProvider` boundary from Task 2. Implement report dictionaries with sorted keys/lists and no current timestamps.

- [ ] **Step 5: Verify Task 5**

Run focused tests, full pytest, Ruff, and mypy. Expected: all exit 0.

- [ ] **Step 6: Independent review and commit**

Assign a fresh reviewer to Sections 6, 10, and 12.16–12.17. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/contracts.py services/ml/src/fire_risk/data/labels.py services/ml/src/fire_risk/data/run_report.py services/ml/tests/test_labels.py services/ml/tests/test_run_report.py
git commit -m "feat(data): version proxy incidents and label reporting"
```

## Task 6: Leakage-free train-only quality calibration

**Files:**
- Create: `services/ml/src/fire_risk/data/calibration.py`
- Modify: `services/ml/src/fire_risk/data/quality.py`
- Modify: `services/ml/src/fire_risk/data/features.py`
- Create: `services/ml/tests/test_calibration.py`
- Modify: `services/ml/tests/test_quality.py`
- Modify: `services/ml/tests/test_features.py`

**Interfaces:**
- Consumes: saved channel-day profiles and their source years.
- Produces: `CalibratedThresholds` with `schema_version`, `calibration_version`, `train_periods`, `source_sha256`, `seed`, rationale, and typed `QualityThresholds`.
- Produces: `calibrate_thresholds(profiles, source_hashes, seed) -> CalibratedThresholds`, `write_calibration(path, value)`, and `read_calibration(path) -> CalibratedThresholds`.

- [ ] **Step 1: Write failing split-isolation tests**

Create profiles whose 2025/2026 values would materially change every quantile. Assert calibration results are byte-for-byte equal with those rows removed. Assert admissible 2021 rows are retained and only rows already carrying `historical_artifact`/`exclude_from_fire_training` are removed.

- [ ] **Step 2: Write failing contamination and serialization tests**

```python
def test_calibration_rejects_validation_or_test_profiles() -> None:
    with pytest.raises(CalibrationLeakageError, match="2025|2026"):
        calibrate_thresholds(profiles_with_2026_only(), hashes(), seed=42)


def test_frozen_thresholds_round_trip_canonically(tmp_path: Path) -> None:
    value = calibrate_thresholds(train_profiles(), hashes(), seed=42)
    write_calibration(tmp_path / "thresholds.json", value)
    assert read_calibration(tmp_path / "thresholds.json") == value
```

Also assert sorted source hashes, stable float serialization, explicit train ranges, and version mismatch rejection.

- [ ] **Step 3: Run tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_calibration.py tests/test_quality.py -v`  
Expected: FAIL because calibration is absent and fixed defaults are used directly.

- [ ] **Step 4: Implement deterministic robust calibration**

Filter to years 2019–2024 before aggregation, reject any remaining out-of-split year, and exclude only pre-flagged inadmissible channel-days. Derive integer thresholds with explicit rounding from robust train quantiles and enforce safe lower bounds from the typed schema. Serialize canonical JSON with sorted keys and record the calibration rationale and exact periods:

```text
2019-01-01..2020-12-31
2021-01-01..2021-12-31 (admissible intervals only)
2022-01-01..2024-12-31
```

Do not expose an API that accepts validation/test frames as calibration inputs.

- [ ] **Step 5: Apply only the loaded frozen configuration downstream**

Change quality marking callers to require `QualityThresholds` supplied by calibration/loading. Remove implicit `QualityThresholds()` construction from production feature paths; test helpers may still construct fixtures explicitly.

- [ ] **Step 6: Verify Task 6**

Run focused tests, full pytest, Ruff, and mypy. Expected: all exit 0.

- [ ] **Step 7: Independent review and commit**

Assign a fresh reviewer to Sections 7 and 12.13–12.14, specifically asking them to trace every 2025/2026 code path. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/data/calibration.py services/ml/src/fire_risk/data/quality.py services/ml/src/fire_risk/data/features.py services/ml/tests/test_calibration.py services/ml/tests/test_quality.py services/ml/tests/test_features.py
git commit -m "feat(data): calibrate quality thresholds on train only"
```

## Task 7: Resumable two-pass pipeline, manifest, and CLI

**Files:**
- Create: `services/ml/src/fire_risk/data/pipeline.py`
- Modify: `services/ml/src/fire_risk/data/run_report.py`
- Modify: `services/ml/src/fire_risk/cli.py`
- Create: `services/ml/tests/test_pipeline.py`
- Modify: `services/ml/tests/test_cli.py`
- Modify: `services/ml/README.md`

**Interfaces:**
- Consumes: journals, authoritative references, canonical config, `source_timezone`, seed, output directory, and explicit temp directory.
- Produces the staged artifact names from v2 spec Section 8 and completion records containing `stage`, `input_identity`, `output_sha256`, `schema_version`, and non-clock statistics.
- Produces: `run_full(config: FullRunConfig) -> RunResult` and keeps Typer `prepare` as a thin adapter.

- [ ] **Step 1: Write failing identity and invalidation tests**

Assert run identity changes when any source hash, canonical config field, seed, schema version, or implementation revision changes. Assert timezone is part of identity. Assert changing a stage input invalidates that stage and all downstream stages but leaves upstream profile artifacts reusable.

- [ ] **Step 2: Write failing interruption and atomicity tests**

Simulate a writer failure before atomic rename. Assert no completion marker exists, the prior valid artifact remains readable, and rerun rebuilds the incomplete stage. Put a mismatched identity into a completion record and assert it is never reused.

- [ ] **Step 3: Write failing two-pass and reporting integration tests**

Use fixture journals across 2019–2026. Assert stage 10 writes channel-day profiles; stage 20 calibrates only 2019–2024 admissible rows; pass 2 loads the exact frozen threshold values for 2025/2026. Assert outputs include object inventory, normalized events, episodes, membership, proxy labels, feature snapshots, coverage, quality report, run report, and manifest.

Assert `run_report.json` contains rows by year, channel→object coverage, unknown states, excluded 2021 intervals, proxy distributions, every horizon's availability/class counts, rule/feature overlap, and the proxy warning. Assert the second identical run reuses completed stages and matches Parquet hashes and all report/manifest content after removing only explicitly named clock fields.

- [ ] **Step 4: Run tests and confirm failure**

Run: `cd services/ml && python -m pytest tests/test_pipeline.py tests/test_cli.py -v`  
Expected: FAIL because the current CLI is a monolithic one-pass build without hashed stages or run report.

- [ ] **Step 5: Implement stage orchestration**

Create ordered stage specifications for:

```text
00-source-inventory.json
10-channel-day-profiles.parquet
20-calibrated-thresholds.json
30-normalized-events.parquet
31-object-inventory.parquet
32-object-inventory-by-type.parquet
40-episodes.parquet
41-episode-membership.parquet
50-incident-labels.parquet
60-feature-snapshots.parquet
70-coverage.json
71-quality-report.json
72-run-report.json
manifest.json
```

Hash every source before reading. Write each output to a sibling temporary path, fsync/close it, atomically replace the final path, calculate its SHA-256, then write the completion record atomically. Reuse only when identity and output hash both match. Direct Polars streaming temp/spill files to the explicit `D:` temp directory.

- [ ] **Step 6: Refactor CLI and document the exact full-run contract**

Set the CLI's default source timezone to `Europe/Moscow` while retaining the option. Add `--temp-dir` and `--resume/--no-resume`. Document that production execution must pass all eight journal paths, the two external reference paths, `--source-timezone Europe/Moscow`, a fixed seed, output on `D:`, and a temp path on `D:`. State that thresholds and run artifacts are not committed.

- [ ] **Step 7: Verify Task 7**

Run focused tests, full pytest, Ruff, and mypy. Run the fixture CLI twice and compare output hashes and normalized JSON after removing `started_at`, `completed_at`, and stage-duration fields only. Expected: all checks exit 0 and deterministic comparisons match.

- [ ] **Step 8: Independent review and commit**

Assign a fresh reviewer to Sections 8–11, the stage invalidation rules, Windows path safety, and source immutability. Fix findings, rerun checks, then commit:

```bash
git add services/ml/src/fire_risk/data/pipeline.py services/ml/src/fire_risk/data/run_report.py services/ml/src/fire_risk/cli.py services/ml/tests/test_pipeline.py services/ml/tests/test_cli.py services/ml/README.md
git commit -m "feat(data): add resumable full-data pipeline"
```

## Task 8: Full 2019–2026 execution and acceptance evidence

**Files:**
- Modify only if the run exposes a defect: the owning source/test files from Tasks 1–7.
- Generated and ignored: the selected `D:` artifact directory and temp directory.
- Do not add source CSV, Parquet, JSON run artifacts, calibrated thresholds, or temp files to Git.

**Interfaces:**
- Consumes: eight journal CSVs plus the two authoritative external Russian references.
- Produces: the complete artifact set and final acceptance statistics; no tracked output is required unless a defect fix changes code/tests/docs.

- [ ] **Step 1: Record immutable source inventory before execution**

Calculate SHA-256 and byte size for every `dataset/ext-journal-2019.csv` through `dataset/ext-journal-2026.csv` and both external references. Save this as stage 00 under the run directory, not in Git. Confirm the two reference hashes include:

```text
channels: AC2F51BE51B3454EF634425748DBD6370632B034F5DB0A209E7B0DD74DE7812C
states:   B968F3652ED33FD6E0D2DCCEE334275436DADA67F4549763CFB4B2072108B5CC
```

- [ ] **Step 2: Run pass 1 on train only**

Invoke the full command with all journal paths, the external reference paths, `--source-timezone Europe/Moscow`, fixed seed, output on `D:`, temp on `D:`, and resume enabled. Inspect `10-channel-day-profiles.parquet` and `20-calibrated-thresholds.json`: their recorded calibration inputs must contain no 2025/2026 rows, while admissible 2021 profiles remain.

- [ ] **Step 3: Resume pass 2 with frozen thresholds**

Resume the same run identity and complete all stages. Confirm stage logs show `20-calibrated-thresholds.json` loaded without refitting when processing 2025 and 2026. Confirm no year-level filter removes all of 2021.

- [ ] **Step 4: Validate required statistics**

Extract and retain for the final response:

```text
accepted/quarantined rows by year
channel→object matched/unknown counts and percentage
unknown-state event and pair counts
true/false conflicting-state counts
excluded 2021 channel-day intervals and rows by reason
proxy incidents by year, object, rule, and sensor combination
class balance for now/6h/12h/24h
available/censored/positive/negative for every horizon
frozen threshold version, values, calibration periods, and rationale
feature-family/proxy-rule overlap
```

Open every Parquet schema and ensure target columns are nullable and availability columns are non-null Boolean.

- [ ] **Step 5: Prove resumability and determinism**

Run the identical command again. Confirm all eligible stages are reused. Compare manifest/report statistics and every Parquet SHA-256; permit differences only in the documented clock fields, never in identities, counts, thresholds, or data hashes.

- [ ] **Step 6: Prove source immutability**

Recalculate all ten source SHA-256 values and byte sizes and compare them to stage 00. Any difference is a blocking failure; do not commit or push until explained and restored from the user's authoritative copy.

- [ ] **Step 7: Run the final verification suite**

Run: `cd services/ml && python -m pytest -v`  
Run: `cd services/ml && python -m ruff check src tests`  
Run: `cd services/ml && python -m mypy src`  
Expected: all exit 0.

- [ ] **Step 8: Independent whole-branch review**

Assign a fresh reviewer who did not implement Tasks 1–7. Give them the PRD, original specification, backlog, original DATA plan, v2 specification, this plan, the diff from the pre-correction base, and the generated report schemas/statistics. Fix all Critical/Important findings with TDD, rerun the full verification suite, and create a separate fix commit for each coherent finding.

- [ ] **Step 9: Push without merging**

Confirm `git status --short` is clean and `git diff --name-only origin/feature/data-foundation...HEAD` contains no CSV, XLSX, Parquet, secrets, model artifacts, or generated run directories. Push only:

```bash
git push origin feature/data-foundation
```

Do not create or merge a `main` integration commit.

## Phase completion gate

- [ ] Every Task 1–7 implementation has a separate implementer, separate reviewer, green focused/full checks, and its own commit.
- [ ] The whole-branch reviewer has no open Critical/Important findings.
- [ ] Full 2019–2026 artifacts exist and resume successfully from matching identities.
- [ ] Thresholds were calibrated exclusively on train periods and applied unchanged to 2025/2026.
- [ ] `run_report.json` contains all required proxy, coverage, censoring, split, overlap, and warning fields.
- [ ] Final pytest, Ruff, and mypy commands exit 0.
- [ ] Before/after hashes prove the eight journals and two reference CSVs were unchanged.
- [ ] All commits are pushed to `origin/feature/data-foundation`; `main` remains untouched.
