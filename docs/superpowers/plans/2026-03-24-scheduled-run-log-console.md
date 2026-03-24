# Scheduled Run Log Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split scheduled-run detail and log views, then upgrade the log view into a professional real-time console with millisecond timestamps, level parsing, enter-to-search filtering, and live re-filtering as new log chunks arrive.

**Architecture:** Keep the existing scheduled-run APIs and text log storage model. Add a dedicated detail modal plus a dedicated log-console modal in the scheduled-tasks page, then teach `static/js/scheduled_tasks.js` to maintain a parsed log-line state machine for rendering, filtering, copying, wrapping, and live updates. Standardize newly appended run-log lines in `src/scheduler/run_logger.py` as timestamped text entries (`YYYY-MM-DD HH:mm:ss.SSS [LEVEL] message`) and apply `INFO/WARN/ERROR` levels at scheduled-run write sites.

**Tech Stack:** FastAPI, SQLAlchemy ORM, vanilla JS, CSS, pytest, Node-based asset behavior tests

---

## Spec Reference

- `docs/superpowers/specs/2026-03-24-scheduled-run-log-console-design.md`

## File Map

- `templates/scheduled_tasks.html` — split the old combined run modal into a dedicated detail modal and a dedicated log-console modal with toolbar hooks.
- `static/js/scheduled_tasks.js` — separate detail/log open flows, add console state, parse/filter/render log lines, and support enter-to-search/live re-filtering.
- `static/css/style.css` — add professional console chrome, toolbar layout, timestamp/level colors, and wrap/no-wrap states.
- `src/scheduler/run_logger.py` — centralize timestamped `[LEVEL]` line formatting for scheduled-run logs.
- `src/scheduler/runners/cleanup.py` — tag failure/progress log sites with explicit levels where helpful.
- `src/scheduler/runners/refill.py` — tag failure/progress log sites with explicit levels where helpful.
- `src/scheduler/runners/refresh.py` — tag failure/progress log sites with explicit levels where helpful.
- `tests/test_scheduled_tasks_page_assets.py` — template/CSS hooks plus Node-based behavior tests for the split modals and console controls.
- `tests/test_scheduler_engine.py` — run-logger formatting coverage for timestamp + level behavior.

> Review note: this session cannot use reviewer subagents under current tool policy, so plan review is done by local self-review after writing.

### Task 1: Add failing template/CSS tests for separate detail and log modals

**Files:**
- Modify: `templates/scheduled_tasks.html`
- Modify: `static/css/style.css`
- Test: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: Add failing asset assertions for split modal hooks**

In `tests/test_scheduled_tasks_page_assets.py`, add assertions for:

```python
assert 'id="run-detail-modal"' in template
assert 'id="run-detail-modal-body"' in template
assert 'id="run-log-search-input"' in template
assert 'id="run-log-level-filter"' in template
assert 'id="run-log-copy-btn"' in template
assert 'id="run-log-clear-btn"' in template
assert 'id="run-log-wrap-input"' in template
```

Also add stylesheet checks for new console classes:

```python
assert ".scheduled-run-console-shell" in stylesheet
assert ".scheduled-run-console-toolbar" in stylesheet
assert ".scheduled-run-log-line" in stylesheet
assert ".scheduled-run-log-level-error" in stylesheet
```

- [ ] **Step 2: Run the focused asset tests to verify they fail**

Run:

```bash
pytest tests/test_scheduled_tasks_page_assets.py -q
```

Expected: FAIL because the new modal and console hooks/classes do not exist yet.

- [ ] **Step 3: Implement the minimal modal and CSS scaffold**

In `templates/scheduled_tasks.html`:
- add a dedicated `run-detail-modal`
- keep `run-log-modal` but replace the old generic body with:
  - status bar
  - toolbar
  - console shell

Suggested markup skeleton:

```html
<div id="run-detail-modal" class="modal">...</div>
<div id="run-log-modal" class="modal">
  <input id="run-log-search-input">
  <select id="run-log-level-filter"></select>
  <button id="run-log-copy-btn"></button>
  <button id="run-log-clear-btn"></button>
  <input type="checkbox" id="run-log-wrap-input">
  <div id="run-log-console" class="scheduled-run-console-shell"></div>
</div>
```

