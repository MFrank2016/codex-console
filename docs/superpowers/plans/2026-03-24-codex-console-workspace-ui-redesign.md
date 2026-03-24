# codex-console Workspace UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild codex-console into a unified warm-toned workspace UI with a collapsible workflow sidebar, a new dashboard homepage, and a dedicated registration workbench while preserving the current FastAPI/Jinja2/vanilla-JS business flows.

**Architecture:** Add a shared workspace shell (Jinja base template + sidebar include + persisted collapse script + shared CSS tokens), then introduce a dashboard route/page and move registration into `/registration-workbench`, and finally migrate the remaining pages onto the same shell in small, test-backed slices without rewriting the underlying APIs.

**Tech Stack:** FastAPI, Jinja2 templates, vanilla JavaScript, shared CSS in `static/css/style.css`, current page-level scripts in `static/js/*.js`, pytest, TestClient, existing Node-based JS harnesses.

---

## Spec Reference

- `docs/superpowers/specs/2026-03-24-codex-console-workspace-ui-redesign-design.md`

## Review Note

- Current tool policy for this session does not allow reviewer subagents without explicit user delegation, so this plan should be reviewed locally after writing.

## File Map

### Create

- `src/web/page_shell.py` — central workspace navigation metadata and a helper for consistent page-shell template context.
- `src/web/routes/dashboard.py` — lightweight dashboard summary API that aggregates existing registration/account/scheduler signals for the new homepage.
- `templates/_workspace_base.html` — shared HTML document/base layout for the workspace shell.
- `templates/_workspace_sidebar.html` — grouped collapsible sidebar include.
- `templates/dashboard.html` — new `/` dashboard page.
- `static/js/workspace.js` — sidebar expand/collapse persistence and shared workspace UI helpers.
- `static/js/dashboard.js` — dashboard data loading and card/panel rendering.
- `tests/test_workspace_shell_assets.py` — shared shell/template/script/CSS assertions.
- `tests/test_dashboard_page_assets.py` — dashboard route, auth, asset, and summary-script coverage.

### Modify

- `src/web/app.py` — route remap (`/` → dashboard, `/registration-workbench` → registration page), shared page-shell context, and new dashboard template rendering.
- `src/web/routes/__init__.py` — register the dashboard summary API router.
- `templates/index.html` — convert the existing registration page into the registration workbench inside the new shell.
- `templates/accounts.html` — migrate to workspace shell and new page-head/metric/table layout.
- `templates/email_services.html` — migrate to workspace shell and configuration-workbench layout.
- `templates/login.html` — restyle into the new warm-toned visual system.
- `templates/payment.html` — migrate to workspace shell and compact action-panel layout.
- `templates/registration_experiments.html` — migrate to workspace shell and analysis layout.
- `templates/registration_batch_stats.html` — migrate to workspace shell and analysis layout.
- `templates/scheduled_tasks.html` — migrate to workspace shell while preserving existing management hooks.
- `templates/settings.html` — migrate to workspace shell and configuration layout.
- `static/css/style.css` — add workspace design tokens, shell, cards, page-head, sidebar, dashboard, and login selectors; retire obsolete top-nav-only styling where safe.
- `static/js/app.js` — adapt registration-page initialization to the workbench layout without changing existing business endpoints.
- `tests/test_registration_page_assets.py` — update route expectations and add workspace-shell assertions for the registration workbench.
- `tests/test_registration_experiment_page_assets.py` — assert the new shell hooks remain present.
- `tests/test_registration_batch_stats_page_assets.py` — assert the new shell hooks remain present.
- `tests/test_scheduled_tasks_page_assets.py` — assert shell hooks remain present after layout migration.
- `tests/test_static_asset_versioning.py` — cover new shared assets (`workspace.js`, `dashboard.js`) in rendered pages.

---

### Task 1: Add failing route and shell tests for the new workspace entrypoints

