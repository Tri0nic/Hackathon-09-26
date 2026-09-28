# Model Demonstration and Dispatcher Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom ML HTTP adapter with FastAPI and add a held-out model demonstration that can publish dangerous calculations into the existing dispatcher, request, and SMS workflow.

**Architecture:** FastAPI preserves the current ML contract and adds OpenAPI. The ASP.NET API owns an ordered catalog of 24 complete held-out snapshots, caches each fresh calculation for 30 minutes, and publishes a trusted dangerous result exactly once into PostgreSQL with internal demo markers. React presents the sequence through a bottom sidebar page and reuses existing alert and request screens after publication.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pydantic, existing ML runtime, ASP.NET Core 10 Minimal API, `IMemoryCache`, Npgsql/PostgreSQL, React, TypeScript, Vitest, xUnit, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-model-demonstration-fastapi-design.md`

## Global Constraints

- Use exactly 24 complete `object_id × scoring_timestamp` rows from the held-out 2026 test period, never training rows.
- Store no expected probabilities; every displayed value must come from the running inference service.
- Keep complete feature vectors server-side and submit only scenario or calculation IDs from the browser.
- Keep the source timestamp read-only and display it separately from the new `Рассчитано` timestamp.
- Preserve successful contracts for `GET /health`, `GET /ml/models/current`, and `POST /ml/predict`; FastAPI validation errors use HTTP 422.
- Do not add a `Тестировщик` role or alter existing role permissions.
- Place `Демонстрация модели` at the bottom of the left sidebar for every existing role.
- Do not show algorithm, package, or native artifact names in user-facing demonstration copy.
- Treat sensors as input context and predictions as object-level results.
- Cache unpublished calculations for exactly 30 minutes.
- Publish only threshold-exceeding results, exactly once, and never overwrite a non-demo warning.
- Render `Демо` inside existing alert UI; do not add a table column.
- Cleanup must remove all and only demonstration workflow data in one database transaction.
- Preserve the user's existing uncommitted edits in `services/web/src/App.tsx`, its tests, domain helpers, and styles.

## Review Focus

- A malformed or drifted scenario catalog fails clearly before inference; it never fills missing features silently.
- An expired, unknown, safe, or already-published calculation has deterministic server behavior and cannot create a duplicate warning.
- Two simultaneous publish requests for one `calculationId` return the same alert and create one database chain.
- Publishing a demo result for an object with a non-demo current warning leaves that warning unchanged.
- A late prediction response received after the user advances never attaches stale results to the newly displayed row.

---

### Task 1: FastAPI ML adapter

**Files:**
- Modify: `services/ml/pyproject.toml`
- Replace: `services/ml/src/fire_risk/ml_api.py`
- Modify: `services/ml/tests/test_ml_api.py`
- Modify: `services/ml/Dockerfile`

**Interfaces:**
- Consumes: `Predictor.predict(features: dict[str, float | int | bool | None], top_k: int) -> Prediction` from `fire_risk.ml.inference`.
- Produces: `create_app(predictor: Predictor, manifest: dict[str, Any]) -> FastAPI`, `create_runtime_app() -> FastAPI`, and `main() -> None`.

- [ ] **Step 1: Add failing FastAPI contract tests**

Extend `services/ml/tests/test_ml_api.py` with a fake predictor and tests named `test_health`, `test_model_summary`, `test_predict_accepts_top_k_spellings`, `test_predict_rejects_invalid_body`, and `test_openapi_and_docs`. Assert both `topK` and `top_k` reach the fake predictor, absent features and non-positive top K return 422, and all three routes appear in `/openapi.json`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python -m pytest services/ml/tests/test_ml_api.py -q`

Expected: FAIL because `create_app` and FastAPI validation/OpenAPI do not exist.

- [ ] **Step 3: Add FastAPI runtime dependencies**

Add `fastapi>=0.115,<1` and `uvicorn>=0.32,<1` to project dependencies and `httpx>=0.27,<1` to the `dev` extra in `services/ml/pyproject.toml`.

- [ ] **Step 4: Implement the adapter**

Implement `PredictionRequest(BaseModel)` using `AliasChoices("topK", "top_k")`, positive validation, and default 5. Implement the three routes in `create_app`, load `FIRE_RISK_MODEL` once in `create_runtime_app`, and make `main()` pass `FIRE_RISK_ML_HOST` and `FIRE_RISK_ML_PORT` to Uvicorn. Preserve existing success response keys and `model_summary()` behavior.

