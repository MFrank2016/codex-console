# Dual Pipeline Unified Runner Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route both `current_pipeline` and `codexgen_pipeline` through the shared pipeline runner, then add shared step-local retry support to both pipelines.

**Architecture:** Keep `current_pipeline` and `codexgen_pipeline` as separate definitions, but make `run_registration_job()` dispatch both through `_run_pipeline_registration()` and `PipelineRunner`. After the execution path is unified, extend `StepDefinition` and `PipelineRunner` with transient-aware per-step retry metadata so both pipelines gain the same recovery semantics.

**Tech Stack:** FastAPI, SQLAlchemy ORM, existing registration pipeline framework, pytest.

---

## File Structure Map

### Modified files
- Modify: `src/core/registration_job.py` — unify runtime construction and dispatch both pipelines through `PipelineRunner`.
- Modify: `src/core/pipeline/steps/current.py` — add a `build_current_runtime()` helper and attach retry policy to current pipeline step definitions.
- Modify: `src/core/pipeline/definitions.py` — extend `StepDefinition` with retry metadata.
- Modify: `src/core/pipeline/runner.py` — implement per-step transient retry and persist retry metadata.
- Modify: `src/core/pipeline/steps/codexgen.py` — attach retry policy to codexgen step definitions.

### Tests
- Modify: `tests/test_registration_job.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_current_pipeline.py`
- Modify: `tests/test_codexgen_pipeline.py`

---

### Task 1: Unify `current_pipeline` and `codexgen_pipeline` execution entrypoints

**Files:**
- Modify: `src/core/registration_job.py`
- Modify: `src/core/pipeline/steps/current.py`
- Test: `tests/test_registration_job.py`
- Test: `tests/test_current_pipeline.py`
- Test: `tests/test_codexgen_pipeline.py`

- [x] **Step 1: Write failing tests proving `current_pipeline` goes through `PipelineRunner`**
- [x] **Step 2: Run focused tests and verify failure before implementation**
- [x] **Step 3: Add `build_current_runtime()` and shared pipeline runtime factory**
- [x] **Step 4: Route both pipeline keys through `_run_pipeline_registration()`**
- [x] **Step 5: Run focused tests and verify both pipelines pass through unified runner**

### Task 2: Add transient-aware step-local retry to the shared pipeline runner

**Files:**
- Modify: `src/core/pipeline/definitions.py`
- Modify: `src/core/pipeline/runner.py`
- Modify: `src/core/pipeline/steps/current.py`
- Modify: `src/core/pipeline/steps/codexgen.py`
- Test: `tests/test_pipeline_runner.py`
- Test: `tests/test_current_pipeline.py`
- Test: `tests/test_codexgen_pipeline.py`

- [x] **Step 1: Write failing tests for retryable transient step failures**
- [x] **Step 2: Run focused retry tests and verify expected failure**
- [x] **Step 3: Extend `StepDefinition` with retry metadata and teach `PipelineRunner` to retry transient failures**
- [x] **Step 4: Configure retry policies on shared critical steps for both pipelines**
- [x] **Step 5: Run focused tests and verify retry metadata + behavior**

### Task 3: Focused regression pass for phase 1

**Files:**
- Modify: `tests/test_registration_job.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_current_pipeline.py`
- Modify: `tests/test_codexgen_pipeline.py`

- [x] **Step 1: Run the combined phase-1 regression suite**
- [x] **Step 2: Fix any breakage without expanding scope to failure APIs or token capture**
- [x] **Step 3: Summarize remaining risks for phase 2 (`A + C1`)**
