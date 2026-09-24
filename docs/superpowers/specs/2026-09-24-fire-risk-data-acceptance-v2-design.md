# Fire Risk DATA Acceptance v2 Design

**Status:** proposed for implementation  
**Date:** 2026-09-24  
**Branch:** `feature/data-foundation`  
**Builds on:** `2026-09-24-fire-risk-mvp-design.md` and the DATA-01…DATA-09 implementation

## 1. Goal

Bring the DATA epic to acceptance on the complete 2019–2026 journal corpus by:

- reading the authoritative Russian channel and state reference schemas directly;
- producing causal feature snapshots and explicitly right-censored targets;
- calibrating quality thresholds on train data only;
- creating a replaceable proxy incident journal and `y_now`, `y_6h`, `y_12h`, `y_24h`;
- running a resumable, reproducible two-pass full-data build;
- reporting coverage, data quality, proxy-label composition, and target availability.

The source CSV files are immutable inputs and never enter Git.

## 2. Authoritative inputs

### 2.1 Event journals

```text
dataset/ext-journal-2019.csv
...
dataset/ext-journal-2026.csv
```

Required Russian fields:

```text
ид_события
ид_канала_данных
дата
время
тревожное
значение_датчика
```

### 2.2 Extended channel reference

Authoritative external file:

```text
C:\Users\Андрей\Downloads\Telegram Desktop\справочник_каналов_датчиков_расширенный.csv
```

Observed profile: 11,485 unique channel IDs, 78 object IDs, 19 sensor types.

Russian-to-canonical mapping:

| Russian source | Canonical field |
| --- | --- |
| `ид_канала_данных` | `channel_id` |
| `тип_инж_системы` | `engineering_system_type` |
| `тип_датчика` | `sensor_type` |
| `название_датчика` | `sensor_name` |
| `ид_объект` | `object_id` |
| `иерархия_уровень` | `object_level` |
| `диспетчерское_название_объекта` | `object_name` |
| `объект_ур2` | `level2_object_id` |
| `объект_ур2_имя` | `level2_object_name` |
| `объект_ур1` | `level1_object_id` |
| `объект_ур1_имя` | `level1_object_name` |

`родитель` and `Имя` remain source-only metadata. The adapter validates their
presence in the known Russian schema but does not invent additional canonical
semantics for them.

### 2.3 State reference

Authoritative external file:

```text
C:\Users\Андрей\Downloads\Telegram Desktop\справочник_состояний.csv
```

Russian-to-canonical mapping:

| Russian source | Canonical field |
| --- | --- |
| `тип_датчика` | `sensor_type` |
| `ид_набор_состояний` | `state_set_id` |
| `название_состояния` | `state_name` |
| `тревожное` | `alarm_flag` |

The adapter accepts either the canonical or exact Russian schema and rejects
unknown/partial schemas with an actionable error. It never requires manual
column renaming.

## 3. State normalization and conflict semantics

1. Normalize alarm values from `true/t/1` and `false/f/0`.
2. Collapse exact duplicate rows.
3. Group by `(sensor_type, state_name)`.
4. Preserve every distinct `state_set_id` as a sorted list in a mapping record:

```text
sensor_type
state_name
alarm_flag: bool | null
state_set_ids: list[string]
is_conflicting: bool
```

5. If all variants have the same normalized `alarm_flag`, the value is a
   `known_state`, even when several `state_set_id` values exist.
6. A pair is conflicting only when both `true` and `false` exist. It remains
   `value_kind=unknown` with `conflicting_state_mapping` and is reported.

The observed authoritative file currently contains three exact duplicates,
four same-alarm/multiple-set pairs, and one true/false conflict. These are
fixtures for adapter and integration tests, not hard-coded production rules.

## 4. Provider-owned observation boundary and right censoring

Every `LabelProvider` exposes an explicit coverage boundary:

```text
observed_until: datetime
get_incidents(start, end, object_ids) -> list[IncidentLabel]
```

`observed_until` describes the provider's confirmed observation coverage. It
is not inferred from the last event, last positive incident, or per-object
activity.

For a snapshot at `t`:

```ini
target_now_available = t <= observed_until
target_6h_available  = t + 6h  <= observed_until
target_12h_available = t + 12h <= observed_until
target_24h_available = t + 24h <= observed_until
```

