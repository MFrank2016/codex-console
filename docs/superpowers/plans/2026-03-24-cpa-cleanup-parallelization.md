# CPA Cleanup Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up `cpa_cleanup` by adding configurable concurrent probe/delete execution and batch local expiration updates.

**Architecture:** Keep the change scoped to the existing scheduled cleanup path. Extend the cleanup task config schema with worker-count fields, move the CPA client fallback probe/delete loops to bounded `ThreadPoolExecutor` execution, and replace per-account DB commits with a bulk `UPDATE` helper. Preserve existing logging, stop semantics, and summary fields.

**Tech Stack:** Python 3.13, SQLAlchemy ORM, curl_cffi, vanilla JS config editor, pytest

---

## File Map

- `src/scheduler/cpa_client.py` — add bounded concurrent fallback probe/delete helpers and worker-count defaults.
- `src/scheduler/runners/cleanup.py` — resolve/forward worker config, switch local expiration to bulk updates, keep staged logs/stop checks.
- `src/database/crud.py` — add bulk expire helper scoped by `email + primary_cpa_service_id`.
- `src/scheduler/service.py` — validate `probe_workers` / `delete_workers` as optional non-negative integers.
- `static/js/scheduled_tasks.js` — expose new cleanup config fields with safe defaults.
- `tests/test_scheduler_cpa_client.py` — add failing tests for worker propagation and concurrent completion behavior.
- `tests/test_scheduler_cleanup_runner.py` — add failing tests for worker propagation and bulk expiration use.
- `tests/test_scheduler_service.py` — add validation coverage for new config keys.
- `tests/test_scheduled_tasks_page_assets.py` — add asset assertions for the new config keys.

### Task 1: Extend cleanup config schema and validation

**Files:**
- Modify: `static/js/scheduled_tasks.js`
- Modify: `src/scheduler/service.py`
- Test: `tests/test_scheduler_service.py`
- Test: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: Write the failing tests**

Add assertions that:

```python
with pytest.raises(ValueError, match="probe_workers"):
    validate_plan_payload(..., config={"probe_workers": -1})

with pytest.raises(ValueError, match="delete_workers"):
    validate_plan_payload(..., config={"delete_workers": -1})
```

And asset assertions that the cleanup config schema now includes:

```python
assert "probe_workers" in script
assert "delete_workers" in script
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py -q
```

Expected: FAIL because the new config keys are not yet validated/rendered.

- [ ] **Step 3: Implement the minimal config support**

In `src/scheduler/service.py`, extend cleanup validation:

```python
if task_type == "cpa_cleanup":
    _validate_optional_non_negative_int(config, "max_cleanup_count")
    _validate_optional_non_negative_int(config, "max_probe_count")
    _validate_optional_non_negative_int(config, "probe_workers")
    _validate_optional_non_negative_int(config, "delete_workers")
```

In `static/js/scheduled_tasks.js`, add cleanup defaults:

```javascript
{
    key: 'probe_workers',
    key_description: '401 探测并发数',
    value_type: 'number',
    default_value: 10,
    value_description: '0 或空时回退为默认并发',
    readonly_key: true,
},
{
    key: 'delete_workers',
    key_description: '远端删除并发数',
    value_type: 'number',
    default_value: 20,
    value_description: '0 或空时回退为默认并发',
    readonly_key: true,
},
```

- [ ] **Step 4: Re-run the focused tests and make them pass**

Run:

```bash
pytest tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the config support work**

```bash
git add src/scheduler/service.py static/js/scheduled_tasks.js tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py
git commit -m "feat: add cleanup worker config"
```

### Task 2: Add concurrent CPA probe/delete support

**Files:**
- Modify: `src/scheduler/cpa_client.py`
- Test: `tests/test_scheduler_cpa_client.py`

- [ ] **Step 1: Write the failing tests**

Add tests proving the new worker parameter is accepted and work completes out of order safely:

```python
result = cpa_client.probe_invalid_accounts(_service(), workers=4)
assert sorted(item["email"] for item in result) == ["invalid1@example.com", "invalid2@example.com"]

