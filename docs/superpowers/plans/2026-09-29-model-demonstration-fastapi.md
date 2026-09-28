# Model Demonstration and FastAPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom ML HTTP adapter with a compatible FastAPI service and add a non-persisting model-demonstration page backed by complete held-out object snapshots.

**Architecture:** FastAPI preserves the three current ML routes and adds automatic OpenAPI documentation. A curated scenario catalog owned by the ASP.NET API keeps complete feature vectors off the browser, forwards one selected scenario to ML, and returns presentation context plus a fresh prediction without changing operational records. React exposes this flow through a bottom sidebar link available to every existing role.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pydantic, CatBoost runtime, ASP.NET Core 10 Minimal API, React, TypeScript, Vitest, xUnit, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-model-demonstration-fastapi-design.md`

## Global Constraints

- Preserve successful responses for `GET /health`, `GET /ml/models/current`, and `POST /ml/predict`; malformed FastAPI requests deliberately use standard HTTP 422 validation responses.
- Do not add a `Тестировщик` business role or alter existing role permissions.
- Place `Демонстрация модели` at the bottom of the left sidebar for every role.
- Do not name the model algorithm, library, native artifact, or package in demonstration-page copy.
- Describe predictions as object-level results; sensors are input context, not prediction entities.
- Use complete held-out 2026 snapshots and never store expected probabilities in scenario data.
- Display the read-only source `scoring_timestamp` separately from the new server calculation time.
- Demonstration prediction must not create or update alerts, requests, decisions, or SMS.
- Preserve the user's existing uncommitted edits in `services/web/src/App.tsx`, tests, domain helpers, and styles.

## Review Focus

- Missing or malformed scenario catalogs must fail clearly at startup or request time, never fall back to prepared probabilities.
- Scenario identifiers are untrusted input: an unknown ID returns 404 without exposing feature vectors or filesystem details.
- All 157 manifest features must be present before forwarding; extra context fields must never enter model input.
- Source timestamp and calendar feature values must agree, including ISO weekday semantics and timezone conversion.
- Switching scenarios or a failed request must not leave a previous result presented as the new scenario's calculation.

---

### Task 1: FastAPI-compatible ML service

**Files:**
- Modify: `services/ml/pyproject.toml`
- Replace: `services/ml/src/fire_risk/ml_api.py`
- Modify: `services/ml/tests/test_ml_api.py`
- Modify: `services/ml/Dockerfile`

**Interfaces:**
- Consumes: `Predictor.predict(features: dict[str, float | int | bool | None], top_k: int) -> Prediction` from `fire_risk.ml.inference`.
- Produces: `create_app(predictor: Predictor, manifest: dict[str, Any]) -> FastAPI`, runtime `main() -> None`, and unchanged HTTP contracts for the ASP.NET `MlClient`.

- [ ] **Step 1: Add failing FastAPI contract tests**

Extend `services/ml/tests/test_ml_api.py` with a fake predictor and `TestClient` assertions for:

- `GET /health` returns `200` and `{"status":"ok"}`;
- `GET /ml/models/current` preserves current camel-case summary fields;
- `POST /ml/predict` accepts `features` with either current `topK` or legacy `top_k` and serializes the predictor result;
- absent `features` and non-positive `topK` return `422` structured validation errors;
- `/openapi.json` describes all three routes and `/docs` returns HTML.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m pytest services/ml/tests/test_ml_api.py -q`

Expected: FAIL because `create_app` and FastAPI validation/OpenAPI do not exist.

- [ ] **Step 3: Add runtime dependencies**

Add `fastapi>=0.115,<1` and `uvicorn>=0.32,<1` to project dependencies and `httpx>=0.27,<1` to the `dev` extra in `services/ml/pyproject.toml`.

- [ ] **Step 4: Implement the FastAPI adapter**

Implement in `services/ml/src/fire_risk/ml_api.py`:

- `PredictionRequest(BaseModel)` with `features: dict[str, float | int | bool | None]` and `top_k: int` accepting both `topK` and `top_k` through `AliasChoices`, defaulting to 5 and requiring a positive value;
- `create_app(predictor, manifest) -> FastAPI` with the three preserved routes;
- `create_runtime_app() -> FastAPI` that loads `FIRE_RISK_MODEL` once;
- `main() -> None` that calls `uvicorn.run` with `FIRE_RISK_ML_HOST` and `FIRE_RISK_ML_PORT`.

Keep `model_summary()` stable so `/api/model/metrics` needs no changes.