**Files:**
- Create: `tests/test_workspace_shell_assets.py`
- Create: `tests/test_dashboard_page_assets.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `src/web/app.py`

- [ ] **Step 1: Write failing route/auth tests for `/` and `/registration-workbench`**

In `tests/test_dashboard_page_assets.py`, add TestClient coverage that expects:

```python
app = create_app()
with TestClient(app) as client:
    unauthenticated = client.get("/", follow_redirects=False)
    assert unauthenticated.status_code == 302
    assert unauthenticated.headers["location"] == "/login?next=/"

    password = get_settings().webui_access_password.get_secret_value()
    client.post("/login", data={"password": password, "next": "/"}, follow_redirects=False)

    response = client.get("/")
    assert response.status_code == 200
    assert 'data-page-key="dashboard"' in response.text
    assert "/static/js/dashboard.js?v=" in response.text
```

Also add a second test that `/registration-workbench` requires auth and renders the registration hooks (`id="registration-form"`, `id="task-step-waterfall"`).

- [ ] **Step 2: Write failing shared-shell asset assertions**

In `tests/test_workspace_shell_assets.py`, assert the shared shell assets do not exist yet:

```python
stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
assert ".workspace-shell" in stylesheet
assert ".workspace-sidebar" in stylesheet
assert ".workspace-rail" in stylesheet
assert ".page-head" in stylesheet

script = Path("static/js/workspace.js").read_text(encoding="utf-8")
assert "WORKSPACE_SIDEBAR_STORAGE_KEY" in script
assert "toggleWorkspaceSidebar" in script
```

In `tests/test_registration_page_assets.py`, add route-source assertions:

```python
app_source = Path("src/web/app.py").read_text(encoding="utf-8")
assert '@app.get("/registration-workbench", response_class=HTMLResponse)' in app_source
assert 'templates.TemplateResponse("index.html"' in app_source
```

- [ ] **Step 3: Run the focused tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workspace_shell_assets.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: FAIL because the workspace shell assets, dashboard route, and registration workbench route do not exist yet.

- [ ] **Step 4: Add the minimal route stubs in `src/web/app.py`**

Implement the smallest route remap that makes the new tests meaningful:

```python
@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not _is_authenticated(request):
        return _redirect_to_login(request)
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/registration-workbench", response_class=HTMLResponse)
async def registration_workbench_page(request: Request):
    if not _is_authenticated(request):
        return _redirect_to_login(request)
    return templates.TemplateResponse("index.html", {"request": request})
```

Do not try to finish the dashboard implementation yet; this step is only to establish route intent.

- [ ] **Step 5: Re-run the focused tests and confirm they still fail on missing assets/templates**

Run:

```bash
uv run pytest tests/test_workspace_shell_assets.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: FAIL, but now on missing `dashboard.html`, `workspace.js`, and shell selectors instead of missing routes.

- [ ] **Step 6: Commit the failing-test baseline plus route intent**

```bash
git add src/web/app.py tests/test_workspace_shell_assets.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py
git commit -m "test: define workspace shell entrypoints"
```

---

### Task 2: Build the shared workspace shell foundation

**Files:**
- Create: `src/web/page_shell.py`
- Create: `templates/_workspace_base.html`
- Create: `templates/_workspace_sidebar.html`
- Create: `static/js/workspace.js`
- Modify: `src/web/app.py`
- Modify: `static/css/style.css`
- Test: `tests/test_workspace_shell_assets.py`

- [ ] **Step 1: Extend the shell tests so they describe the intended structure**

In `tests/test_workspace_shell_assets.py`, add assertions for:

```python
base_template = Path("templates/_workspace_base.html").read_text(encoding="utf-8")
assert '{% include "_workspace_sidebar.html" %}' in base_template
assert 'id="workspace-sidebar-toggle"' in base_template
assert 'data-page-key="{{ page_key }}"' in base_template
assert "/static/js/workspace.js?v={{ static_version }}" not in base_template
assert "/static/js/workspace.js?v=" in rendered_html
```

Also add a pure-source assertion that `src/web/page_shell.py` defines grouped navigation keys like `dashboard`, `registration_workbench`, `accounts`, `scheduled_tasks`, `registration_experiments`, and `settings`.

