# Fire-risk data preparation

Python 3.12+ is required. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e './services/ml[dev]'
Set-Location services/ml
python -m pytest -v
python -m ruff check src tests
python -m mypy src
```

## Train the CatBoost baseline

Training runs `now`, `6h`, `12h`, and `24h` sequentially, saving each completed
model before starting the next one. `--resume` reuses matching completed models.
Run from `services/ml`:

```powershell
..\..\.venv\python.exe -m fire_risk.ml_cli train `
  --input "D:\AndrewProgramming\GithubProjects\Hackathon-09-26\.artifacts\full-2019-2026-v2\acceptance\60-feature-snapshots.parquet" `
  --output "D:\AndrewProgramming\GithubProjects\Hackathon-09-26\.artifacts\ml\catboost-v1" `
  --task-type GPU `
  --resume
```

The output directory contains four `.cbm` models, per-horizon metadata,
`manifest.json`, and `metrics.json`. Reported metrics reproduce reconstructed
proxy labels and are not evidence of confirmed real-fire detection quality.

On Windows, installation includes the `tzdata` runtime dependency so Python's
`ZoneInfo` can resolve `Europe/Moscow` even without a system IANA timezone
database. Re-run the editable installation command when updating an existing
environment to pick up dependency changes.

The implementation worktree also supports its existing Conda-style environment:
use `..\..\.venv\python.exe` in place of `python` from `services/ml`.

## Fixture build and reproducibility

Run `python -m pytest tests/test_pipeline.py tests/test_cli.py -v` for fixture
builds with explicit provider coverage. Tests execute the CLI twice and compare
Parquet SHA-256 values and JSON content, excluding only execution `started_at`
and `completed_at`. No stage-duration fields are currently emitted. The pipeline
tests also force a complete rebuild with `resume=False` and verify the same
non-clock artifacts, interruption recovery, tamper detection and source integrity.

For a previously calibrated fixture, use:

```powershell
python -m fire_risk.cli prepare --events tests/fixtures/events.csv --channels tests/fixtures/channels.csv --states tests/fixtures/states.csv --quality-thresholds D:/fire-risk/.artifacts/fixture-thresholds.json --label-observed-until 2026-12-31T00:00:00+03:00 --source-timezone Europe/Moscow --temp-dir D:/fire-risk/.artifacts/temp --output D:/fire-risk/.artifacts --run-id smoke-test
```

The threshold file must be a validated artifact created by
`calibrate_thresholds` / `write_calibration`, or stage 20 of an earlier full run.
A supplied `--quality-thresholds` file is loaded without refitting.

## Full 2019–2026 two-pass build

Pass all eight immutable journals and both authoritative external references.
The adapters accept the exact Russian schemas directly; no manual renaming is
needed. Same-alarm state mappings with several state-set IDs remain known;
only true/false disagreement is a conflict.

From the main repository's `services/ml` directory, execute in PowerShell:

```powershell
# Set this to the provider-confirmed coverage end; do not infer it from events.
$labelCoverageEnd = 'REPLACE_WITH_CONFIRMED_ISO_8601_TIMESTAMP_WITH_TIMEZONE'
python -m fire_risk.cli prepare `
  --events ../../dataset/ext-journal-2019.csv `
  --events ../../dataset/ext-journal-2020.csv `
  --events ../../dataset/ext-journal-2021.csv `
  --events ../../dataset/ext-journal-2022.csv `
  --events ../../dataset/ext-journal-2023.csv `
  --events ../../dataset/ext-journal-2024.csv `
  --events ../../dataset/ext-journal-2025.csv `
  --events ../../dataset/ext-journal-2026.csv `
  --channels 'C:\Users\Андрей\Downloads\Telegram Desktop\справочник_каналов_датчиков_расширенный.csv' `
  --states 'C:\Users\Андрей\Downloads\Telegram Desktop\справочник_состояний.csv' `
  --source-timezone Europe/Moscow --device-as-of 2026-09-24 --device-seed 42 `
  --label-observed-until $labelCoverageEnd --calibrate --resume `
  --output D:/fire-risk/.artifacts --temp-dir D:/fire-risk/.artifacts/temp `
  --run-id full-2019-2026-v2