In `static/css/style.css`, add console-specific styles:
- dark shell
- toolbar layout
- colored level badges
- wrap/no-wrap display classes

- [ ] **Step 4: Re-run the focused asset tests and make them pass**

Run:

```bash
pytest tests/test_scheduled_tasks_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the modal/CSS scaffold**

```bash
git add templates/scheduled_tasks.html static/css/style.css tests/test_scheduled_tasks_page_assets.py
git commit -m "feat: split scheduled run detail and log modals"
```

### Task 2: Add failing JS behavior tests for the log console and implement the split flows

**Files:**
- Modify: `static/js/scheduled_tasks.js`
- Test: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: Add failing Node-based behavior tests**

Extend `tests/test_scheduled_tasks_page_assets.py` with focused scenarios for:

1. `openScheduledRunDetail(123)` renders detail-only content and **does not** render `scheduled-run-log-panel`
2. `openScheduledRunLog(123)` renders the console shell and loads the first log chunk
3. pressing Enter in `run-log-search-input` applies the current search filter
4. changing `run-log-level-filter` re-renders matching lines only
5. after a second log chunk arrives, current search + level filters are automatically re-applied

Suggested assertions:

```python
if (detailBodyHtml.includes('scheduled-run-log-panel')) throw new Error('detail modal should not include logs');
if (!logBodyHtml.includes('scheduled-run-console-shell')) throw new Error('missing console shell');
if (!visibleText.includes('[ERROR]')) throw new Error('expected filtered error line');
```

- [ ] **Step 2: Run the focused asset tests to verify they fail**

Run:

```bash
pytest tests/test_scheduled_tasks_page_assets.py -q
```

Expected: FAIL because the current JS still uses one combined modal and lacks console state/filter behavior.

- [ ] **Step 3: Implement the minimal JS split and console state**

In `static/js/scheduled_tasks.js`:
- add `runDetailModal` / `runDetailModalBody` elements
- keep dedicated log-modal elements for console controls
- make `openScheduledRunDetail()` fetch and render metadata only
- make `openScheduledRunLog()` fetch detail + log chunks and start polling

Add a small console state model, e.g.:

```javascript
let scheduledRunConsoleState = {
  rawLines: [],
  visibleLines: [],
  searchTerm: '',
  levelFilter: '',
  wrap: false,
  clearedView: false,
};
```

Implement helpers:

```javascript
function parseScheduledRunLogLines(text) { ... }
function applyScheduledRunLogFilters() { ... }
function renderScheduledRunConsole() { ... }
function handleScheduledRunLogSearchKeydown(event) { ... }
```

Control rules:
- search applies on Enter only
- level filter applies immediately
- clear button clears only `visibleLines`/view state, not `rawLines`
- new chunks append to `rawLines`, then call `applyScheduledRunLogFilters()` again

- [ ] **Step 4: Re-run the focused asset tests and make them pass**

Run:

```bash
pytest tests/test_scheduled_tasks_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the JS console behavior**

```bash
git add static/js/scheduled_tasks.js tests/test_scheduled_tasks_page_assets.py
git commit -m "feat: add scheduled run log console behavior"
```

### Task 3: Add failing run-logger formatting tests and implement timestamped leveled lines

**Files:**
- Modify: `src/scheduler/run_logger.py`
- Test: `tests/test_scheduler_engine.py`

- [ ] **Step 1: Add failing run-logger tests**

In `tests/test_scheduler_engine.py`, extend `test_run_logger_append_log_uses_logged_at_for_last_log_timestamp` coverage or add two new tests:

```python
logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
assert run_logger.append_run_log(run_id, "hello", logged_at=logged_at) is True
assert persisted.logs == "2025-01-02 03:04:05.123 [INFO] hello"
```

And:

```python
assert run_logger.append_run_log(run_id, "boom", level="ERROR", logged_at=logged_at) is True
assert "[ERROR] boom" in persisted.logs
```

- [ ] **Step 2: Run the focused engine/logger tests to verify they fail**

Run:

```bash
pytest tests/test_scheduler_engine.py -q
```

Expected: FAIL because `append_run_log()` currently stores raw message text and has no `level` parameter.