- [ ] **Step 5: Keep the container entry point compatible**

Keep module execution as the Docker command and ensure `python -m fire_risk.ml_api` calls `main()`.

- [ ] **Step 6: Verify the ML service**

Run: `python -m pytest services/ml/tests/test_ml_api.py services/ml/tests/test_ml_artifact.py -q`

Expected: PASS, including real artifact loading and OpenAPI tests.

- [ ] **Step 7: Commit**

```powershell
git add services/ml/pyproject.toml services/ml/src/fire_risk/ml_api.py services/ml/tests/test_ml_api.py services/ml/Dockerfile
git commit -m "feat(ml): expose inference through FastAPI"
```

### Task 2: Held-out sequence and validated catalog

**Files:**
- Create: `scripts/export-model-demo-scenarios.py`
- Create: `services/api/FireRisk.Api/Data/model-demo-scenarios.json`
- Create: `services/api/FireRisk.Api/ModelDemoScenarioCatalog.cs`
- Create: `services/api/FireRisk.Api.Tests/ModelDemoScenarioCatalogTests.cs`
- Modify: `services/api/FireRisk.Api/FireRisk.Api.csproj`

**Interfaces:**
- Consumes: acceptance `60-feature-snapshots.parquet`, nearby rows from `30-normalized-events.parquet`, `31-object-inventory.parquet`, and the deployed model directory/manifest.
- Produces: `ModelDemoScenarioCatalog.List() -> IReadOnlyList<ModelDemoScenarioSummary>` and `ModelDemoScenarioCatalog.Get(string id) -> ModelDemoScenario`; JSON root fields are `featureNames` and ordered `scenarios`.

- [ ] **Step 1: Add failing catalog tests**

Create tests asserting the catalog has exactly 24 unique ordered IDs; every source timestamp is in the held-out 2026 period; every feature dictionary exactly matches root `featureNames`; `hour`, ISO `weekday`, and `month` agree with Europe/Moscow source time; every summary has object, district, and sensor context but no features or expected probability; unknown IDs throw `KeyNotFoundException`; a fixture with a missing or extra feature throws `InvalidDataException`.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoScenarioCatalogTests`

Expected: FAIL because the catalog implementation and data do not exist.

- [ ] **Step 3: Implement the deterministic exporter**

Create a CLI with required `--snapshots`, `--events`, `--inventory`, `--model-dir`, and `--output` arguments. Select exactly 24 stable, chronologically ordered 2026 test rows; use the deployed predictor only to ensure the set contains both threshold-safe and threshold-exceeding examples; copy all manifest feature values; lazily filter the large event Parquet to only selected object/time windows; attach readable context; omit labels, decisions, and probabilities from output.

- [ ] **Step 4: Export the committed catalog**

Run the exporter against the three required files in `.artifacts/full-2019-2026-v2/acceptance` and the model directory `.artifacts/ml/catboost-synthetic-v1`. Verify the output contains exactly 24 scenarios, includes both safe and threshold-exceeding rows when recalculated, stores no model outputs, and is small enough to commit.

- [ ] **Step 5: Implement `ModelDemoScenarioCatalog`**

Define `ModelDemoSensor`, `ModelDemoScenarioSummary`, and `ModelDemoScenario`. Implement `ModelDemoScenarioCatalog(string path)` with eager validation and immutable ordered storage. Register it through an `IHostEnvironment.ContentRootPath` factory and configure the JSON as API content copied to output; tests use temporary fixture paths.

- [ ] **Step 6: Verify the catalog**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoScenarioCatalogTests`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add scripts/export-model-demo-scenarios.py services/api/FireRisk.Api/Data/model-demo-scenarios.json services/api/FireRisk.Api/ModelDemoScenarioCatalog.cs services/api/FireRisk.Api.Tests/ModelDemoScenarioCatalogTests.cs services/api/FireRisk.Api/FireRisk.Api.csproj
git commit -m "feat(api): add held-out model demo sequence"
```

### Task 3: Prediction API and 30-minute cache

**Files:**
- Modify: `services/api/FireRisk.Api/Contracts.cs`
- Modify: `services/api/FireRisk.Api/MlClient.cs`
- Create: `services/api/FireRisk.Api/ModelDemoCalculationCache.cs`
- Create: `services/api/FireRisk.Api/ModelDemoService.cs`
- Create: `services/api/FireRisk.Api.Tests/ModelDemoCalculationTests.cs`
- Modify: `services/api/FireRisk.Api/Program.cs`

**Interfaces:**
- Consumes: `ModelDemoScenarioCatalog.Get(string id)` and `IMlGateway.PredictAsync(PredictRequest, CancellationToken)`.
- Produces: `ModelDemoService.PredictAsync(string scenarioId, CancellationToken) -> ModelDemoPredictionResponse`, `GET /api/model-demo/scenarios`, and `POST /api/model-demo/predict`.

- [ ] **Step 1: Add failing service/cache tests**

Test that a known ID forwards every catalog feature with `TopK=5`; context never enters the feature dictionary; the response contains a new `CalculationId`, source and calculated timestamps, and all prediction fields; unknown IDs fail; an unavailable ML gateway propagates failure without a cached result; advancing/listing does not run inference; and a calculation is retrievable before but not at or after 30 minutes using a fake `TimeProvider`.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoCalculationTests`

