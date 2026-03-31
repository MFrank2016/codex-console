# Dual Pipeline Failure Read-side Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the registration failure read-side so structured pipeline failure fields can be filtered and returned consistently from the facade and failure APIs.

**Architecture:** Reuse the structured failure fields already persisted in phase 2 (`failure_stage`, `step_key`, `retryable`) and thread them through the read-side boundary. Keep the scope backend-only: extend the query facade and failure routes first, then expose richer list/summary payloads without pulling UI work into this phase.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy ORM, pytest.

---

## File Structure Map

### Modified files
- Modify: `src/application/registration_query_dtos.py` — extend failure summary DTO contract for structured dimensions.
- Modify: `src/application/registration_query_facade.py` — accept structured failure filters, forward them to repository queries, and shape richer summary payloads.
- Modify: `src/database/repositories/registration_failure_repository.py` — aggregate structured summary dimensions from persisted failure records.
- Modify: `src/web/routes/registration.py` — accept structured query params and expose richer response models.

### Tests
- Modify: `tests/test_registration_query_facade.py`
- Modify: `tests/test_registration_failure_routes.py`
- Modify: `tests/test_registration_failure_repository.py`

---

### Task 1: Extend repository/facade summary and filters for structured failure fields

**Files:**
- Modify: `src/database/repositories/registration_failure_repository.py`
- Modify: `src/application/registration_query_dtos.py`
- Modify: `src/application/registration_query_facade.py`
- Test: `tests/test_registration_failure_repository.py`
- Test: `tests/test_registration_query_facade.py`

- [x] **Step 1: Write failing repository/facade tests for `failure_stage`, `step_key`, `retryable` filter propagation and summary aggregation**
- [x] **Step 2: Run focused repository/facade tests and verify failure before implementation**
- [x] **Step 3: Extend repository summary payload with structured dimensions / retryable breakdown**
- [x] **Step 4: Extend facade filter builder and summary/list methods to accept the structured filters**
- [x] **Step 5: Run focused repository/facade tests and verify pass**

### Task 2: Expose structured failure fields in failure APIs

**Files:**
- Modify: `src/web/routes/registration.py`
- Modify: `src/application/registration_query_dtos.py`
- Test: `tests/test_registration_failure_routes.py`

- [x] **Step 1: Write failing route tests for structured query params and structured response payload fields**
- [x] **Step 2: Run focused route tests and verify failure before implementation**
- [x] **Step 3: Extend route query params / response models to expose structured failure fields**
- [x] **Step 4: Keep route behavior as pure facade delegation with `ValueError -> HTTP 400` mapping**
- [x] **Step 5: Run focused route tests and verify pass**

### Task 3: Focused regression pass for phase 4

**Files:**
- Modify: `tests/test_registration_failure_repository.py`
- Modify: `tests/test_registration_query_facade.py`
- Modify: `tests/test_registration_failure_routes.py`

- [x] **Step 1: Run the combined phase-4 regression suite**
- [x] **Step 2: Fix any breakage without expanding scope to UI/panel work**
- [x] **Step 3: Summarize remaining handoff items after backend read-side expansion**
