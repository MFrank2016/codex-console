# Dual Pipeline Structured Failure Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured registration failure fields and propagate pipeline step failure context from the shared runner into registration failure records for both pipelines.

**Architecture:** First extend failure persistence primitives (`RegistrationFailureRecord`, payload builders, migrations) with `failure_stage`, `step_key`, and `retryable`. Then teach `PipelineRunner` to raise a structured pipeline step execution error carrying retry metadata, and update `run_registration_job()` to persist that context into failure records without changing read-side APIs yet.

**Tech Stack:** FastAPI, SQLAlchemy ORM, existing pipeline runner, pytest.

---

## File Structure Map

### Modified files
- Modify: `src/database/models.py` — extend `RegistrationFailureRecord` with structured failure fields.
- Modify: `src/database/session.py` — add migration entries for new failure-record columns.
- Modify: `src/core/registration_failure_records.py` — extend failure query/write dataclasses and payload construction.
- Modify: `src/database/repositories/registration_failure_repository.py` — support storing and filtering structured failure fields.
- Modify: `src/core/pipeline/runner.py` — raise structured pipeline step execution errors with retry metadata.
- Modify: `src/core/registration_job.py` — catch structured pipeline errors and persist them to failure records.

### New files
- Create: `src/core/pipeline/errors.py` — structured pipeline failure context and exception types.

### Tests
- Modify: `tests/test_registration_failure_repository.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_registration_job.py`

---

### Task 1: Add structured registration failure fields to persistence primitives

**Files:**
- Modify: `src/database/models.py`
- Modify: `src/database/session.py`
- Modify: `src/core/registration_failure_records.py`
- Modify: `src/database/repositories/registration_failure_repository.py`
- Test: `tests/test_registration_failure_repository.py`

- [x] **Step 1: Write failing repository tests for `failure_stage`, `step_key`, and `retryable` round-tripping**
- [x] **Step 2: Run focused repository tests and verify failure before implementation**
- [x] **Step 3: Add model columns and migration entries for structured failure fields**
- [x] **Step 4: Extend payload builders and repository helpers to store/filter the new fields**
- [x] **Step 5: Run focused repository tests and verify pass**

### Task 2: Raise structured pipeline step failures from the shared runner

**Files:**
- Create: `src/core/pipeline/errors.py`
- Modify: `src/core/pipeline/runner.py`
- Test: `tests/test_pipeline_runner.py`

- [x] **Step 1: Write failing runner tests for structured step-failure exceptions**
- [x] **Step 2: Run focused runner tests and verify expected failure**
- [x] **Step 3: Add `PipelineStepFailureContext` and `PipelineStepExecutionError`**
- [x] **Step 4: Update `PipelineRunner` to raise structured failures while preserving retry metadata**
- [x] **Step 5: Run focused runner tests and verify pass**

### Task 3: Persist structured pipeline failure context in `run_registration_job()`

**Files:**
- Modify: `src/core/registration_failure_records.py`
- Modify: `src/core/registration_job.py`
- Test: `tests/test_registration_job.py`

- [x] **Step 1: Write failing registration-job tests for structured failure persistence**
- [x] **Step 2: Run focused job tests and verify failure before implementation**
- [x] **Step 3: Teach failure payload helpers to extract structured context from pipeline exceptions**
- [x] **Step 4: Catch `PipelineStepExecutionError` in `run_registration_job()` and persist structured fields**
- [x] **Step 5: Run focused job tests and verify pass**

### Task 4: Focused regression pass for phase 2

**Files:**
- Modify: `tests/test_registration_failure_repository.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_registration_job.py`

- [x] **Step 1: Run the combined phase-2 regression suite**
- [x] **Step 2: Fix any breakage without expanding scope to failure APIs or trace UI**
- [x] **Step 3: Summarize risks and handoff items for phase 3 (`D1 + D2`)**
