# Model Demo Presentation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the agreed model-demo layout, explain inputs and factors clearly, and label calculated examples without changing the 12/12 held-out scenario set.

**Architecture:** Extend the safe scenario summary with a small presentation-only input summary derived from the server-side feature vector. Keep inference inputs and predictions unchanged; render a stable two-column input/result layout and derive the example tag only from the returned model decisions.

**Tech Stack:** ASP.NET Core 8, React 19, TypeScript, Vitest, CSS.

**Spec:** `docs/superpowers/specs/2026-09-29-model-demonstration-fastapi-design.md`

## Global Constraints

- Keep the existing 24 scenarios and their 12 safe / 12 dangerous composition.
- Do not expose the complete feature vector or a prepared prediction to the browser.
- Do not mention the model algorithm or library in user-facing copy.
- Describe the result as object-level risk, not a prediction for one sensor.
- Remove the blue instructional notice.
- Use short Russian labels without long explanatory sentences or em dashes.

## Review Focus

- A scenario with no calculation must not reveal whether it is safe or dangerous.
- A calculated scenario with any positive decision must show `Тревожный пример`; otherwise it must show `Штатный пример`.
- Missing or null presentation features must render a useful fallback and must not break the page.
- Repeated factors from different horizons must not produce repeated generic rows.
- The responsive layout must remain readable as one column on narrow screens.

---

### Task 1: Safe readable input summary

**Files:**
- Modify: `services/api/FireRisk.Api/ModelDemoScenarioCatalog.cs`
- Modify: `services/api/FireRisk.Api.Tests/ModelDemoScenarioCatalogTests.cs`
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/api.ts`
- Modify: `services/web/src/api.test.ts`

**Interfaces:**
- Produces: `ModelDemoScenarioSummary.Inputs`, a curated list of label/value pairs derived from existing server-side features.
- Consumes: the existing complete catalog feature vector.

- [ ] Write failing API and web normalization tests proving curated inputs are returned while `features` and prepared probabilities remain hidden.
- [ ] Run focused tests and confirm the new assertions fail.
- [ ] Implement the presentation-only input summary with concise labels and safe fallbacks.
- [ ] Run focused API and web tests and confirm they pass.

### Task 2: Agreed page composition and concise factors

**Files:**
- Modify: `services/web/src/ModelDemoPage.tsx`
- Modify: `services/web/src/modelDemo.ts`
- Modify: `services/web/src/modelDemo.test.ts`
- Modify: `services/web/src/ModelDemoPage.test.tsx`
- Modify: `services/web/src/styles.css`

**Interfaces:**
- Consumes: `ModelDemoScenario.inputs` and calculated prediction decisions/factors.
- Produces: `Проверка обученной модели`, side-by-side `Входные данные` / `Результат прогноза`, a concise factor list, and a post-calculation example tag.

- [ ] Write failing rendering and helper tests for removed notice, stable blocks, post-calculation tags, concise factor labels, influence labels, and factor de-duplication.
- [ ] Run focused web tests and confirm they fail for the intended reasons.
- [ ] Implement the layout, tags, concise factor presentation, and responsive CSS without changing navigation or workflow behavior.
- [ ] Run focused tests, then the complete web and API suites, typecheck, and production build.

### Task 3: Final verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: the completed API and web changes.
- Produces: evidence that the page and existing workflow remain operational.

- [ ] Run the complete repository checks named by the existing model-demo plan.
- [ ] Inspect the final diff for user-facing implementation names, the removed notice, and unintended scenario-catalog changes.
- [ ] Perform a fresh whole-change code review and address any important findings through RED-GREEN tests.
