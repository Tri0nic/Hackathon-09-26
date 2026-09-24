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

The implementation worktree also supports its existing Conda-style environment:
use `..\..\.venv\python.exe` in place of `python` from `services/ml`.

## Fixture build and reproducibility

```powershell
python -m fire_risk.cli prepare --events tests/fixtures/events.csv --channels tests/fixtures/channels.csv --states tests/fixtures/states.csv --output .artifacts --run-id smoke-test
```

The checked-in event fixture deliberately contains channel IDs absent from the
reference fixture. It produces two normalized rows and two membership rows,
zero episodes/labels/snapshots, and explicitly reports two unknown-channel
events. `tests/test_cli.py` also prepares a temporary fixture with known smoke
and heat channels, a proxy fire episode, conflicting states, and a malformed
timestamp, verifying nonempty features and targets through the same command.

To repeat the fixture build and compare provenance and source integrity:

```powershell
$fixtureFiles = @('tests/fixtures/events.csv', 'tests/fixtures/channels.csv', 'tests/fixtures/states.csv')
$beforeHashes = $fixtureFiles | Get-FileHash -Algorithm SHA256 | Select-Object Path, Hash | ConvertTo-Json
python -m fire_risk.cli prepare --events tests/fixtures/events.csv --channels tests/fixtures/channels.csv --states tests/fixtures/states.csv --output .artifacts --run-id smoke-test
$firstManifest = Get-Content .artifacts/smoke-test/manifest.json -Raw | ConvertFrom-Json
python -m fire_risk.cli prepare --events tests/fixtures/events.csv --channels tests/fixtures/channels.csv --states tests/fixtures/states.csv --output .artifacts --run-id smoke-test
$secondManifest = Get-Content .artifacts/smoke-test/manifest.json -Raw | ConvertFrom-Json
$firstManifest.PSObject.Properties.Remove('started_at')
$firstManifest.PSObject.Properties.Remove('completed_at')
$secondManifest.PSObject.Properties.Remove('started_at')
$secondManifest.PSObject.Properties.Remove('completed_at')
if (($firstManifest | ConvertTo-Json -Depth 20) -ne ($secondManifest | ConvertTo-Json -Depth 20)) { throw 'Manifest mismatch' }
$afterHashes = $fixtureFiles | Get-FileHash -Algorithm SHA256 | Select-Object Path, Hash | ConvertTo-Json
if ($beforeHashes -ne $afterHashes) { throw 'Source CSV changed' }
```

## Full journal build

The supplied `dataset/справочник_каналов_датчиков.csv` is **not** an enriched
channel reference: its five Russian columns do not contain the required object
mapping or hierarchy. A canonical state reference is also not supplied in the
current dataset. Before a full build, obtain authoritative channel-to-object
mapping and state definitions and export UTF-8 CSVs to
`data/references/channels.csv` and `data/references/states.csv`. Do not infer or
invent those mappings from engineering tags. Preserve the original CSVs.

`channels.csv` must contain the fields below, with one row per channel and IDs
stored as strings (including leading zeros):

```text
channel_id,engineering_system_type,sensor_type,sensor_name,object_id,object_level,object_name,level2_object_id,level2_object_name,level1_object_id,level1_object_name
```

`states.csv` requires `sensor_type,state_set_id,state_name,alarm_flag`. Distinct
variants for the same type/value are reported as conflicts. Numeric values can
appear in the report of pairs absent from the state reference; numeric parsing
has precedence during normalization.

From the main repository's `services/ml`, after supplying those references:

```powershell
python -m fire_risk.cli prepare `
  --events ../../dataset/ext-journal-2019.csv `
  --events ../../dataset/ext-journal-2020.csv `
  --events ../../dataset/ext-journal-2021.csv `
  --events ../../dataset/ext-journal-2022.csv `
  --events ../../dataset/ext-journal-2023.csv `
  --events ../../dataset/ext-journal-2024.csv `
  --events ../../dataset/ext-journal-2025.csv `
  --events ../../dataset/ext-journal-2026.csv `
  --channels ../../data/references/channels.csv `
  --states ../../data/references/states.csv `
  --source-timezone UTC --device-as-of 2026-09-24 --device-seed 0 `
  --output .artifacts --run-id full-2019-2026-v1
```