- [ ] **Step 5: Update the container entry point**

Keep `CMD ["python", "-m", "fire_risk.ml_api"]` and ensure the module calls `main()` so the existing Compose environment continues to control host and port.

- [ ] **Step 6: Run ML tests**

Run: `python -m pytest services/ml/tests/test_ml_api.py services/ml/tests/test_ml_artifact.py -q`

Expected: PASS, including real artifact load and OpenAPI tests.

- [ ] **Step 7: Commit the FastAPI service**

```powershell
git add services/ml/pyproject.toml services/ml/src/fire_risk/ml_api.py services/ml/tests/test_ml_api.py services/ml/Dockerfile
git commit -m "feat(ml): expose inference through FastAPI"
```

### Task 2: Complete held-out demonstration scenarios

**Files:**
- Create: `scripts/export-model-demo-scenarios.py`
- Create: `services/api/FireRisk.Api/Data/model-demo-scenarios.json`
- Create: `services/api/FireRisk.Api/ModelDemoScenarioCatalog.cs`
- Create: `services/api/FireRisk.Api.Tests/ModelDemoScenarioCatalogTests.cs`
- Modify: `services/api/FireRisk.Api/FireRisk.Api.csproj`

**Interfaces:**
- Consumes: `.artifacts/full-2019-2026-v2/acceptance/60-feature-snapshots.parquet`, `30-normalized-events.parquet`, `31-object-inventory.parquet`, and `.artifacts/ml/catboost-synthetic-v1/manifest.json` at export time.
- Produces: a JSON document with a root `featureNames` schema and `scenarios`, plus `ModelDemoScenarioCatalog.List() -> IReadOnlyList<ModelDemoScenarioSummary>` and `ModelDemoScenarioCatalog.Get(string id) -> ModelDemoScenario`. A full scenario contains exactly the schema feature names plus presentation context.

- [ ] **Step 1: Write failing catalog tests**

Add xUnit tests asserting:

- catalog IDs are unique and include `normal`, `smoke-heat`, `gas-growth`, and `malfunction`;
- every scenario has a 2026 `SourceTimestamp`, object context, and at least one presented sensor;
- every feature name from the bundled root `featureNames` schema is present exactly once in each scenario;
- `hour`, ISO `weekday`, and `month` match `SourceTimestamp` in Europe/Moscow;
- unknown IDs throw `KeyNotFoundException`;
- summaries contain no feature dictionary or expected probability.

- [ ] **Step 2: Run catalog tests and confirm they fail**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoScenarioCatalogTests`

Expected: FAIL because the catalog and bundled data do not exist.

- [ ] **Step 3: Implement the deterministic exporter**

Create `scripts/export-model-demo-scenarios.py` with CLI arguments `--snapshots`, `--events`, `--inventory`, `--manifest`, and `--output`. Select deterministic 2026 rows using feature predicates for the four named scenarios, copy all manifest features, derive source calendar assertions in Europe/Moscow, and join only the nearby normalized events and object inventory needed for readable object/sensor context. Omit labels and model probabilities.

- [ ] **Step 4: Export and validate the bundled catalog**

Run the exporter against the existing acceptance Parquet and manifest. Verify the JSON contains four complete feature vectors and remains small enough to commit.

- [ ] **Step 5: Implement the catalog reader**

Add records `ModelDemoSensor`, `ModelDemoScenarioSummary`, and `ModelDemoScenario` plus `ModelDemoScenarioCatalog(string path)`. It loads `Data/model-demo-scenarios.json`, validates unique IDs and that every feature map exactly matches root `featureNames`, exposes summaries, and rejects unknown IDs. Configure the JSON file to copy to the API output directory and register the singleton through a factory using `IHostEnvironment.ContentRootPath`; tests construct it with a temporary fixture path.

- [ ] **Step 6: Run catalog and existing domain tests**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj`

Expected: PASS.

- [ ] **Step 7: Commit scenario data and catalog**

```powershell
git add scripts/export-model-demo-scenarios.py services/api/FireRisk.Api/Data/model-demo-scenarios.json services/api/FireRisk.Api/ModelDemoScenarioCatalog.cs services/api/FireRisk.Api.Tests/ModelDemoScenarioCatalogTests.cs services/api/FireRisk.Api/FireRisk.Api.csproj
git commit -m "feat(api): add held-out model demo scenarios"
```

### Task 3: Non-persisting ASP.NET demonstration endpoints