```

In an isolated worktree, supply absolute journal paths to the main repository's
`dataset` directory. Production output **and** temporary/spill directories must
be explicit paths on `D:`; reference files remain read-only at their original
locations. Never commit thresholds, reports, intermediate data, temp files or
other generated artifacts. Keep production runs under an ignored `.artifacts`
directory or outside the checkout.

`--calibrate` and `--quality-thresholds` are mutually exclusive. Calibration
requires an explicit `--temp-dir` and journal filenames containing their
2019–2026 source year. Pass 1 profiles train journals (2019–2024) only and saves
typed, versioned train-only thresholds. No static threshold decides which 2021
intervals enter calibration. In the absence of pre-established exclusion
annotations, all parser-valid 2021 intervals remain admissible; the report
states that pre-calibration exclusions are zero. Parser-invalid rows never enter
profiles. Pass 2 reloads the frozen artifact and applies it unchanged to all
years, including 2025 validation and 2026 test.

`Europe/Moscow` is the default, configurable timezone assumption and part of
identity/provenance. Source timestamps are localized there. Business-day quality
profiles, historical baselines and calendar features use that timezone; persisted
event, episode and scoring timestamps are UTC. Coverage is always explicit:
`--label-observed-until` requires an offset-aware timestamp.

## Configuration, stages, and resumption

`--config path/to/config.json` accepts `PipelineConfig` fields:
`scoring_step_minutes` (15), `episode_gap_minutes` (30),
`methane_alarm_percent` (1.0), and per-sensor `sensor_sentinels`.

```text
<output>/<run-id>/
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

Every stage has a `<filename>.complete.json` containing its name, input identity,
output SHA-256, schema version and non-clock statistics. Reuse requires both a
matching identity and verified content hash. Missing/invalid markers or changed
stage inputs rebuild that stage and every successor. For example, changing the
episode gap reuses the source inventory, channel-day profiles, thresholds,
normalized events and object inventory. `--no-resume` rebuilds all stages.
Never run concurrent writers against the same run directory.

Each write uses a temporary sibling, closes/fsyncs it, atomically replaces the
output, then atomically publishes its completion record. An interrupted writer
does not delete the prior artifact; an incomplete output has no valid completion
marker. The pipeline hashes every source before reading and after execution and
refuses to complete the manifest if any hash changes. The run identity includes
source hashes, canonical configuration, timezone, seed, schema/Polars version and
implementation revision. Revision uses `FIRE_RISK_IMPLEMENTATION_REVISION` if
set, otherwise local Git HEAD; run committed code or supply an explicit build
revision when testing uncommitted changes.

Legacy names (`normalized_events.parquet`, `inventory_totals.parquet`,
`inventory_by_type.parquet`, `episodes.parquet`, `episode_membership.parquet`,
`incident_labels.parquet`, `feature_snapshots.parquet`, `coverage.json`,
`quality_report.json`, `run_report.json`) are published atomically as aliases.
They use same-volume hard links where available, avoiding another copy of large
Parquet outputs. Stage names and their completion markers are authoritative.

CSV sanitation uses bounded record buffers and caller-owned temporary spools
under `--temp-dir`; they are removed when the run exits normally or raises.
Polars spill is directed to the same root with `POLARS_TEMP_DIR`. Abrupt process
termination may leave temp files, so provision space on `D:`. Sorting, rolling
windows and joins still require memory; lazy execution does not guarantee
constant memory. No whole journal or full label table is converted to a Python
list. Small references and grouped report aggregates are collected eagerly.

Run IDs are single Windows-safe components. Reserved device names, trailing
dots/spaces, separators, colons, case aliases and junction/symlink aliases to
other directories are rejected before output writes.

`run_report.json` includes accepted/quarantined rows by source year, object
coverage, unknown states/conflicts, excluded 2021 intervals and reasons, frozen
threshold provenance, proxy counts by year/object/rule/sorted sensor combination,
class balance and available/censored/positive/negative counts for every horizon,
feature/rule input overlap, and source hashes/seed/timezone/revision. Proxy metrics
measure reproduction of reconstructed labels, **not detection quality for
confirmed real fires**.

Numeric methane readings at or above the configured threshold set the resolved
`alarm_flag` consumed by episodes and proxy labels; `source_alarm_flag` preserves
the original journal flag.