- [ ] **Step 2: Run the focused shell tests to verify they fail**

Run:

```bash
uv run pytest tests/test_workspace_shell_assets.py -q
```

Expected: FAIL because the base template, sidebar include, page-shell helper, and workspace script do not exist.

- [ ] **Step 3: Implement the page-shell helper and shared templates**

Create `src/web/page_shell.py` with a small helper API such as:

```python
WORKSPACE_NAV = [
    {"group": "总览", "items": [{"key": "dashboard", "label": "控制台总览", "href": "/"}]},
    {"group": "执行", "items": [...]},
    {"group": "复盘", "items": [...]},
    {"group": "配置", "items": [...]},
]


def build_page_shell(*, page_key: str, page_title: str, page_subtitle: str) -> dict[str, object]:
    return {
        "page_key": page_key,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "workspace_nav": WORKSPACE_NAV,
    }
```

Create `templates/_workspace_base.html` with the global HTML document, shell containers, shared stylesheet, shared `workspace.js`, and block slots for page-specific content/extra scripts. Create `templates/_workspace_sidebar.html` with the grouped navigation markup and a toggle button hook.

- [ ] **Step 4: Add sidebar persistence JS and workspace CSS tokens**

In `static/js/workspace.js`, implement:

```javascript
const WORKSPACE_SIDEBAR_STORAGE_KEY = 'codex-console.workspace.sidebar';

function applyWorkspaceSidebarState(isCollapsed) {
  document.body.classList.toggle('workspace-sidebar-collapsed', Boolean(isCollapsed));
}

function toggleWorkspaceSidebar() {
  const next = !document.body.classList.contains('workspace-sidebar-collapsed');
  localStorage.setItem(WORKSPACE_SIDEBAR_STORAGE_KEY, next ? 'collapsed' : 'expanded');
  applyWorkspaceSidebarState(next);
}
```

In `static/css/style.css`, add the foundational selectors:

```css
.workspace-shell { ... }
.workspace-rail { ... }
.workspace-sidebar { ... }
.workspace-sidebar-collapsed .workspace-sidebar { ... }
.page-head { ... }
.hero-metrics { ... }
.workspace-panel { ... }
```

- [ ] **Step 5: Wire `src/web/app.py` to pass shell context**

Refactor the page-rendering helpers so each route can merge:

```python
context = {"request": request, **build_page_shell(page_key="dashboard", page_title="控制台总览", page_subtitle="...")}
return templates.TemplateResponse("dashboard.html", context)
```

Do not migrate every page yet; just ensure the helper is available for upcoming tasks.

- [ ] **Step 6: Re-run the shell tests**

Run:

```bash
uv run pytest tests/test_workspace_shell_assets.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the shared shell foundation**

```bash
git add src/web/page_shell.py templates/_workspace_base.html templates/_workspace_sidebar.html static/js/workspace.js static/css/style.css src/web/app.py tests/test_workspace_shell_assets.py
git commit -m "feat: add shared workspace shell foundation"
```

---

### Task 3: Build the new dashboard homepage and its summary API

**Files:**
- Create: `src/web/routes/dashboard.py`
- Create: `templates/dashboard.html`
- Create: `static/js/dashboard.js`
- Modify: `src/web/routes/__init__.py`
- Modify: `src/web/app.py`
- Test: `tests/test_dashboard_page_assets.py`

- [ ] **Step 1: Add failing dashboard source and behavior tests**

In `tests/test_dashboard_page_assets.py`, add assertions that:

```python
template = Path("templates/dashboard.html").read_text(encoding="utf-8")
assert 'id="dashboard-hero"' in template
assert 'id="dashboard-task-health"' in template
assert 'id="dashboard-quick-links"' in template

