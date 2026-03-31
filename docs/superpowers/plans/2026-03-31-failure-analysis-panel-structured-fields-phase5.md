# Failure Analysis Panel Structured Fields Phase 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing registration failure analysis panel to the new structured failure fields so the frontend can filter and display `failure_stage`, `step_key`, and `retryable`.

**Architecture:** Keep the current panel skeleton and reuse the existing JS state machine. This phase only extends the existing template hooks, query builder, summary rendering, row rendering, and JS harness scenarios to cover the new backend fields added in phase 4.

**Tech Stack:** HTML templates, vanilla JS, CSS, Python pytest, JS harness.

---

## File Structure Map

### Modified files
- Modify: `templates/index.html` — add structured filter inputs and summary slots.
- Modify: `static/js/app.js` — include structured filters in query building and render structured summary/row fields.
- Modify: `static/css/registration_workbench.css` — keep the expanded panel readable after adding new filter and table cells.
- Modify: `tests_runtime/app_js_harness.py` — extend mocked API payloads and scenarios for the structured fields.

### Tests
- Modify: `tests/test_registration_failure_panel_assets.py`

---

### Task 1: Lock the new panel contract with failing tests

**Files:**
- Modify: `tests/test_registration_failure_panel_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

- [x] **Step 1: Add failing asset tests for new structured filter hooks / summary hooks / query params / row rendering**
- [x] **Step 2: Run focused asset tests and verify failure before implementation**

### Task 2: Extend the existing panel implementation

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `static/css/registration_workbench.css`
- Modify: `tests_runtime/app_js_harness.py`

- [x] **Step 1: Add template hooks for `failure_stage`, `step_key`, `retryable` filters and structured summary lists**
- [x] **Step 2: Extend JS state/query/render logic to consume and render the structured fields**
- [x] **Step 3: Adjust table/dialog/CSS so the denser structured data remains readable**
- [x] **Step 4: Run focused asset tests and verify pass**

### Task 3: Focused regression pass

**Files:**
- Modify: `tests/test_registration_failure_panel_assets.py`

- [x] **Step 1: Run focused panel asset regression**
- [x] **Step 2: Fix any front-end wiring breakage without expanding scope to unrelated workbench features**
- [x] **Step 3: Summarize remaining panel follow-up items if any**