Feature rows are exactly `object_id × scoring_timestamp`, from the floor of the
first known event to the ceiling of the last event for each object. Unknown
objects remain in normalized events and membership, with null episode IDs, but
cannot form object features. Empty grid intervals remain present. Each 5m, 30m,
3h, 6h and 24h window uses **(t − window, t]**. It contains counts of events,
alarms, distinct channels/types, malfunctions, and stuck/burst/historical flags;
gas maximum/mean/threshold exceedances; temperature maximum/mean; alarm
conjunctions of smoke with heat, manual call points or UIR-R; and pump alarms.
Missing numeric signals yield typed nulls, counts zero, and conjunctions false.
Hour/month and ISO weekday (Monday = 1) are available at the scoring timestamp.

The object baseline is mean daily activity over observed, eligible **completed**
days. Current-day events and retrospectively known stuck, historical-artifact or
training-excluded intervals are excluded;
days with no eligible observations do not enter its denominator. No eligible
history gives null baseline/ratio. Activity ratio is 24h event count / baseline.
Retrospective day quality flags stay in normalized data and reports for audit.
The public snapshot builder recomputes causal quality flags from raw event
history, including when its input already carries retrospective or causal flags.
A day is flagged only from the first event at which thresholds are crossed.
Reduced inputs without `event_id`/`raw_value` cannot establish state histories,
so unverified window quality flags default to zero. Existing exclusion annotations
on reduced inputs can exclude completed days from the baseline. The separate
`baseline_excluded` marker is used only when its day is complete, never as a
current-window feature. This prevents a later same-day burst from changing an
earlier snapshot, whether the builder is called directly or through the CLI.

Targets consume the canonical incident table separately from feature building:
`target_now` uses active **[start, end)** intervals, with zero-duration incidents
active only at their timestamp and null-ended incidents ongoing. Future targets
use **(t, t + 6/12/24 hours]**, so they are cumulative and monotonic. Confirmed
fires and unknown proxy/synthetic fire labels are positives; explicit negative
decisions and undecided dispatcher labels are not. Proxy labels remain
`source=proxy`, `decision=unknown`, with confidence and rule version; they are not
confirmed fires. A decision-free incident table is assumed already filtered.

`episode_group_id` represents a connected forecast context per object. Each
incident influences the interval starting 24h before its start and continuing
through its active interval. Overlapping influence intervals merge transitively,
and the earliest incident ID (ties break on ID) names the component. Thus a
future incident cannot create target-positive rows assigned to different groups
just because an earlier incident is active at one scoring time. Disconnected
contexts keep separate IDs; grouping is independent of input order and snapshot
selection. A snapshot with no active/future match gets null. Temporal split and
embargo policy remains the training stage's responsibility. This stage
marks each target unavailable when its horizon extends beyond the provider's
explicit observation boundary. Censored targets are null, never false. Duration,
slope, window-local variability/entropy, authoritative inventory and 24-hour
freshness features are included and causal.

Quality reports explicitly count malformed timestamps, other malformed input
rows by reason, unknown channels, conflicting mappings, and quarantined rows.
Missing required identifiers/date/time/alarm/value fields, invalid alarm flags,
invalid timestamps, too few/extra CSV fields and malformed quotes enter the bad
LazyFrame with an explicit `quality_reason`, `source_file` and `source_row`. Row numbers count
logical CSV records including the header, not physical lines inside quoted
multiline values. Quoted commas, escaped quotes and valid quoted multiline values
are preserved. Malformed quoting receives `invalid_csv_quoting`; records exceeding
the 1,048,576-character read budget or Python CSV's field-size limit receive
`record_too_large`. After either parser error, the first physical line is
quarantined and parsing resumes at the following physical line, so an unfinished
quote cannot consume valid neighboring records. Like any CSV reader, a sequence
that is syntactically a valid multiline field is treated as such. Source identity
is the pair `(source_file, source_row)`, including when multiple input files reuse
event IDs. Malformed rows are omitted from normalized output without
discarding valid neighbors; original CSVs retain them. Historical 2021 artifacts
remain normalized with exclusion flags and are omitted from proxy fire labels.
Device ages are first-observation estimates or marked `generated_demo`/
`is_synthetic`; they are not installation records.
