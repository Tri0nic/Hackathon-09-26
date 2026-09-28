# Role Workspaces and Request Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver role-specific workspaces, detailed request creation, group SMS dispatch on creation, and first-claim assignment.

**Architecture:** Extend the shared request/SMS contracts and PostgreSQL schema, centralize authorization and routing rules in pure domain helpers, and make both server-backed and demo-mode flows use the same payloads. React derives navigation and page behavior from the selected role and employee.

**Tech Stack:** React, TypeScript, Vitest, ASP.NET Core minimal API, C#, xUnit, PostgreSQL, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-28-role-workspaces-and-requests.md`

## Global Constraints

- SMS is created on request creation only.
- The first successful claim owns the request.
- ODS creates emergency response-team requests only.
- Analytics remains visible only to ODS.
- Preserve existing unrelated workspace changes.

## Review Focus

- A second simultaneous claim must not replace the first assignee.
- ODS payloads that attempt non-emergency or technician routing must be rejected.
- A failed SMS must remain `undelivered` when request status changes.
- Role switching must redirect away from a now-forbidden route.
- Empty or malformed request fields must not create requests or notifications.

---

### Task 1: Domain contracts and role policy

**Files:**
- Modify: `services/api/FireRisk.Api/Domain/BusinessRules.cs`
- Modify: `services/api/FireRisk.Api.Tests/BusinessRulesTests.cs`
- Modify: `services/api/FireRisk.Api/Contracts.cs`
- Modify: `services/web/src/types.ts`
- Modify: `services/web/src/domain.ts`
- Test: `services/web/src/domain.test.ts`

**Interfaces:**
- Produces request executor/priority types, employee profiles, role navigation policy, and request-creation validation.

- [ ] Write failing C# and TypeScript tests for ODS restrictions, role navigation, and claim eligibility.
- [ ] Run focused suites and confirm failures are caused by missing policies.
- [ ] Add the minimal contracts and pure policy helpers.
- [ ] Run focused and full suites to green.

### Task 2: Persistence, request dispatch, and atomic claim API

**Files:**
- Modify: `services/api/FireRisk.Api/Migrations/001_initial.sql`
- Modify: `services/api/FireRisk.Api/PgStore.cs`
- Modify: `services/api/FireRisk.Api/Program.cs`
- Modify: `services/api/FireRisk.Api.Tests/BusinessRulesTests.cs`

**Interfaces:**
- Consumes: request policy and expanded creation contract from Task 1.
- Produces: `POST /api/alerts/{id}/requests` with complete payload and `POST /api/requests/{id}/claim` with conflict protection.

- [ ] Write failing policy tests proving request-created recipient expansion and removal of level-based SMS policy.
- [ ] Run tests and confirm the expected failures.
- [ ] Extend schema/query projections and create request plus recipient SMS records in one transaction.
- [ ] Remove prediction-triggered SMS dispatch and implement conditional atomic claim.
- [ ] Run API tests to green.

### Task 3: Demo API behavior

**Files:**
- Modify: `services/web/src/demo.ts`
- Modify: `services/web/src/api.ts`
- Modify: `services/web/src/api.test.ts`

**Interfaces:**
- Consumes: expanded TypeScript request and employee contracts.
- Produces: `api.createRequest(payload)` and `api.claimRequest(requestId, employee)` with server/demo parity.

- [ ] Write failing normalization and demo mutation tests for expanded requests, per-employee SMS, and first claim.
- [ ] Run tests and confirm behavioral failures.
- [ ] Implement normalization and in-memory/server API methods.
- [ ] Run web API tests to green.

### Task 4: Role-specific workspace and request form

**Files:**
- Modify: `services/web/src/App.tsx`
- Modify: `services/web/src/styles.css`
- Modify: `services/web/src/App.test.tsx`

**Interfaces:**
- Consumes: role policies, employee fixtures, and API methods from Tasks 1-3.
- Produces: role-filtered navigation, employee chooser, `/alerts/{id}/request` form, and executor request actions.

- [ ] Write failing render tests for each role, employee selection, request form restrictions, available/own request sections, and footer removal.
- [ ] Run tests and confirm failures are caused by missing UI behavior.
- [ ] Implement role-aware navigation and safe-route fallback.
- [ ] Implement request form and claim UI.
- [ ] Run web tests and typecheck to green.

### Task 5: Integrated verification

**Files:**
- Modify only files required by failures discovered during verification.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a running local site with verified role and request workflows.

- [ ] Run complete web tests, typecheck, and production build.
- [ ] Run complete API tests.
- [ ] Rebuild/restart Docker Compose services.
- [ ] Verify health, request creation, recipient SMS count, and claim conflict through live endpoints.