`--source-timezone UTC` is an explicit assumption, not established source
provenance. Set it to the source owner's documented IANA timezone, for example
`Europe/Moscow`, before a production build. Output timestamps, calendar features,
and day boundaries are UTC. The full dataset was not executed in fixture
validation. Sorting, grouped rolling windows and joins require working memory;
lazy execution does not promise constant memory on the multiyear dataset.

## Configuration, outputs, and interpretation

`--config path/to/config.json` accepts `PipelineConfig` fields, including
`scoring_step_minutes` (default 15), `episode_gap_minutes` (30),
`methane_alarm_percent` (1.0), and per-sensor `sensor_sentinels`. Omitted fields
retain defaults. Configuration, timezone, deterministic device-age seed/as-of,
quality thresholds, and proxy rule version are recorded in the manifest.

```text
.artifacts/<run-id>/
  normalized_events.parquet
  episodes.parquet
  episode_membership.parquet
  incident_labels.parquet
  feature_snapshots.parquet
  coverage.json
  quality_report.json
  manifest.json
```

The pipeline scans journals lazily, joins references, normalizes values and
pickets, attaches deterministic device-age estimates, profiles quality, builds
episodes/membership, emits proxy labels in batches, and attaches targets to
feature snapshots. Parquet files are explicit output boundaries; subsequent
stages rescan them. Only small references and aggregate JSON reports are eagerly
read; no event journal is converted to a Python list. Proxy label records are
converted in batches of at most 10,000 episodes inside Polars output processing.

Source CSVs are never modified. Repeating a run ID replaces that run's generated
files; choose a new ID to preserve an earlier build. The manifest records source
filenames, absolute paths and byte sizes, a SHA-256 of canonical configuration,
schema and Polars versions, UTC execution timestamps, and Parquet row counts.
Configuration sets are sorted before hashing. Determinism comparisons exclude
only execution `started_at`/`completed_at`; tests compare Parquet values as well.
Source sizes are provenance metadata, not cryptographic content hashes.

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
days. Current-day events and retrospectively known stuck intervals are excluded;
days with no eligible observations do not enter its denominator. No eligible
history gives null baseline/ratio. Activity ratio is 24h event count / baseline.
Retrospective day quality flags stay in normalized data and reports for audit.
Snapshots use causal quality flags: a day is flagged only from the first event
at which thresholds are crossed. The separate `baseline_stuck` input is used
only when its day is complete, never as a current-window feature. This prevents
a later same-day burst from changing an earlier snapshot.

Targets consume the canonical incident table separately from feature building:
`target_now` uses active **[start, end)** intervals, with zero-duration incidents
active only at their timestamp and null-ended incidents ongoing. Future targets
use **(t, t + 6/12/24 hours]**, so they are cumulative and monotonic. Confirmed
fires and unknown proxy/synthetic fire labels are positives; explicit negative
decisions and undecided dispatcher labels are not. Proxy labels remain
`source=proxy`, `decision=unknown`, with confidence and rule version; they are not
confirmed fires. A decision-free incident table is assumed already filtered.

`episode_group_id` is the earliest active incident ID, otherwise the nearest
future incident within 24h (ties break on ID). A snapshot with no match gets
null. Overlapping incidents can create overlapping forecast contexts; temporal
split/embargo policy remains the training stage's responsibility. This stage
does not mark right-censored horizons after the journal's final observation.
The broader duration, slope, entropy, inventory and freshness features listed
in the design are not implemented in this foundation's minimum feature contract.

Quality reports explicitly count malformed timestamps, unknown channels,
conflicting mappings, and quarantined rows. Malformed timestamps are omitted
from normalized output; original CSVs retain them. Historical 2021 artifacts
remain normalized with exclusion flags and are omitted from proxy fire labels.
Device ages are first-observation estimates or marked `generated_demo`/
`is_synthetic`; they are not installation records.