Unavailable horizon targets are `null`, never `false`. Training data for one
horizon includes only rows with its `target_*_available=true`. Available future
targets retain cumulative monotonicity:

```text
y_6h <= y_12h <= y_24h
```

The proxy provider used for the full build receives a configured journal
coverage end. A future real decision provider supplies its own coverage end
without changing feature construction or model contracts.

## 5. Causal feature schema

The unit remains `object_id × scoring_timestamp`, default step 15 minutes.
Every feature at `t` uses only rows with `registered_at <= t`.

### 5.1 Existing window families

For 5m, 30m, 3h, 6h, and 24h retain event/alarm counts, unique channels and
types, malfunction/quality counts, gas and temperature summaries, signal
conjunctions, calendar fields, and causal historical baseline.

### 5.2 State and malfunction durations

For each channel, the state known at `t` starts at the last observed change at
or before `t`. Duration is clipped to the feature window and ends at `t`.
Future state changes or future episode ends are never consulted.

Per window expose at least:

```text
active_state_duration_seconds_<window>
max_active_state_duration_seconds_<window>
malfunction_duration_seconds_<window>
max_malfunction_duration_seconds_<window>
```

### 5.3 Gas and temperature slopes

Compute least-squares slope against event time using only numeric points inside
the window and at or before `t`. Fewer than two distinct timestamps, or zero
time variance, produces `null`, never zero.

```text
gas_slope_per_hour_<window>
temperature_slope_per_hour_<window>
```

### 5.4 Variability and entropy

Within each window independently:

- numeric variability is sample standard deviation of numeric values;
- state entropy is Shannon entropy of observed `(channel_id, raw_value)` states;
- an empty window yields `null`; one observed category yields entropy `0.0`.

No statistic reuses a wider or future window.

### 5.5 Inventory and freshness

Inventory comes from the authoritative channel reference, not observed events.
For each object retain total channels and counts by exact `sensor_type` in a
stable nested mapping table, plus stable scalar totals for the known MVP signal
families.

At `t`, freshness compares inventory against the last event of every channel
known at or before `t`. A channel with no event by `t` is stale. Expose total
fresh/stale counts and stale share for the agreed 24-hour freshness period,
plus per-family counts where applicable.

Appending events after `t` cannot change inventory, freshness, duration, slope,
variability, entropy, or any existing feature at `t`.

## 6. Proxy incident journal

Proxy labels remain canonical `IncidentLabel` records and can later be replaced
by `DecisionJournalLabelProvider` without changing feature or model inputs.

Rules use alarm-specific episode composition only and include agreed patterns:

- smoke + heat;
- smoke + manual call point;
- smoke + UIR-R;
- smoke/heat plus supporting pump signal;
- methane threshold alarm plus another fire signal;
- configurable mass coordinated alarm across distinct channels/types.

Technical malfunction states, `historical_artifact` intervals, and rows marked
`exclude_from_fire_training` cannot create proxy fire incidents. Rule version,
confidence, sensor combination, episode ID, and source are persisted.

The proxy journal produces `y_now`, `y_6h`, `y_12h`, and `y_24h` through the
same target builder used by future real decisions. Features never import or
execute proxy-label rules.

## 7. Leakage-free quality calibration

### 7.1 Splits

```text
train calibration: 2019–2020, admissible 2021 intervals, 2022–2024
validation:        2025
test:              2026
```

2025 and 2026 never contribute to thresholds, quantiles, sentinel discovery,
or rule selection. They are processed only after the frozen configuration is
written.

### 7.2 Two-pass procedure

Pass 1:

1. Parse and normalize train-period rows.
2. Write versioned channel-day profiles as Parquet.
3. Exclude only already established malformed/corrupted 2021 channel-day
   intervals from calibration; never exclude 2021 wholesale.
4. Calculate robust candidate thresholds from train profiles.
5. Persist the selected typed threshold configuration, rationale, train period,
   source SHA-256 values, code revision, seed, and calibration version.

Pass 2:

1. Load the frozen threshold configuration without recalculation.
2. Apply it unchanged to train, 2025 validation, and 2026 test data.
3. Produce normalized events, quality flags, episodes, proxy labels, snapshots,
   targets, reports, and manifest.

Calibration output is an artifact, not a committed source dataset. The chosen
threshold schema and deterministic algorithm are committed and tested.