**Files:**
- Modify: `services/api/FireRisk.Api/Contracts.cs`
- Modify: `services/api/FireRisk.Api/MlClient.cs`
- Modify: `services/api/FireRisk.Api/Program.cs`
- Create: `services/api/FireRisk.Api/ModelDemoService.cs`
- Create: `services/api/FireRisk.Api.Tests/ModelDemoServiceTests.cs`

**Interfaces:**
- Consumes: `ModelDemoScenarioCatalog.Get(string id)` and `IMlGateway.PredictAsync(PredictRequest, CancellationToken)`.
- Produces: `GET /api/model-demo/scenarios` and `POST /api/model-demo/predict` with request `{ "scenarioId": string }` and response `{ scenario, prediction }`.

- [ ] **Step 1: Add failing service tests**

Use a fake prediction gateway to assert:

- a known scenario forwards every catalog feature and default `TopK=5`;
- context fields and `SourceTimestamp` are not forwarded as features;
- the returned prediction keeps its fresh `CalculatedAt` value;
- an unknown ID maps to not-found behavior;
- the service has no `PgStore` dependency and therefore cannot persist alerts, requests, or SMS.

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoServiceTests`

Expected: FAIL because the service and contracts do not exist.

- [ ] **Step 3: Introduce a prediction gateway boundary**

Define `IMlGateway` with the existing `GetModelAsync` and `PredictAsync` operations, and make `MlClient` implement it. Register `AddHttpClient<IMlGateway, MlClient>(...)` and change the existing route injections from `MlClient` to `IMlGateway` without changing their behavior.

- [ ] **Step 4: Implement `ModelDemoService` and contracts**

Add `ModelDemoPredictionRequest(string ScenarioId)` and `ModelDemoPredictionResponse(ModelDemoScenarioSummary Scenario, MlPrediction Prediction)`. Implement `ModelDemoService.PredictAsync(string scenarioId, CancellationToken)` to resolve the scenario, forward its complete feature dictionary, and return without calling `PgStore`.

- [ ] **Step 5: Map the two API routes**

Register the catalog and service as singletons/scoped dependencies, map scenario listing, map prediction, and convert `KeyNotFoundException` to HTTP 404 with `{ error: "scenario not found" }`.

- [ ] **Step 6: Run API tests**

Run: `dotnet test --no-restore`

Expected: all API and domain tests PASS.

- [ ] **Step 7: Commit API endpoints**

```powershell
git add services/api/FireRisk.Api/Contracts.cs services/api/FireRisk.Api/MlClient.cs services/api/FireRisk.Api/Program.cs services/api/FireRisk.Api/ModelDemoService.cs services/api/FireRisk.Api.Tests/ModelDemoServiceTests.cs
git commit -m "feat(api): expose non-persisting model demonstration"
```

### Task 4: Demonstration page and bottom sidebar entry

**Files:**
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/api.ts`
- Create: `services/web/src/ModelDemoPage.tsx`
- Create: `services/web/src/modelDemo.ts`
- Create: `services/web/src/ModelDemoPage.test.tsx`
- Modify carefully: `services/web/src/App.tsx`
- Modify carefully: `services/web/src/App.test.tsx`
- Modify carefully: `services/web/src/domain.ts`
- Modify carefully: `services/web/src/domain.test.ts`
- Modify carefully: `services/web/src/styles.css`

**Interfaces:**
- Consumes: `GET /api/model-demo/scenarios` and `POST /api/model-demo/predict`.
- Produces: `api.listModelDemoScenarios()`, `api.predictModelDemo(scenarioId: string)`, route `/model-demo`, `ModelDemoPage`, and a bottom-pinned sidebar link available for every `UserRole`.

- [ ] **Step 1: Add failing data-contract and copy tests**

Define tests for API normalization and `modelDemoFactorLabel(feature: string) -> string` covering common window suffixes, temperature, gas, alarm count, and a readable fallback. Assert demonstration types contain source time, sensor context, four probabilities, decisions, factors, and calculation time but no expected probability in scenario summaries.

- [ ] **Step 2: Add failing page/navigation tests**

Render each existing role and assert:

- there is no `Тестировщик` option;
- `Демонстрация модели` is rendered after the main navigation in a bottom-pinned container;
- `/model-demo` is allowed for all roles without exposing unrelated role navigation;
- the page shows scenario, object, sensors, and read-only source date/time;
- pressing `Рассчитать прогноз` shows loading, then four horizon values, threshold states, factors, and separate `Рассчитано` time;
- switching scenarios clears the prior result;
- an API error leaves no stale result and shows a concise error;
- rendered demonstration-page text does not contain `CatBoost`, `.cbm`, or package names.