script = Path("static/js/dashboard.js").read_text(encoding="utf-8")
assert "/dashboard/summary" in script
assert "renderDashboardHero" in script
assert "renderDashboardTaskHealth" in script
```

Add a TestClient/API test expecting `/api/dashboard/summary` to return keys like `registration`, `accounts`, and `scheduled`.

- [ ] **Step 2: Run the focused dashboard tests to verify they fail**

Run:

```bash
uv run pytest tests/test_dashboard_page_assets.py -q
```

Expected: FAIL because the dashboard template, script, and summary API do not exist yet.

- [ ] **Step 3: Implement a lightweight summary endpoint**

Create `src/web/routes/dashboard.py` with a small aggregator over existing data sources:

```python
@router.get("/dashboard/summary")
async def get_dashboard_summary():
    with get_db() as db:
        return {
            "registration": {...},
            "accounts": {...},
            "scheduled": {...},
            "quick_links": [...],
        }
```

Reuse existing CRUD/service queries where possible. Do not introduce a brand-new persistence model just for the dashboard.

- [ ] **Step 4: Create the dashboard template and renderer**

Make `templates/dashboard.html` extend `_workspace_base.html` and include:

```html
{% block page_content %}
<section class="hero-metrics" id="dashboard-hero"></section>
<section class="workspace-grid">
  <div class="workspace-panel" id="dashboard-task-health"></div>
  <div class="workspace-panel" id="dashboard-quick-links"></div>
</section>
{% endblock %}
```

In `static/js/dashboard.js`, fetch `/api/dashboard/summary`, then render hero cards, task health, quick links, and a compact recent-activity panel. Keep the first version simple and text/card based; avoid chart-library scope creep.

- [ ] **Step 5: Re-run the dashboard tests**

Run:

```bash
uv run pytest tests/test_dashboard_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the dashboard vertical slice**

```bash
git add src/web/routes/dashboard.py src/web/routes/__init__.py templates/dashboard.html static/js/dashboard.js src/web/app.py tests/test_dashboard_page_assets.py
git commit -m "feat: add workspace dashboard homepage"
```

---

### Task 4: Turn the current registration page into the registration workbench

**Files:**
- Modify: `src/web/app.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_registration_page_assets.py`

- [ ] **Step 1: Add failing registration-workbench route and shell assertions**

In `tests/test_registration_page_assets.py`, add assertions that authenticated HTML from `/registration-workbench` contains:

```python
assert 'data-page-key="registration_workbench"' in response.text
assert 'id="registration-form"' in response.text
assert 'id="task-step-waterfall"' in response.text
assert 'href="/registration-workbench"' in response.text
```

Add template assertions that the page now exposes dedicated workbench layout classes such as:

```python
template = Path("templates/index.html").read_text(encoding="utf-8")
assert "registration-workbench-layout" in template
assert "registration-workbench-main" in template
assert "registration-workbench-side" in template
```

- [ ] **Step 2: Run the focused registration tests to verify they fail**

Run:

```bash
uv run pytest tests/test_registration_page_assets.py -q
```

Expected: FAIL because the registration page still uses the legacy top-nav layout.

- [ ] **Step 3: Convert `templates/index.html` to extend the new shell**

Restructure the template so it keeps existing IDs/hooks but moves into the workbench skeleton:

```html
{% extends "_workspace_base.html" %}

{% block page_content %}
<div class="registration-workbench-layout">
  <section class="workspace-panel registration-workbench-side">
    <!-- existing registration form / controls -->
  </section>
  <section class="registration-workbench-main">
    <!-- task status, waterfall, logs -->
  </section>
  <aside class="workspace-panel registration-workbench-sidecar">
    <!-- recent accounts / quick tips -->
  </aside>
</div>
{% endblock %}
```

Preserve IDs used by `static/js/app.js` such as `registration-form`, `task-step-waterfall`, `console-log`, `recent-accounts-table`, and the batch progress hooks.

- [ ] **Step 4: Adapt `static/js/app.js` only where layout hooks changed**

Keep the business logic unchanged; only update selectors or defensive initialization for any moved nodes. A valid minimal pattern is:

```javascript
const root = document.body.dataset.pageKey;
if (root !== 'registration_workbench') {
  return;
}
```

Do not rename API endpoints, payload formats, or task-state logic in this task.

- [ ] **Step 5: Re-run the registration page tests and a focused JS harness check**