Expected: FAIL because the contracts, gateway, cache, and service do not exist.

- [ ] **Step 3: Introduce the ML gateway boundary**

Define `IMlGateway` with `GetModelAsync(CancellationToken)` and `PredictAsync(PredictRequest, CancellationToken)`. Make `MlClient` implement it, register `AddHttpClient<IMlGateway, MlClient>`, and switch existing route injection to the interface without changing operational behavior.

- [ ] **Step 4: Implement the calculation cache**

Define `DemoCalculation(Guid Id, string ScenarioId, MlPrediction Prediction, DateTimeOffset ExpiresAt, Guid? PublishedAlertId)` and `ModelDemoCalculationCache(IMemoryCache cache, TimeProvider clock)`. Implement `Create`, `Get`, `MarkPublished`, and `Clear`; track only owned keys, enforce exact 30-minute expiry explicitly, and never compact unrelated application cache entries.

- [ ] **Step 5: Implement prediction service and endpoints**

Add request/response records with `ScenarioId`, `CalculationId`, scenario summary, and prediction. Implement `ModelDemoService.PredictAsync`; register `AddMemoryCache`, `TimeProvider.System`, cache, catalog, and service; map scenario listing and prediction; return 404 for an unknown scenario and 503 for inference unavailability.

- [ ] **Step 6: Verify calculation behavior**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoCalculationTests`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add services/api/FireRisk.Api/Contracts.cs services/api/FireRisk.Api/MlClient.cs services/api/FireRisk.Api/ModelDemoCalculationCache.cs services/api/FireRisk.Api/ModelDemoService.cs services/api/FireRisk.Api.Tests/ModelDemoCalculationTests.cs services/api/FireRisk.Api/Program.cs
git commit -m "feat(api): cache model demo calculations"
```

### Task 4: Idempotent publication and transactional cleanup

**Files:**
- Modify: `services/api/FireRisk.Api/Migrations/001_initial.sql`
- Modify: `services/api/FireRisk.Api/PgStore.cs`
- Modify: `services/api/FireRisk.Api/Contracts.cs`
- Modify: `services/api/FireRisk.Api/ModelDemoService.cs`
- Modify: `services/api/FireRisk.Api/Program.cs`
- Create: `services/api/FireRisk.Api.Tests/ModelDemoPublicationTests.cs`

**Interfaces:**
- Consumes: `ModelDemoCalculationCache.Get(Guid)`, scenario context, trusted `MlPrediction`, and `IModelDemoPublicationStore`.
- Produces: `ModelDemoService.PublishAsync(Guid, CancellationToken) -> ModelDemoPublicationResponse`, `ModelDemoService.ClearAsync(CancellationToken)`, `POST /api/model-demo/publish`, and `DELETE /api/model-demo/results`.

- [ ] **Step 1: Add failing publication policy tests**

Using fake persistence, assert an unknown/expired calculation returns not found, an all-false `Decisions` result is rejected, a dangerous result is published with `is_demo=true`, two sequential and two concurrent calls return one alert ID and invoke persistence once, a database uniqueness replay returns the existing alert ID, and failed persistence leaves the calculation retryable.