- [ ] **Step 3: Run web tests and confirm they fail**

Run: `npm test -- --run` from `services/web`.

Expected: FAIL because the types, API methods, route, and page do not exist.

- [ ] **Step 4: Implement web contracts and API methods**

Add focused `ModelDemoScenario`, `ModelDemoPrediction`, and factor types. Implement the two API calls without demo-memory fallback: an unavailable backend must reject so the page can show a truthful failure state.

- [ ] **Step 5: Implement labels and `ModelDemoPage`**

Keep state local to `ModelDemoPage`: scenarios, selected ID, loading, result, and error. Render source time with the existing Russian date formatter, keep it non-editable, submit only scenario ID, clear stale results on selection, and use neutral user-facing copy without implementation names.

- [ ] **Step 6: Integrate route and bottom sidebar link**

Add `/model-demo` to `allowedNavigation` for every role, but render its link in a separate `sidebar-demo-link` container after normal navigation so it stays at the bottom. Merge around existing uncommitted role/request edits instead of replacing those files wholesale.

- [ ] **Step 7: Add focused styling**

Add responsive scenario/result grids, source-time and limitation styles, loading/disabled state, threshold badges, and bottom sidebar placement. Reuse existing color variables and panel typography.

- [ ] **Step 8: Run web verification**

Run from `services/web`:

```powershell
npm test -- --run
npm run typecheck
npm run build
```

Expected: all commands PASS.

- [ ] **Step 9: Commit the web demonstration**

Stage only the intended merged hunks and verify the diff preserves pre-existing user changes before committing:

```powershell
git diff -- services/web/src/App.tsx services/web/src/domain.ts services/web/src/styles.css
git add services/web/src/types.ts services/web/src/api.ts services/web/src/ModelDemoPage.tsx services/web/src/modelDemo.ts services/web/src/ModelDemoPage.test.tsx services/web/src/App.tsx services/web/src/App.test.tsx services/web/src/domain.ts services/web/src/domain.test.ts services/web/src/styles.css
git commit -m "feat(web): add model demonstration workspace"
```

### Task 5: End-to-end verification and documentation

**Files:**
- Modify: `scripts/smoke.ps1`
- Modify: `README.md`
- Modify: `docs/validation-report.md`

**Interfaces:**
- Consumes: completed FastAPI, ASP.NET demo endpoints, and web route.
- Produces: a repeatable operator/judge check covering OpenAPI and real non-persisting inference.

- [ ] **Step 1: Add failing smoke assertions**

Extend `scripts/smoke.ps1` to assert:

- `http://localhost:8000/docs` is reachable;
- scenario listing returns the four stable IDs without feature dictionaries;
- demo prediction returns the selected source timestamp, a fresh calculation timestamp, four probabilities, and factors;
- the demo prediction values equal a direct `/ml/predict` call made by the smoke script with the same server-side scenario fixture;
- counts from `/api/alerts`, `/api/requests`, and `/api/sms` do not change after the prediction.

- [ ] **Step 2: Rebuild and run the complete stack**

Run:

```powershell
docker compose up --build -d
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1
```

Expected: smoke script exits successfully and reports the model demonstration check as passed.

- [ ] **Step 3: Run all repository verification**

Run:

```powershell
python -m pytest services/ml/tests -q
dotnet test --no-restore
Set-Location services/web
npm test -- --run
npm run build
```

Expected: every command PASS.

- [ ] **Step 4: Perform visual verification**

Open `http://localhost:8080/model-demo` for at least technician and ODS roles. Verify the link remains at the sidebar bottom, both timestamps are distinct and clear, no implementation-specific model name appears, all scenario context fits at 1920×1080, and a second scenario cannot display the first result.

- [ ] **Step 5: Update documentation**

Document the `/docs` URL, judge demonstration steps, held-out scenario provenance, object-level semantics, proxy-label limitation, and non-persisting behavior. Remove the outdated README statement that trained artifacts are connected separately if it remains present.

- [ ] **Step 6: Commit verification and docs**

```powershell
git add scripts/smoke.ps1 README.md docs/validation-report.md
git commit -m "docs: verify model demonstration workflow"
```

- [ ] **Step 7: Final diff and artifact audit**

Run `git status --short`, `git diff --check`, and inspect every changed file. Confirm no generated caches, Parquet data, model binaries, database volumes, unrelated user edits, or expected probabilities were added.