Run:

```bash
uv run pytest tests/test_registration_page_assets.py -q
```

Expected: PASS.

Run:

```bash
uv run pytest tests/test_registration_page_assets.py::test_app_js_renders_task_step_waterfall_html tests/test_registration_page_assets.py::test_app_js_single_task_flow_fetches_task_detail_and_renders_steps -q
```

Expected: PASS.

- [ ] **Step 6: Commit the registration workbench migration**

```bash
git add src/web/app.py templates/index.html static/js/app.js tests/test_registration_page_assets.py
git commit -m "feat: migrate registration page into workspace workbench"
```

---

### Task 5: Migrate the execution/configuration pages onto the shared shell

**Files:**
- Modify: `templates/accounts.html`
- Modify: `templates/scheduled_tasks.html`
- Modify: `templates/email_services.html`
- Modify: `templates/settings.html`
- Modify: `templates/payment.html`
- Modify: `static/css/style.css`
- Modify: `tests/test_scheduled_tasks_page_assets.py`
- Modify: `tests/test_registration_page_assets.py`

- [ ] **Step 1: Add failing shell assertions for the remaining workbench pages**

Add source assertions that these templates now extend the shared shell and expose page-level layout classes:

```python
for path in [
    "templates/accounts.html",
    "templates/scheduled_tasks.html",
    "templates/email_services.html",
    "templates/settings.html",
    "templates/payment.html",
]:
    template = Path(path).read_text(encoding="utf-8")
    assert '{% extends "_workspace_base.html" %}' in template
```

For `tests/test_scheduled_tasks_page_assets.py`, add:

```python
assert "page-head" in template
assert "workspace-panel" in template
```

- [ ] **Step 2: Run the focused asset tests to verify they fail**

Run:

```bash
uv run pytest tests/test_scheduled_tasks_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: FAIL because those templates still use standalone page documents.

- [ ] **Step 3: Convert the execution/configuration templates one by one**

For each template, move only the document shell into `_workspace_base.html` and keep existing inner IDs/hooks. Example pattern:

```html
{% extends "_workspace_base.html" %}

{% block page_metrics %}
<section class="hero-metrics">...</section>
{% endblock %}

{% block page_content %}
<section class="workspace-panel">...</section>
{% endblock %}
```

Apply this to:

1. `accounts.html`
2. `scheduled_tasks.html`
3. `email_services.html`
4. `settings.html`
5. `payment.html`

Do not rework the business forms or tables beyond moving them into shared cards/panels.

- [ ] **Step 4: Add any shared CSS selectors needed for migrated layouts**

Extend `static/css/style.css` with selectors such as:

```css
.workspace-table-panel { ... }
.workspace-toolbar { ... }
.workspace-side-stack { ... }
.config-workbench-grid { ... }
```

Keep page-specific CSS minimal; add shared rules before page-specific fallbacks.

- [ ] **Step 5: Re-run the focused asset suites**

Run:

```bash
uv run pytest tests/test_scheduled_tasks_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the execution/configuration page migration**

```bash
git add templates/accounts.html templates/scheduled_tasks.html templates/email_services.html templates/settings.html templates/payment.html static/css/style.css tests/test_scheduled_tasks_page_assets.py tests/test_registration_page_assets.py
git commit -m "feat: migrate execution and configuration pages to workspace shell"
```

---

### Task 6: Migrate the analysis pages and login page into the same visual system

**Files:**
- Modify: `templates/registration_experiments.html`
- Modify: `templates/registration_batch_stats.html`
- Modify: `templates/login.html`
- Modify: `static/css/style.css`
- Modify: `tests/test_registration_experiment_page_assets.py`
- Modify: `tests/test_registration_batch_stats_page_assets.py`

- [ ] **Step 1: Add failing shell/login visual assertions**

In `tests/test_registration_experiment_page_assets.py` and `tests/test_registration_batch_stats_page_assets.py`, assert:

```python
template = Path("templates/registration_experiments.html").read_text(encoding="utf-8")
assert '{% extends "_workspace_base.html" %}' in template
assert "page-head" in template
```

