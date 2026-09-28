# Model Demonstration and FastAPI Design

## Goal

Give judges a short, repeatable way to verify that the product performs a real
model calculation instead of displaying prepared probabilities. The feature
must not introduce a business role, describe the result as a prediction for one
sensor, or expose implementation-specific model technology in user-facing copy.

## User experience

- Add a persistent `Демонстрация модели` item at the bottom of the left sidebar,
  visually separated from operational navigation.
- Show the item for every selected business role. It does not change role
  permissions and does not add a `Тестировщик` role.
- Open a dedicated `/model-demo` page titled `Демонстрация модели` with the
  subtitle `Проверка расчёта на отложенных данных`.
- Do not show the algorithm or library name in headings, controls, badges,
  descriptions, or result labels.

The page contains three stages:

1. Select one of several deterministic scenarios such as normal operation,
   smoke with heat, gas growth, or technical malfunction.
2. Inspect the selected object snapshot: object, dangerous section, related
   sensors, measurements, alarm counts, and calculation date and time.
3. Press `Рассчитать прогноз` and see four horizon results, threshold states,
   calculation time, and human-readable contributing factors.

The primary action calculates without writing alerts, requests, or SMS. The
existing persisted prediction endpoint remains available to the operational
flow but is not invoked by repeated demonstration runs.

## Time semantics

Every scenario is a complete snapshot for one `object_id × scoring_timestamp`
row from the held-out 2026 period. Its date and time are displayed prominently
and submitted with the scenario identity.

The timestamp is read-only. Changing it independently would make the calendar
features and the 5-minute through 24-hour history windows inconsistent. A future
live-ingestion feature may build a new snapshot for an arbitrary time, but that
is outside this demonstration scope.

The packaged feature vector includes the snapshot's `hour`, ISO `weekday`, and
`month` values as well as all other model features. The response contains a new
server calculation timestamp, which is displayed separately as `Рассчитано`.

## Scenario data

- Export a small deterministic set of complete feature rows from the held-out
  test period, never from the training period.
- Store all model feature values required for inference; do not rely on median
  filling for omitted features.
- Store presentation context separately: scenario label, source timestamp,
  object identity, sensor names, pickets, and readable measurements.
- Do not store expected probabilities in the scenario. Every probability shown
  on the page must come from the running inference service.
- Describe sensors as the signals that form the object snapshot. The result is
  an object-level risk calculation, not a per-sensor prediction.

## Service architecture

Replace the custom Python HTTP adapter with FastAPI while preserving the
existing external contracts:

- `GET /health`
- `GET /ml/models/current`
- `POST /ml/predict`

FastAPI additionally exposes `/docs` and `/openapi.json`. The existing model is
loaded once at process startup. Request validation uses explicit Pydantic models,
and the response continues to use the current prediction schema so the ASP.NET
client remains compatible.

The ASP.NET API adds two demonstration endpoints:

- `GET /api/model-demo/scenarios` returns scenario metadata without the private
  full feature vector.
- `POST /api/model-demo/predict` accepts a scenario ID, resolves its complete
  feature vector server-side, calls `/ml/predict`, and returns the calculation
  plus scenario context without persisting an alert.

The browser never supplies arbitrary model features for the curated demo path.
This makes the demonstration deterministic, prevents malformed combinations,
and keeps all 157 input features consistent.

## Result presentation

The result area shows:

- `Сейчас` as the current-event estimate;
- accumulated risk `В течение 6 часов`, `В течение 12 часов`, and
  `В течение 24 часов`;
- whether the configured threshold is exceeded for each horizon;
- `Рассчитано` using the response timestamp;
- readable factor names and values;
- a visible limitation: `Демонстрационная proxy-разметка; качество на
  подтверждённых пожарах не измерено`.

The page does not display `CatBoost`, native artifact filenames, package names,
or training implementation details. Technical metadata remains available from
the service endpoint and OpenAPI documentation for engineering verification.

## Error handling

- Disable the primary action while a calculation is running.
- Show a concise error if the inference service is unavailable; do not silently
  substitute prepared probabilities or a previous result.
- Reject unknown scenario IDs in the ASP.NET API.
- Return validation errors from FastAPI as structured JSON.
- Keep the last successful result visible only until the user selects another
  scenario; mark it with its calculation timestamp.

## Verification

- FastAPI contract tests cover health, model summary, request validation, real
  inference, and OpenAPI availability.
- ASP.NET tests cover scenario listing, unknown IDs, forwarding the complete
  feature vector, and the non-persisting response.
- Web tests cover the bottom sidebar placement, absence of a tester role,
  scenario selection, read-only source time, loading/error states, four horizon
  results, and absence of implementation-specific model names.
- An end-to-end smoke check proves that the UI result matches a direct inference
  call for the same scenario and that no alert, request, or SMS is created.

## Acceptance criteria

- `Демонстрация модели` is the last item in the left sidebar for every role.
- No `Тестировщик` business role is introduced.
- `/docs` displays the live ML API contract.
- A judge can select a held-out scenario and receive a fresh four-horizon result.
- The page displays both the source snapshot time and the new calculation time.
- All inference features come from the complete held-out snapshot.
- User-facing text does not name the model implementation technology.
- The result is explicitly object-level and does not claim to predict one sensor.
- Repeated calculations do not modify alerts, requests, decisions, or SMS.