result = cpa_client.delete_invalid_accounts(_service(), names, workers=4)
assert result == {"deleted": 3, "failed": 1}
```

Use a `threading.Event`/`Barrier` or controlled sleeps in the fake transport so the test would deadlock/fail if the code stayed strictly serial.

- [ ] **Step 2: Run the focused client tests to verify they fail**

Run:

```bash
pytest tests/test_scheduler_cpa_client.py -q
```

Expected: FAIL because `workers` is unsupported and execution is still serial.

- [ ] **Step 3: Implement bounded concurrent execution in `cpa_client.py`**

Add module defaults and wire worker arguments through the public helpers:

```python
_DEFAULT_PROBE_WORKERS = 10
_DEFAULT_DELETE_WORKERS = 20
```

Implementation rules:
- Normalize worker counts so `0/None` fall back to defaults.
- Keep `max_probe_count` / `limit` semantics unchanged.
- Use `ThreadPoolExecutor(max_workers=...)` + `as_completed(...)`.
- Protect shared counters/lists where ordering no longer matches input order.
- Preserve progress callback messages and `{deleted, failed}` return shape.

- [ ] **Step 4: Re-run the client tests and make them pass**

Run:

```bash
pytest tests/test_scheduler_cpa_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the CPA client work**

```bash
git add src/scheduler/cpa_client.py tests/test_scheduler_cpa_client.py
git commit -m "feat: parallelize cleanup cpa client"
```

### Task 3: Batch local expiration updates inside cleanup runner

**Files:**
- Modify: `src/database/crud.py`
- Modify: `src/scheduler/runners/cleanup.py`
- Test: `tests/test_scheduler_cleanup_runner.py`

- [ ] **Step 1: Write the failing runner tests**

Add coverage that:

```python
captured["probe_workers"] == 7
captured["delete_workers"] == 9
summary["local_marked_expired"] == 250
```

And add a CRUD/runner assertion that the cleanup flow uses a bulk expiration helper rather than calling the single-account helper once per email.

- [ ] **Step 2: Run the focused runner tests to verify they fail**

Run:

```bash
pytest tests/test_scheduler_cleanup_runner.py -q
```

Expected: FAIL because the runner does not yet resolve/forward worker config or use bulk DB updates.

- [ ] **Step 3: Implement the minimal bulk-expire path**

In `src/database/crud.py`, add:

```python
def mark_accounts_expired_by_emails_and_cpa(db, *, emails, cpa_service_id, reason):
    cleaned = sorted({email for email in emails if email})
    if not cleaned:
        return 0
    now = datetime.utcnow()
    updated = (
        db.query(Account)
        .filter(Account.email.in_(cleaned))
        .filter(Account.primary_cpa_service_id == cpa_service_id)
        .update({...}, synchronize_session=False)
    )
    db.commit()
    return int(updated)
```

In `src/scheduler/runners/cleanup.py`:
- resolve `probe_workers` / `delete_workers` with default fallback
- pass them to `probe_invalid_accounts()` / `delete_invalid_accounts()`
- batch emails in `_PROGRESS_EVERY` chunks and call the new bulk CRUD helper once per chunk
- keep stop checks and staged progress logs intact

- [ ] **Step 4: Re-run the runner tests and make them pass**

Run:

```bash
pytest tests/test_scheduler_cleanup_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the cleanup runner work**

```bash
git add src/database/crud.py src/scheduler/runners/cleanup.py tests/test_scheduler_cleanup_runner.py
git commit -m "feat: batch cleanup expiration updates"
```

### Task 4: Final verification

**Files:**
- Modify: none
- Test: `tests/test_scheduler_cpa_client.py`
- Test: `tests/test_scheduler_cleanup_runner.py`
- Test: `tests/test_scheduler_service.py`
- Test: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: Run the full focused verification suite**

Run:

```bash
pytest tests/test_scheduler_cpa_client.py tests/test_scheduler_cleanup_runner.py tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 2: Record final diff context**

Run:

```bash
git status --short
git diff -- src/scheduler/cpa_client.py src/scheduler/runners/cleanup.py src/database/crud.py src/scheduler/service.py static/js/scheduled_tasks.js tests/test_scheduler_cpa_client.py tests/test_scheduler_cleanup_runner.py tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py
```

Expected: Only the planned files differ.

- [ ] **Step 3: Commit the finished optimization**

```bash
git add docs/superpowers/specs/2026-03-24-cpa-cleanup-parallelization-design.md docs/superpowers/plans/2026-03-24-cpa-cleanup-parallelization.md src/scheduler/cpa_client.py src/scheduler/runners/cleanup.py src/database/crud.py src/scheduler/service.py static/js/scheduled_tasks.js tests/test_scheduler_cpa_client.py tests/test_scheduler_cleanup_runner.py tests/test_scheduler_service.py tests/test_scheduled_tasks_page_assets.py
git commit -m "feat: speed up scheduled cpa cleanup"
```