Add a new login source test (either here or in a dedicated login asset test if one already exists) asserting:

```python
template = Path("templates/login.html").read_text(encoding="utf-8")
assert "login-card" in template
assert "warm-surface" in Path("static/css/style.css").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
uv run pytest tests/test_registration_experiment_page_assets.py tests/test_registration_batch_stats_page_assets.py -q
```

Expected: FAIL because the analysis and login templates still use their old standalone structure.

- [ ] **Step 3: Convert the analysis pages to the shared shell**

Update both analysis templates so they extend `_workspace_base.html`, expose a consistent page head, and wrap existing content containers in analysis-oriented panels. Preserve IDs already consumed by the JS harnesses:

```html
id="experiment-summary"
id="experiment-step-compare"
id="survival-summary"
id="batch-stats-list"
id="batch-compare-panel"
```

Do not rename those IDs in this task.

- [ ] **Step 4: Restyle the login page using the same warm design tokens**

Keep the login route/form behavior unchanged, but migrate the markup into a centered card using the shared warm palette:

```html
<main class="login-shell">
  <section class="login-card">
    <form id="login-form">...</form>
  </section>
</main>
```

Add corresponding CSS selectors without pulling the full sidebar shell into the login page.

- [ ] **Step 5: Re-run the focused tests and the existing JS harnesses**

Run:

```bash
uv run pytest tests/test_registration_experiment_page_assets.py tests/test_registration_batch_stats_page_assets.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the analysis/login migration**

```bash
git add templates/registration_experiments.html templates/registration_batch_stats.html templates/login.html static/css/style.css tests/test_registration_experiment_page_assets.py tests/test_registration_batch_stats_page_assets.py
git commit -m "feat: migrate analysis and login pages to redesigned ui"
```

---

### Task 7: Close the loop with asset-versioning, route smoke tests, and full UI regression

**Files:**
- Modify: `tests/test_static_asset_versioning.py`
- Modify: `src/web/app.py`
- Modify: `static/css/style.css`
- Modify: `static/js/workspace.js`
- Modify: `static/js/dashboard.js`

- [ ] **Step 1: Add failing static-version and route smoke coverage**

Extend `tests/test_static_asset_versioning.py` so rendered HTML proves the new shared assets are versioned:

```python
response = client.get("/")
assert "/static/js/workspace.js?v=" in response.text
assert "/static/js/dashboard.js?v=" in response.text

response = client.get("/registration-workbench")
assert "/static/js/workspace.js?v=" in response.text
assert "/static/js/app.js?v=" in response.text
```

Also add smoke GETs for `/accounts`, `/scheduled-tasks`, `/email-services`, `/settings`, `/registration-experiments`, and `/registration-batch-stats` after login.

- [ ] **Step 2: Run the new regression slice to verify it catches any missing asset wiring**

Run:

```bash
uv run pytest tests/test_static_asset_versioning.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: FAIL if any page forgot to include the new shared asset bundle or if route remaps broke auth/rendering.

- [ ] **Step 3: Fix the remaining missing asset or page-key wiring**

Typical final cleanup should look like:

```python
return templates.TemplateResponse(
    "accounts.html",
    {"request": request, **build_page_shell(page_key="accounts", page_title="账号工作台", page_subtitle="...")},
)
```

And:

```html
{% block extra_scripts %}
<script src="/static/js/workspace.js?v={{ static_version }}"></script>
<script src="/static/js/accounts.js?v={{ static_version }}"></script>
{% endblock %}
```

Keep this cleanup localized; avoid broad refactors in the final pass.

- [ ] **Step 4: Run the full UI-focused regression suite**

Run:

```bash
uv run pytest \
  tests/test_workspace_shell_assets.py \
  tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py \
  tests/test_static_asset_versioning.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Run the full project test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit the final verification pass**

```bash
git add tests/test_static_asset_versioning.py src/web/app.py static/css/style.css static/js/workspace.js static/js/dashboard.js
git commit -m "test: verify redesigned workspace ui assets"
```
