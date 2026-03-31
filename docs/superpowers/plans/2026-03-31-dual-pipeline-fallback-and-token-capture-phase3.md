# Dual Pipeline Fallback and Token Capture Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared auth entry fallback and registration-time token capture so current/codexgen pipelines and the legacy `RegistrationEngine.run()` path can avoid brittle single-entry auth bootstraps and unnecessary relogin loops.

**Architecture:** Move auth entry selection and registration-time token capture into shared helpers on `RegistrationEngine`. Then adapt both `current_pipeline` and `codexgen_pipeline` token-acquisition steps to prefer shared capture results, while keeping relogin as the fallback path and preserving codexgen-only create-account behavior.

**Tech Stack:** FastAPI, SQLAlchemy ORM, curl_cffi sessions, existing pipeline framework, pytest.

---

## File Structure Map

### Modified files
- Modify: `src/config/settings.py` — add minimal auth-entry settings.
- Modify: `src/core/register.py` — add shared auth fallback helpers, registration token capture helpers, and token-source propagation for both legacy and pipeline step adapters.
- Modify: `src/core/pipeline/steps/codexgen.py` — reuse shared auth/token helpers instead of bespoke relogin-only behavior.
- Modify: `src/core/registration_job.py` — keep pipeline result payloads exposing unified `token_source` metadata.

### Tests
- Modify: `tests/test_registration_engine.py`
- Modify: `tests/test_current_pipeline.py`
- Modify: `tests/test_codexgen_pipeline.py`
- Modify: `tests/test_registration_job.py`

---

### Task 1: Add shared auth entry fallback to `RegistrationEngine`

**Files:**
- Modify: `src/config/settings.py`
- Modify: `src/core/register.py`
- Test: `tests/test_registration_engine.py`

- [x] **Step 1: Write failing engine tests for auth entry fallback metadata and fallback hit behavior**
- [x] **Step 2: Run focused engine tests and verify failure before implementation**
- [x] **Step 3: Add entry-mode settings and shared auth fallback helpers to `RegistrationEngine`**
- [x] **Step 4: Ensure `_prepare_authorize_flow()` records `auth_entry_mode_used` and fallback hits**
- [x] **Step 5: Run focused engine tests and verify pass**

### Task 2: Reuse shared auth fallback in current/codexgen pipeline adapters

**Files:**
- Modify: `src/core/register.py`
- Modify: `src/core/pipeline/steps/codexgen.py`
- Test: `tests/test_current_pipeline.py`
- Test: `tests/test_codexgen_pipeline.py`

- [x] **Step 1: Write failing pipeline tests for `auth_entry_mode_used` metadata in both pipelines**
- [x] **Step 2: Run focused pipeline tests and verify failure before implementation**
- [x] **Step 3: Route current/codexgen prepare-authorize steps through the shared helper outputs**
- [x] **Step 4: Run focused pipeline tests and verify pass**

### Task 3: Add registration-time token capture before relogin fallback

**Files:**
- Modify: `src/core/register.py`
- Modify: `src/core/pipeline/steps/codexgen.py`
- Modify: `src/core/registration_job.py`
- Test: `tests/test_registration_engine.py`
- Test: `tests/test_current_pipeline.py`
- Test: `tests/test_codexgen_pipeline.py`
- Test: `tests/test_registration_job.py`

- [x] **Step 1: Write failing tests for shared token capture and unified `token_source` propagation**
- [x] **Step 2: Run focused capture tests and verify failure before implementation**
- [x] **Step 3: Add `_try_capture_registration_tokens()` and shared token-application helpers to `RegistrationEngine`**
- [x] **Step 4: Update current/codexgen token-acquisition steps to prefer capture over relogin and expose `token_source`**
- [x] **Step 5: Update legacy `run()` to short-circuit relogin when capture succeeds**
- [x] **Step 6: Run focused tests and verify pass**

### Task 4: Focused regression pass for phase 3

**Files:**
- Modify: `tests/test_registration_engine.py`
- Modify: `tests/test_current_pipeline.py`
- Modify: `tests/test_codexgen_pipeline.py`
- Modify: `tests/test_registration_job.py`

- [x] **Step 1: Run the combined phase-3 regression suite**
- [x] **Step 2: Fix any breakage without expanding scope to trace UI or failure APIs**
- [x] **Step 3: Summarize risks and handoff items for phase 4 (`E1 + C2`)**
