# Model Demonstration, FastAPI, and Dispatcher Workflow Design

## Goal

Give judges a short, repeatable way to verify that the product performs a real
model calculation on held-out data and can pass a dangerous result into the
existing dispatcher workflow. The feature must not introduce a business role,
describe the result as a prediction for one sensor, or expose
implementation-specific model technology in user-facing copy.

## User experience

- Add a persistent `Демонстрация модели` item at the bottom of the left sidebar,
  visually separated from operational navigation.
- Show the item for every selected business role. It does not change role
  permissions and does not add a `Тестировщик` role.
- Open a dedicated `/model-demo` page titled `Демонстрация модели` with the
  subtitle `Проверка расчёта на отложенных данных`.
- Do not show the algorithm or library name in headings, controls, badges,
  descriptions, or result labels.

The page has three content blocks:

1. `Текущие показания` shows the selected source row number, object, dangerous
   section, related sensors, readable measurements, alarm counts, and its
   read-only source date and time.
2. `Результат` shows four probability horizons, threshold states, calculation
   time, and human-readable contributing factors.
3. `Управление` contains `Следующие показания`, `Рассчитать прогноз`,
   `Передать диспетчеру`, and the less prominent destructive action
   `Очистить результаты демонстрации`.

The controls behave independently:

- `Следующие показания` advances to the next held-out row in a deterministic,
  cyclic sequence and immediately clears the previous result.
- `Рассчитать прогноз` always evaluates the currently displayed row and never
  advances the sequence.
- `Передать диспетчеру` is enabled only for a fresh result where at least one
  configured threshold is exceeded.
- After publication, the page shows a link to the created warning.
- `Очистить результаты демонстрации` requires confirmation and removes only
  data created through this page.

## Time semantics

Every demonstration row is a complete snapshot for one
`object_id × scoring_timestamp` row from the held-out 2026 period. Its date and
time are displayed prominently but cannot be edited independently. Editing the
timestamp would make its calendar features and the 5-minute through 24-hour
history windows inconsistent.

The packaged feature vector includes the snapshot's `hour`, ISO `weekday`, and
`month` values as well as every other model feature. A newly calculated result
contains a separate server timestamp displayed as `Рассчитано`.

## Held-out demonstration sequence

- Export exactly 24 deterministic rows from the held-out test period, never
  from the training period.
- Order them into a stable sequence containing normal and dangerous operating
  conditions, including smoke/heat, gas growth, and technical malfunction
  contexts where the test data provides them.
- Store every feature required for inference; do not rely on median filling for
  omitted features.
- Store presentation context separately: source timestamp, object identity,
  district, sensor names, pickets, and readable measurements.
- Store no expected or prepared probabilities. Every displayed probability is
  returned by the running inference service.
- Keep complete feature vectors on the server. The browser receives only
  summaries and submits a scenario ID.
- Describe sensors as signals forming an object snapshot. The result is an
  object-level risk calculation, not a per-sensor prediction.

The browser holds only its current index in the sequence. No shared cursor is
required: one judge cannot advance another judge's page. After the last row,
`Следующие показания` returns to the first.

## FastAPI service

Replace the custom Python HTTP adapter with FastAPI while preserving the
existing successful external contracts:

- `GET /health`
- `GET /ml/models/current`
- `POST /ml/predict`

FastAPI additionally exposes `/docs` and `/openapi.json`. The existing model is
loaded once at process startup. Explicit Pydantic request models accept both
the current `topK` spelling and legacy `top_k`; malformed requests use standard
structured HTTP 422 responses. Prediction responses retain the schema expected
by the ASP.NET client.

## Demonstration API and transient calculation cache

The ASP.NET API exposes:

- `GET /api/model-demo/scenarios` — returns ordered summaries without feature
  vectors or expected probabilities.
- `POST /api/model-demo/predict` — accepts a scenario ID, resolves the complete
  server-side feature vector, calls `/ml/predict`, and returns the result plus a
  unique `calculationId` without creating operational records.
- `POST /api/model-demo/publish` — accepts a `calculationId` and publishes the
  exact trusted result that was shown on the page.
- `DELETE /api/model-demo/results` — transactionally removes only published
  demonstration chains and clears transient calculations.

Each successful calculation is stored in ASP.NET `IMemoryCache` for 30 minutes.
The cache entry contains its scenario identity, trusted prediction response,
and optional published alert ID. This makes publication idempotent and prevents
the browser from changing probabilities or publishing a result for different
inputs. An expired or unknown ID returns a clear conflict/not-found response and
requires recalculation.

The server independently rejects publication when no threshold decision is
true, even though the browser also disables the button. Repeated publication of
the same calculation returns the original alert ID instead of creating a
duplicate.