## 8. Resumable full-data execution

The run is addressed by a deterministic identity derived from:

- SHA-256 of every source journal and reference;
- canonical configuration and `Europe/Moscow` source-timezone assumption;
- implementation revision;
- seed and schema versions.

Stages write atomic completion markers and versioned intermediates:

```text
00-source-inventory.json
10-channel-day-profiles.parquet
20-calibrated-thresholds.json
30-normalized-events.parquet
40-episodes.parquet
41-episode-membership.parquet
50-incident-labels.parquet
60-feature-snapshots.parquet
70-coverage.json
71-quality-report.json
72-run-report.json
manifest.json
```

A stage is reused only when its recorded input identity matches. Otherwise it
and every downstream stage are rebuilt. Writes use a temporary sibling and
atomic rename. The run accepts an explicit temp directory on disk `D:` so the
14.82 GB source corpus is not duplicated on the smaller system disk.

Repeating with the same hashes, configuration, seed, and revision produces
identical Parquet values and non-clock manifest/report statistics.

## 9. Timezone

The full MVP run uses:

```text
--source-timezone Europe/Moscow
```

This remains configurable and is recorded as an assumption in the manifest
and report. Source timestamps are localized to Europe/Moscow and converted to
UTC for storage and modeling. Feature calendar/day boundaries are derived
consistently from the configured source timezone before UTC persistence where
business-local semantics are required.

## 10. Full-run reports

`run_report.json` contains:

- accepted/quarantined rows by source year;
- channel→object matched and unknown event counts and coverage percentage;
- unknown state event/pair counts and true/false conflict counts;
- excluded 2021 channel-day intervals and rows by reason;
- frozen quality-threshold values, version, calibration period, and rationale;
- proxy rule version;
- proxy incidents by year, object, rule, and sorted sensor combination;
- class balance for now/6h/12h/24h;
- `available`, `censored`, `positive`, and `negative` counts per horizon;
- overlap between feature families and proxy-rule inputs;
- source hashes, seed, timezone assumption, and implementation revision;
- a prominent warning that proxy metrics measure reproduction of reconstructed
  labels, not detection quality for confirmed real fires.

`coverage.json`, `quality_report.json`, `manifest.json`, the proxy incident
Parquet, and feature/target Parquet remain separate machine-readable outputs.

## 11. Data safety and Git scope

- Read all source CSVs without modification.
- Capture SHA-256 before and after the full run and require zero differences.
- Never commit source CSVs, generated Parquet, run reports, calibrated artifacts,
  temp files, or model artifacts.
- Commit only adapters, schemas/contracts, pipeline code, configuration schema,
  tests, documentation, and implementation plan.
- Continue only on `feature/data-foundation`; do not merge `main`.

## 12. Test strategy

Required automated tests:

1. Exact Russian channel/state headers map to canonical contracts.
2. Unknown and partial reference schemas fail clearly.
3. Exact state duplicates collapse.
4. Same-alarm/multiple-set pairs are known and retain sorted IDs.
5. True/false variants are conflicting and remain unknown.
6. Provider-owned `observed_until` censors each horizon independently.
7. Censored targets are null and unavailable, never negative.
8. Duration ignores future state changes.
9. Slopes use only past points and are null with insufficient timestamps.
10. Variability/entropy are window-local and future invariant.
11. Inventory comes from reference rows, including never-observed channels.
12. Freshness uses last events known at `t` and inventory denominator.
13. Calibration never reads 2025/2026 profiles.
14. Frozen thresholds apply unchanged to validation/test.
15. Resume identity invalidates the correct downstream stages.
16. Proxy rules exclude malfunction and historical-artifact intervals.
17. Full-run report schemas and proxy warning are stable.
18. Source hashes remain unchanged in fixture integration tests.

## 13. Acceptance

The correction is complete when:

- pytest, Ruff, and mypy pass;
- independent task and whole-branch reviews have no open Critical/Important
  findings;
- the full 2019–2026 two-pass run completes with `Europe/Moscow`;
- frozen train-only thresholds are applied unchanged to 2025/2026;
- all required Parquet and JSON artifacts exist and can be resumed;
- the final report presents real full-run counts and proxy rules/statistics;
- hashes prove every source file is unchanged;
- commits are pushed to `feature/data-foundation` only.