- [ ] **Step 2: Add failing store-boundary and cleanup tests**

Define a fake `IModelDemoPublicationStore` and assert the service passes the calculation ID, exact scenario, and trusted prediction once; does not call the store for safe/expired input; keeps a failed publication retryable; and invokes database cleanup before cache cleanup. Reserve SQL integration assertions for the mandatory Docker smoke in Task 6 because the repository has no disposable PostgreSQL test harness.

- [ ] **Step 3: Run focused tests and confirm failure**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj --filter ModelDemoPublicationTests`

Expected: FAIL because publication and cleanup do not exist.

- [ ] **Step 4: Extend the idempotent schema**

Add `is_demo boolean not null default false` and nullable `demo_calculation_id uuid` to `risk_predictions` and `risk_alerts`, plus partial unique indexes for non-null calculation IDs. Add internal demo markers to any object/channel rows created from catalog context so cleanup can remove them without matching names or prefixes.

- [ ] **Step 5: Implement transactional store operations**

Define `IModelDemoPublicationStore` with `PublishAsync(Guid calculationId, ModelDemoScenario scenario, MlPrediction prediction, CancellationToken) -> Task<Guid>` and `DeleteResultsAsync(CancellationToken) -> Task`. Make `PgStore` implement it. Publication upserts demo object/channel presentation context, inserts the prediction and warning without touching non-demo current rows, and handles a unique-key replay by returning the existing alert. Cleanup deletes dependent rows in the exact dependency order from the spec and commits atomically. Register the existing singleton `PgStore` as the interface implementation without creating a second instance.

- [ ] **Step 6: Implement publish synchronization and endpoints**

Add a keyed `SemaphoreSlim` boundary per calculation in `ModelDemoService.PublishAsync`, recheck cache state inside the lock, reject safe results, call the store, and mark the cache entry published. Implement `ClearAsync` to complete the database transaction before clearing owned cache keys. Map publish and delete endpoints with 404, 409, and 503 responses that do not expose internals.

- [ ] **Step 7: Expose the demo marker in existing alert JSON**

Add `isDemo` to alert list/detail query projections and corresponding C# or JSON contracts without adding a separate endpoint or changing role filters.

- [ ] **Step 8: Verify API behavior**

Run: `dotnet test services/api/FireRisk.Api.Tests/FireRisk.Api.Tests.csproj`

Expected: PASS, including concurrency, safe-result rejection, retryability, and cleanup ordering tests available without Docker.

- [ ] **Step 9: Commit**

```powershell
git add services/api/FireRisk.Api/Migrations/001_initial.sql services/api/FireRisk.Api/PgStore.cs services/api/FireRisk.Api/Contracts.cs services/api/FireRisk.Api/ModelDemoService.cs services/api/FireRisk.Api/Program.cs services/api/FireRisk.Api.Tests/ModelDemoPublicationTests.cs
git commit -m "feat(api): publish demo predictions to dispatcher workflow"
```

### Task 5: Demonstration page and existing workflow UI

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
- Consumes: scenario list, predict, publish, and cleanup endpoints plus existing alert/request endpoints.
- Produces: `/model-demo`, cyclic local selection, `api.predictModelDemo`, `api.publishModelDemo`, `api.clearModelDemoResults`, and `Alert.isDemo` rendering.

- [ ] **Step 1: Add failing contract/helper tests**

Test API normalization for scenario summaries, calculation responses, publication response, and `Alert.isDemo`. Test `modelDemoFactorLabel(feature: string) -> string` for common windows, temperature, gas, alarm counts, and a readable fallback. Assert no scenario summary type can carry features or expected probabilities.

- [ ] **Step 2: Add failing page/navigation tests**

For every existing role, assert no `Тестировщик` option exists and `Демонстрация модели` is the last, bottom-pinned navigation item. Test that `Следующие показания` cycles after row 24 without an API prediction call and clears the old result; a late response for the prior row is ignored; calculation shows four horizons and both timestamps; safe results disable publication with `Порог предупреждения не превышен`; dangerous results publish once and show `Открыть предупреждение`; errors cannot show stale results; cleanup asks for confirmation and refreshes data; user copy contains no implementation names.

- [ ] **Step 3: Add failing existing-workflow badge tests**

Render alert list and detail with `isDemo=true` and assert a single compact `Демо` badge appears beside the existing risk/title content, no new table header is added, and non-demo alerts render no badge.

- [ ] **Step 4: Run web tests and confirm failure**

Run from `services/web`: `npm test -- --run`

Expected: FAIL because the contracts, methods, page, route, and badge do not exist.

- [ ] **Step 5: Implement web contracts and API methods**

Add focused scenario/calculation/publication types and `isDemo` to `Alert`. Implement list, predict, publish, and delete calls without a prepared-probability fallback. After publish or cleanup, refresh application data through the existing load path.

- [ ] **Step 6: Implement `ModelDemoPage`**

Keep current index, result, publication, loading, and error state local. Render source time read-only; submit only scenario ID or calculation ID; advance cyclically; clear result before changing index; disable publish unless a threshold is true; retain a result after retryable publish failure; and confirm cleanup.

- [ ] **Step 7: Integrate route, sidebar, and badge**

Allow `/model-demo` for every role but render its link separately after normal navigation in a bottom-pinned container. Add the badge inside existing alert cells/details. Merge around the user's uncommitted role/request changes rather than replacing whole files.

- [ ] **Step 8: Add focused responsive styling**

Style the scenario/result grids, controls, loading states, inline limitation, bottom link, and compact badge using existing variables. Keep current table columns and normal desktop row height.

- [ ] **Step 9: Verify the web app**

Run from `services/web`:

```powershell
npm test -- --run
npm run typecheck
npm run build
```

Expected: all commands PASS.

- [ ] **Step 10: Audit and commit merged web changes**

Inspect intended hunks against the pre-existing dirty state, then stage only the feature files/hunks.

```powershell
git diff -- services/web/src/App.tsx services/web/src/domain.ts services/web/src/styles.css
git add services/web/src/types.ts services/web/src/api.ts services/web/src/ModelDemoPage.tsx services/web/src/modelDemo.ts services/web/src/ModelDemoPage.test.tsx services/web/src/App.tsx services/web/src/App.test.tsx services/web/src/domain.ts services/web/src/domain.test.ts services/web/src/styles.css
git commit -m "feat(web): add publishable model demonstration"
```

### Task 6: End-to-end workflow verification and documentation

**Files:**
- Modify: `scripts/smoke.ps1`
- Modify: `README.md`
- Modify: `docs/validation-report.md`

**Interfaces:**
- Consumes: completed FastAPI, calculation cache, publication API, PostgreSQL workflow, and web page.
- Produces: a repeatable judge/operator check from held-out row through request creation and cleanup.

- [ ] **Step 1: Add smoke assertions**

Extend `scripts/smoke.ps1` to verify `/docs`; exactly 24 summaries without features/probabilities; a direct ML call equals the demo API result for the same server-side fixture; a safe result cannot publish; a dangerous result creates one demo warning visible in existing alert APIs; replay returns the same alert ID; an existing request endpoint can create a request from it; and cleanup removes that chain while baseline counts and non-demo IDs remain unchanged.

- [ ] **Step 2: Rebuild and run the complete stack**

Run:

```powershell
docker compose up --build -d
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1
```

Expected: smoke exits successfully and reports inference, publication, workflow, idempotency, and cleanup checks as passed.

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

- [ ] **Step 4: Perform visual role verification**

At 1920×1080, verify technician and both dispatcher roles: the link stays at the sidebar bottom; next-row and calculate actions remain separate; source and calculation times are distinct; safe publication is disabled; a published warning has an inline badge without a new column; district/ODS visibility follows existing rules; and a resulting request reaches the intended executor role.

- [ ] **Step 5: Update documentation**

Document the `/docs` URL, 24-row held-out provenance, judge demonstration sequence, 30-minute cache, object-level semantics, proxy-label limitation, publication behavior, demo cleanup, and the fact that neither prediction nor publication retrains or mutates the model.

- [ ] **Step 6: Commit**

```powershell
git add scripts/smoke.ps1 README.md docs/validation-report.md
git commit -m "docs: verify dispatcher model demonstration"
```

- [ ] **Step 7: Final audit**

Run `git status --short`, `git diff --check`, and inspect every changed file. Confirm no generated caches, source Parquet data, model binaries, database volumes, unrelated user edits, or expected probabilities were committed.