## Operational persistence and role workflow

Transient calculations live only in cache. Publication writes the model result
and warning to PostgreSQL through a dedicated transactional store operation;
it never changes model weights or source test rows.

Add an internal `is_demo` flag and nullable `demo_calculation_id` to persisted
predictions and warnings. A partial unique constraint on the calculation ID
provides database-level duplicate protection. A demo publication must not
overwrite or mark stale a non-demo current warning for the same object. Existing
role visibility remains authoritative:

- the district dispatcher sees warnings for the object's district;
- the ODS dispatcher sees all warnings;
- technicians and response teams enter the flow only after a dispatcher creates
  a request for the warning.

From that point, the existing decision, request, assignment, executor-action,
and SMS behavior is reused without a parallel demo implementation. A compact
`Демо` badge is rendered beside the risk level inside the existing alert cell
and near the title on details. No table column is added and row height should
remain stable. The badge does not expose model implementation details.

## Demonstration cleanup

`DELETE /api/model-demo/results` performs one database transaction and deletes
only relations rooted in `risk_alerts.is_demo = true`, in dependency-safe order:

1. related SMS and request comments;
2. related maintenance requests and dispatcher decisions;
3. related alert-level history;
4. demonstration warnings and predictions;
5. transient entries in the demonstration cache.

`demo_calculation_id` associates each published prediction with its warning and
makes cleanup auditable. Ordinary warnings, predictions, requests, decisions,
and SMS must remain unchanged. The UI asks for confirmation because demo
requests may already be in progress.

## Result presentation

The result area shows:

- `Сейчас` as the current-event estimate;
- accumulated risk `В течение 6 часов`, `В течение 12 часов`, and
  `В течение 24 часов`;
- whether the configured threshold is exceeded for each horizon;
- `Рассчитано` using the fresh response timestamp;
- readable factor names and values;
- the visible limitation `Демонстрационная proxy-разметка; качество на
  подтверждённых пожарах не измерено`.

If no threshold is exceeded, the full result remains visible, publication is
disabled, and the page says `Порог предупреждения не превышен`.

The page does not display algorithm names, native artifact filenames, package
names, or training implementation details. Technical metadata remains
available from service endpoints and OpenAPI documentation for engineering
verification.

## Error handling and concurrency

- Disable relevant controls while calculation, publication, or cleanup runs.
- Show a concise error when inference is unavailable; never substitute prepared
  probabilities or a previous result.
- Reject unknown scenario IDs without exposing feature vectors or file paths.
- Clear the result immediately when advancing to another source row.
- An expired calculation cannot be published and prompts a new calculation.
- Serialize publication per `calculationId` so simultaneous clicks cannot create
  duplicate warnings.
- A failed publication keeps the calculated result visible so it can be retried
  while its cache entry remains valid.
- After successful cleanup, refresh application data and reset the demo page to
  its first row with no result.

## Verification

- Export/catalog tests prove there are exactly 24 ordered 2026 test rows, each row
  has the exact manifest feature set, source calendar fields agree with its
  timestamp, IDs are unique, and no probability is bundled.
- FastAPI contract tests cover health, model summary, both `topK` spellings,
  request validation, real inference, and OpenAPI availability.
- ASP.NET tests cover complete feature forwarding, 30-minute cache expiry,
  threshold enforcement, idempotent/concurrent publication, demo isolation,
  role-visible persisted output, and transactional cleanup.
- Web tests cover bottom sidebar placement, absence of a tester role, cyclic
  next-row behavior, stale-result clearing, read-only source time, four horizon
  results, disabled safe-result publication, publication link, the compact
  badge without a new column, confirmation, and error states.
- An end-to-end smoke test proves that the UI result equals a direct inference
  call for the same row, publication produces a dispatcher warning, an existing
  request can be created from it, duplicate publication is prevented, and
  cleanup leaves ordinary records unchanged.

## Acceptance criteria

- `Демонстрация модели` is the last item in the left sidebar for every role.
- No `Тестировщик` business role is introduced.
- `/docs` displays the live ML API contract.
- `Следующие показания` cycles through 24 held-out test rows without running
  prediction; `Рассчитать прогноз` evaluates only the displayed row.
- The page displays both the source snapshot time and the new calculation time.
- All inference features come from a complete held-out snapshot.
- User-facing text does not name model implementation technology.
- The result is object-level and does not claim to predict one sensor.
- Safe results cannot be published as warnings.
- A dangerous result can be published exactly once and then handled through the
  existing dispatcher/request workflow.
- Published warnings carry a compact `Демо` badge without a new table column.
- Confirmed cleanup removes all and only demonstration workflow data.