- [ ] **Step 3: Implement line formatting in `src/scheduler/run_logger.py`**

Add a formatter helper:

```python
def _format_run_log_line(message: str, *, level: str, logged_at: datetime) -> str:
    stamp = logged_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return f"{stamp} [{level}] {message}"
```

Then update:

```python
def append_run_log(run_id: int, message: str, *, level: str = "INFO", logged_at: datetime | None = None) -> bool:
    actual_logged_at = logged_at or datetime.utcnow()
    line = _format_run_log_line(message, level=level, logged_at=actual_logged_at)
    ...
```

Keep `crud.append_scheduled_run_log(...)` unchanged so stored data remains text.

- [ ] **Step 4: Re-run the focused engine/logger tests and make them pass**

Run:

```bash
pytest tests/test_scheduler_engine.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the run-logger formatting work**

```bash
git add src/scheduler/run_logger.py tests/test_scheduler_engine.py
git commit -m "feat: timestamp scheduled run log lines"
```

### Task 4: Apply levels in runner log sites and verify the end-to-end scheduled-run suite

**Files:**
- Modify: `src/scheduler/runners/cleanup.py`
- Modify: `src/scheduler/runners/refill.py`
- Modify: `src/scheduler/runners/refresh.py`
- Test: `tests/test_scheduler_cleanup_runner.py`
- Test: `tests/test_scheduler_service.py`
- Test: `tests/test_scheduled_tasks_routes.py`
- Test: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: Add one failing runner-level assertion for explicit error formatting**

In `tests/test_scheduler_cleanup_runner.py`, update the failure-path assertion so it expects the stored log to contain the leveled prefix on the failure line, for example:

```python
assert "[ERROR] cleanup runner failed: probe failed" in (persisted_run.logs or "")
```

- [ ] **Step 2: Run the scheduled-run focused suite to verify the new assertion fails**

Run:

```bash
pytest tests/test_scheduler_cleanup_runner.py tests/test_scheduled_tasks_routes.py tests/test_scheduled_tasks_page_assets.py tests/test_scheduler_service.py -q
```

Expected: FAIL because runner write sites still rely on default `INFO` everywhere.

- [ ] **Step 3: Apply explicit `WARN/ERROR` levels in runner log sites**

Adjust runner calls such as:

```python
append_run_log(run_id, f"cleanup runner failed: {exc}", level="ERROR")
append_run_log(run_id, "registration returned no account_id", level="WARN")
append_run_log(run_id, f"refresh runner failed: {exc}", level="ERROR")
```

Guideline:
- normal progress/start/complete → `INFO`
- recoverable anomalies/skips → `WARN`
- failure/exception paths → `ERROR`

- [ ] **Step 4: Run the full focused verification suite**

Run:

```bash
pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_scheduled_tasks_routes.py \
  tests/test_scheduler_cleanup_runner.py \
  tests/test_scheduler_service.py \
  tests/test_scheduler_engine.py -q
```

Expected: PASS.

- [ ] **Step 5: Record final diff context**

Run:

```bash
git status --short
git diff -- templates/scheduled_tasks.html static/js/scheduled_tasks.js static/css/style.css src/scheduler/run_logger.py src/scheduler/runners/cleanup.py src/scheduler/runners/refill.py src/scheduler/runners/refresh.py tests/test_scheduled_tasks_page_assets.py tests/test_scheduler_engine.py tests/test_scheduler_cleanup_runner.py tests/test_scheduled_tasks_routes.py tests/test_scheduler_service.py
```

Expected: Only planned files differ.

- [ ] **Step 6: Commit the finished feature**

```bash
git add docs/superpowers/plans/2026-03-24-scheduled-run-log-console.md templates/scheduled_tasks.html static/js/scheduled_tasks.js static/css/style.css src/scheduler/run_logger.py src/scheduler/runners/cleanup.py src/scheduler/runners/refill.py src/scheduler/runners/refresh.py tests/test_scheduled_tasks_page_assets.py tests/test_scheduler_engine.py tests/test_scheduler_cleanup_runner.py tests/test_scheduled_tasks_routes.py tests/test_scheduler_service.py
git commit -m "feat: add scheduled run log console"
```
