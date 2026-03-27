# Workbench Flow Workspace UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 codex-console 的 Web UI 重构为以“总览 → 注册工作台 → 运行中心”为主线的统一工作区，完成双主题、壳层、页面结构和关键交互的一致化升级。

**Architecture:** 保留 FastAPI + Jinja2 + vanilla JS 技术栈，不重写后端 API。通过重构 `page_shell`、公共模板、公共 CSS / JS 与页面级模板脚本，建立统一的工作区壳层、共享组件基线和新的页面信息架构；新增独立运行中心页面，并把现有运行态、日志流和支撑页内容重组到清晰的域模型中。

**Tech Stack:** Python / FastAPI / Jinja2 / vanilla JavaScript / CSS / pytest / Node-based JS harnesses

---

## File Structure Map

### Existing files to modify

- `src/web/page_shell.py` — 工作区导航结构、页面元数据、图标 key、分组映射
- `src/web/app.py` — 页面路由、页头文案、运行中心页面注册
- `src/web/routes/dashboard.py` — Dashboard quick links / recent activity 指向新 IA
- `templates/_workspace_base.html` — 工作区骨架、首帧状态预加载、页头主题按钮
- `templates/_workspace_sidebar.html` — 导航、侧边栏底部退出区、折叠结构
- `templates/dashboard.html` — 总览页结构
- `templates/index.html` — 注册工作台结构
- `templates/accounts.html` — 账号资产页结构
- `templates/registration_experiments.html` — 复盘页结构
- `templates/registration_batch_stats.html` — 复盘页结构
- `templates/scheduled_tasks.html` — 自动化页结构、运行中心拆分后的收敛
- `templates/email_services.html` — 支撑页结构
- `templates/settings.html` — 支撑页结构
- `templates/payment.html` — 支撑页结构
- `templates/login.html` — 登录页图标与主题预设兼容
- `static/css/style.css` — 全局 token、表单/按钮/基础工具样式
- `static/css/dashboard_page.css` — Dashboard 页面样式
- `static/css/registration_workbench.css` — 注册工作台样式
- `static/css/realtime_log_console.css` — 共享日志组件样式
- `static/js/workspace.js` — 主题 / 折叠状态恢复与全局壳层交互
- `static/js/dashboard.js` — Dashboard 数据渲染与加载状态
- `static/js/app.js` — 注册工作台配置与运行态逻辑
- `static/js/registration_stream.js` — 注册工作台实时流集成
- `static/js/accounts.js` — 账号资产页逻辑
- `static/js/scheduled_tasks.js` — 自动化页逻辑，拆出运行中心共享逻辑后收敛
- `static/js/registration_experiments.js` — 复盘页逻辑
- `static/js/registration_batch_stats.js` — 复盘页逻辑
- `static/js/email_services.js` — 支撑页逻辑
- `static/js/settings.js` — 支撑页逻辑
- `static/js/payment.js` — 支撑页逻辑
- `static/js/utils.js` — toast / loading / theme 等通用行为

### New files to create

- `templates/_workspace_icons.html` — 统一 SVG 图标宏
- `templates/run_center.html` — 独立运行中心页面
- `static/css/workspace_shell.css` — 壳层、侧边栏、页头、首帧过渡控制
- `static/css/workspace_components.css` — 统计卡、筛选栏、表格、badge、drawer、empty state 基线
- `static/css/run_center.css` — 运行中心页面样式
- `static/js/run_center_shared.js` — 运行态列表 / 日志 / 详情的共享控制器
- `static/js/run_center.js` — 运行中心页面引导脚本
- `tests/test_run_center_page_assets.py` — 运行中心页面资产与路由测试
- `tests/test_accounts_page_assets.py` — 账号资产页模板 / 脚本 / 交互契约测试
- `tests/test_support_pages_assets.py` — 邮箱 / 设置 / 支付等支撑页资产测试
- `tests_runtime/run_center_js_harness.py` — 运行中心 JS harness
- `tests_runtime/accounts_js_harness.py` — 账号资产页 JS harness

### Existing tests to modify

- `tests/test_workspace_shell_assets.py`
- `tests/test_dashboard_page_assets.py`
- `tests/test_registration_page_assets.py`
- `tests/test_scheduled_tasks_page_assets.py`
- `tests/test_registration_experiment_page_assets.py`
- `tests/test_registration_batch_stats_page_assets.py`
- `tests_runtime/workspace_js_harness.py`
- `tests_runtime/dashboard_js_harness.py`
- `tests_runtime/app_js_harness.py`

---

### Task 1: 固化壳层契约与首帧状态恢复

**Files:**
- Create: `templates/_workspace_icons.html`
- Modify: `src/web/page_shell.py`
- Modify: `templates/_workspace_base.html`
- Modify: `templates/_workspace_sidebar.html`
- Modify: `static/js/workspace.js`
- Test: `tests/test_workspace_shell_assets.py`
- Test: `tests/test_dashboard_page_assets.py`
- Test: `tests/test_registration_page_assets.py`
- Test: `tests_runtime/workspace_js_harness.py`

- [ ] **Step 1: 写出壳层契约的失败测试**

```python
def test_page_shell_navigation_groups_match_workbench_flow_ia():
    expected_nav = {
        "总览": ["dashboard"],
        "执行": ["registration_workbench", "run_center", "accounts"],
        "复盘": ["registration_experiments", "registration_batch_stats"],
        "支撑": ["scheduled_tasks", "email_services", "settings", "payment"],
    }
    actual_nav = {
        group["group"]: [item["key"] for item in group["items"]]
        for group in WORKSPACE_NAV
    }
    assert actual_nav == expected_nav


def test_workspace_base_renders_theme_button_in_page_head_and_logout_in_sidebar_footer():
    rendered_html = environment.get_template("_workspace_base.html").render(...)
    assert 'data-workspace-theme-toggle' in rendered_html
    assert 'href="/logout"' in rendered_html
    assert 'workspace-sidebar-footer' in rendered_html
    assert 'workspace-shell-actions' not in rendered_html or 'href="/logout"' not in rendered_html.split('workspace-shell-actions', 1)[-1]


def test_workspace_base_includes_preflight_state_script_before_workspace_bundle():
    rendered_html = environment.get_template("_workspace_base.html").render(...)
    assert "codex-console.workspace.sidebar" in rendered_html
    assert "document.documentElement.setAttribute('data-theme'" in rendered_html
```

- [ ] **Step 2: 运行壳层测试，确认它们先失败**

Run:

```bash
timeout 60s pytest \
  tests/test_workspace_shell_assets.py \
  tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py -q
```

Expected: FAIL，提示页头/侧边栏位置、preflight script 或 nav contract 尚未满足。

- [ ] **Step 3: 实现最小壳层改造**

```python
# src/web/page_shell.py
WORKSPACE_NAV = [
    {"group": "总览", "items": [{"key": "dashboard", "label": "控制台总览", "href": "/", "icon": "layout-dashboard"}]},
    {"group": "执行", "items": [
        {"key": "registration_workbench", "label": "注册工作台", "href": "/registration-workbench", "icon": "sparkles"},
        {"key": "run_center", "label": "运行中心", "href": "/run-center", "icon": "activity"},
        {"key": "accounts", "label": "账号资产", "href": "/accounts", "icon": "users"},
    ]},
    {"group": "复盘", "items": [
        {"key": "registration_experiments", "label": "实验复盘", "href": "/registration-experiments", "icon": "flask-conical"},
        {"key": "registration_batch_stats", "label": "批次统计", "href": "/registration-batch-stats", "icon": "chart-column"},
    ]},
    {"group": "支撑", "items": [
        {"key": "scheduled_tasks", "label": "自动化任务", "href": "/scheduled-tasks", "icon": "calendar-cog"},
        {"key": "email_services", "label": "邮箱服务", "href": "/email-services", "icon": "mail"},
        {"key": "settings", "label": "系统设置", "href": "/settings", "icon": "settings-2"},
        {"key": "payment", "label": "支付工具", "href": "/payment", "icon": "credit-card"},
    ]},
]
```

```html
<!-- templates/_workspace_base.html -->
<head>
  <script>
    (function () {
      try {
        var theme = localStorage.getItem('theme') || 'light';
        var sidebar = localStorage.getItem('codex-console.workspace.sidebar') || 'expanded';
        document.documentElement.setAttribute('data-theme', theme);
        if (sidebar === 'collapsed') {
          document.documentElement.classList.add('workspace-sidebar-collapsed');
        }
      } catch (error) {}
    })();
  </script>
  <link rel="stylesheet" href="/static/css/style.css?v={{ static_version }}">
</head>
```

```html
<!-- templates/_workspace_sidebar.html -->
<aside class="workspace-sidebar">
  ...
  <footer class="workspace-sidebar-footer">
    <a href="/logout" class="workspace-sidebar-logout">退出登录</a>
  </footer>
</aside>
```

- [ ] **Step 4: 重新运行壳层测试并确认通过**

Run:

```bash
timeout 60s pytest \
  tests/test_workspace_shell_assets.py \
  tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 1**

```bash
git add src/web/page_shell.py templates/_workspace_base.html templates/_workspace_sidebar.html \
  templates/_workspace_icons.html static/js/workspace.js \
  tests/test_workspace_shell_assets.py tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py tests_runtime/workspace_js_harness.py
git commit -m "feat: stabilize workspace shell state and layout contract"
```

---

### Task 2: 建立共享 token、壳层样式与组件基线

**Files:**
- Create: `static/css/workspace_shell.css`
- Create: `static/css/workspace_components.css`
- Modify: `static/css/style.css`
- Modify: `templates/_workspace_base.html`
- Modify: `templates/login.html`
- Test: `tests/test_workspace_shell_assets.py`
- Test: `tests/test_support_pages_assets.py`

- [ ] **Step 1: 为共享样式拆分写失败测试**

```python
def test_workspace_base_loads_shell_and_component_stylesheets():
    rendered_html = environment.get_template("_workspace_base.html").render(...)
    assert "/static/css/workspace_shell.css?v=" in rendered_html
    assert "/static/css/workspace_components.css?v=" in rendered_html


def test_workspace_shell_styles_define_sidebar_footer_and_page_head_actions():
    stylesheet = Path("static/css/workspace_shell.css").read_text(encoding="utf-8")
    assert ".workspace-sidebar-footer" in stylesheet
    assert ".page-head-actions" in stylesheet
```

- [ ] **Step 2: 运行共享样式测试，确认失败**

Run:

```bash
timeout 60s pytest tests/test_workspace_shell_assets.py tests/test_support_pages_assets.py -q
```

Expected: FAIL，提示缺少新样式文件或缺少 selector。

- [ ] **Step 3: 实现 token 与共享组件基线**

```css
/* static/css/workspace_shell.css */
:root {
  --brand-primary: #4338ca;
  --brand-primary-strong: #1e40af;
  --surface-bg: #f8fafc;
  --surface-card: #ffffff;
  --surface-muted: #eef2ff;
  --accent-warning: #d97706;
}

[data-theme="dark"] {
  --surface-bg: #0b1220;
  --surface-card: #121a2b;
  --surface-muted: #172036;
}
```

```css
/* static/css/workspace_components.css */
.workspace-stat-card { ... }
.workspace-filter-bar { ... }
.workspace-data-table { ... }
.workspace-status-badge { ... }
.workspace-empty-state { ... }
.workspace-drawer { ... }
```

- [ ] **Step 4: 重新运行共享样式测试并确认通过**

Run:

```bash
timeout 60s pytest tests/test_workspace_shell_assets.py tests/test_support_pages_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 2**

```bash
git add static/css/style.css static/css/workspace_shell.css static/css/workspace_components.css \
  templates/_workspace_base.html templates/login.html \
  tests/test_workspace_shell_assets.py tests/test_support_pages_assets.py
git commit -m "feat: add shared workspace shell and component styles"
```

---

### Task 3: 引入运行中心路由并更新导航与 Dashboard 数据入口

**Files:**
- Create: `templates/run_center.html`
- Create: `static/css/run_center.css`
- Create: `static/js/run_center.js`
- Create: `tests/test_run_center_page_assets.py`
- Modify: `src/web/app.py`
- Modify: `src/web/page_shell.py`
- Modify: `src/web/routes/dashboard.py`
- Test: `tests/test_dashboard_page_assets.py`

- [ ] **Step 1: 写运行中心路由与 Dashboard quick links 的失败测试**

```python
def test_web_app_registers_run_center_page_route():
    app_source = Path("src/web/app.py").read_text(encoding="utf-8")
    assert '@app.get("/run-center", response_class=HTMLResponse)' in app_source
    assert '"run_center.html"' in app_source


def test_dashboard_summary_uses_run_center_and_support_navigation_targets():
    payload = client.get("/api/dashboard/summary").json()
    hrefs = {item["href"] for item in payload["quick_links"]}
    assert "/run-center" in hrefs
```

- [ ] **Step 2: 运行路由与 Dashboard 测试，确认失败**

Run:

```bash
timeout 60s pytest \
  tests/test_run_center_page_assets.py \
  tests/test_dashboard_page_assets.py -q
```

Expected: FAIL，提示 run-center route/template 或 quick links 尚未存在。

- [ ] **Step 3: 实现最小路由与模板骨架**

```python
# src/web/app.py
@app.get("/run-center", response_class=HTMLResponse)
async def run_center_page(request: Request):
    if not is_authenticated(request):
        return _redirect_to_login(request)
    return templates.TemplateResponse(
        request,
        "run_center.html",
        _workspace_context(
            request,
            page_key="run_center",
            page_title="运行中心",
            page_subtitle="查看运行中任务、关键日志与控制动作。",
        ),
    )
```

```html
<!-- templates/run_center.html -->
{% extends "_workspace_base.html" %}
{% block head_extra %}
<link rel="stylesheet" href="/static/css/run_center.css?v={{ static_version }}">
{% endblock %}
{% block page_content %}
<section id="run-center-page" class="run-center-page">
  <div id="run-center-summary"></div>
  <div id="run-center-list"></div>
  <div id="run-center-log-panel"></div>
</section>
{% endblock %}
{% block page_scripts %}
<script src="/static/js/run_center.js?v={{ static_version }}"></script>
{% endblock %}
```

- [ ] **Step 4: 重新运行路由与 Dashboard 测试并确认通过**

Run:

```bash
timeout 60s pytest \
  tests/test_run_center_page_assets.py \
  tests/test_dashboard_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add src/web/app.py src/web/page_shell.py src/web/routes/dashboard.py \
  templates/run_center.html static/css/run_center.css static/js/run_center.js \
  tests/test_run_center_page_assets.py tests/test_dashboard_page_assets.py
git commit -m "feat: add run center route and dashboard navigation wiring"
```

---

### Task 4: 重做 Dashboard 总览页为启动台

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `static/css/dashboard_page.css`
- Modify: `static/js/dashboard.js`
- Test: `tests/test_dashboard_page_assets.py`
- Test: `tests_runtime/dashboard_js_harness.py`

- [ ] **Step 1: 写总览页启动台结构的失败测试**

```python
def test_dashboard_template_contains_overview_hub_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="dashboard-overview-summary"' in template
    assert 'id="dashboard-overview-alerts"' in template
    assert 'id="dashboard-overview-launchpad"' in template
```

- [ ] **Step 2: 运行 Dashboard 测试，确认失败**

Run:

```bash
timeout 60s pytest tests/test_dashboard_page_assets.py -q
```

Expected: FAIL，提示新容器、JS render helpers 或样式 selector 缺失。

- [ ] **Step 3: 实现总览页新布局与加载态**

```javascript
function renderOverviewLaunchpad(links) {
  return links.map((link) => `
    <a class="overview-launchpad-card" href="${escapeHtml(safeHref(link.href))}">
      <strong>${escapeHtml(link.label)}</strong>
      <span>${escapeHtml(link.description || '')}</span>
    </a>
  `).join('');
}

function renderLoadingState() {
  document.getElementById('dashboard-overview-summary').innerHTML = '<div class="workspace-skeleton-card"></div>';
}
```

- [ ] **Step 4: 重新运行 Dashboard 测试并确认通过**

Run:

```bash
timeout 60s pytest tests/test_dashboard_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 4**

```bash
git add templates/dashboard.html static/css/dashboard_page.css static/js/dashboard.js \
  tests/test_dashboard_page_assets.py tests_runtime/dashboard_js_harness.py
git commit -m "feat: redesign dashboard as overview hub"
```

---

### Task 5: 抽离运行中心共享逻辑，并让自动化页回归支撑域

**Files:**
- Create: `static/js/run_center_shared.js`
- Modify: `static/js/run_center.js`
- Modify: `static/js/scheduled_tasks.js`
- Modify: `static/js/registration_stream.js`
- Modify: `static/js/app.js`
- Modify: `templates/run_center.html`
- Modify: `templates/scheduled_tasks.html`
- Modify: `static/css/run_center.css`
- Test: `tests/test_run_center_page_assets.py`
- Test: `tests/test_scheduled_tasks_page_assets.py`
- Test: `tests/test_registration_page_assets.py`
- Test: `tests_runtime/run_center_js_harness.py`
- Test: `tests_runtime/app_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定“运行中心独立 / 自动化页瘦身”契约**

```python
def test_run_center_template_contains_run_filters_table_and_log_panel():
    template = Path("templates/run_center.html").read_text(encoding="utf-8")
    assert 'id="run-center-filter-status"' in template
    assert 'id="run-center-table-body"' in template
    assert 'id="run-center-log-panel"' in template


def test_scheduled_tasks_template_keeps_plan_management_but_not_primary_run_center_shell():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="create-plan-btn"' in template
    assert 'id="scheduled-runs-card"' not in template


def test_registration_workbench_and_run_center_share_run_identity_contract():
    result = run_app_js_scenario("run_center_link_contract")
    assert result["run_center_href"].startswith("/run-center?")
    assert "task_uuid=task-single-01" in result["run_center_href"]
    assert "source=registration-workbench" in result["run_center_href"]


def test_run_center_template_exposes_retry_and_scope_controls():
    template = Path("templates/run_center.html").read_text(encoding="utf-8")
    assert 'id="run-center-retry-btn"' in template
    assert 'id="run-center-control-scope"' in template
```

- [ ] **Step 2: 运行运行中心 / 自动化测试，确认失败**

Run:

```bash
timeout 60s pytest \
  tests/test_run_center_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_page_assets.py -q
```

Expected: FAIL

- [ ] **Step 3: 抽离共享 run controller，并收敛 scheduled_tasks.js**

```javascript
// static/js/run_center_shared.js
window.createRunCenterController = function createRunCenterController(deps) {
  return {
    loadRuns() { ... },
    openRunLog(runId) { ... },
    stopRun(runId) { ... },
    retryRun(runId, scope) { ... },
    openRegistrationTask(taskUuid) { ... },
  };
};
```

```javascript
// static/js/scheduled_tasks.js
document.addEventListener('DOMContentLoaded', () => {
  bindPlanManagement();
  // 不再承载主运行中心逻辑
});
```

```javascript
// static/js/registration_stream.js / static/js/app.js
function buildRunCenterHref(task) {
  const params = new URLSearchParams({
    task_uuid: task.task_uuid,
    source: 'registration-workbench',
    scope: task.batch_id ? 'batch' : 'task',
  });
  if (task.run_id) {
    params.set('run_id', String(task.run_id));
  }
  if (task.batch_id) {
    params.set('batch_id', String(task.batch_id));
  }
  return `/run-center?${params.toString()}`;
}
```

```javascript
// run_center_shared.js
function resolveControlScope(params) {
  if (params.get('plan_id')) return 'scheduled';
  if (params.get('batch_id')) return 'batch';
  return 'task';
}
```

- [ ] **Step 4: 重新运行运行中心 / 自动化测试并确认通过**

Run:

```bash
timeout 60s pytest \
  tests/test_run_center_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 5**

```bash
git add static/js/run_center_shared.js static/js/run_center.js static/js/scheduled_tasks.js \
  static/js/registration_stream.js static/js/app.js \
  templates/run_center.html templates/scheduled_tasks.html static/css/run_center.css \
  tests/test_run_center_page_assets.py tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_page_assets.py tests_runtime/run_center_js_harness.py \
  tests_runtime/app_js_harness.py
git commit -m "feat: extract dedicated run center and slim scheduled tasks page"
```

---

### Task 6: 把注册页重构为带工作台视图切换的专家控制台

**Files:**
- Modify: `templates/index.html`
- Modify: `static/css/registration_workbench.css`
- Modify: `static/js/app.js`
- Modify: `static/js/registration_stream.js`
- Modify: `static/css/realtime_log_console.css`
- Test: `tests/test_registration_page_assets.py`
- Test: `tests_runtime/app_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定“配置 / 运行中 / 最近结果”三视图结构**

```python
def test_registration_template_contains_workbench_tabs_and_views():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'data-workbench-view="config"' in template
    assert 'data-workbench-view="running"' in template
    assert 'data-workbench-view="recent"' in template
    assert 'id="registration-workbench-tabs"' in template
```

- [ ] **Step 2: 运行注册工作台测试，确认失败**

Run:

```bash
timeout 60s pytest tests/test_registration_page_assets.py -q
```

Expected: FAIL

- [ ] **Step 3: 实现工作台三视图与专家控制台布局**

```html
<section class="registration-workbench-shell">
  <nav id="registration-workbench-tabs" class="workbench-tabs">
    <button data-workbench-view="config">配置</button>
    <button data-workbench-view="running">运行中</button>
    <button data-workbench-view="recent">最近结果</button>
  </nav>
  <section id="registration-workbench-view-config">...</section>
  <section id="registration-workbench-view-running" hidden>...</section>
  <section id="registration-workbench-view-recent" hidden>...</section>
</section>
```

```javascript
function switchWorkbenchView(nextView) {
  for (const section of document.querySelectorAll('[data-workbench-panel]')) {
    section.hidden = section.dataset.workbenchPanel !== nextView;
  }
}
```

- [ ] **Step 4: 重新运行注册工作台测试并确认通过**

Run:

```bash
timeout 60s pytest tests/test_registration_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 6**

```bash
git add templates/index.html static/css/registration_workbench.css static/css/realtime_log_console.css \
  static/js/app.js static/js/registration_stream.js \
  tests/test_registration_page_assets.py tests_runtime/app_js_harness.py
git commit -m "feat: redesign registration workbench as tabbed expert console"
```

---

### Task 7: 把账号管理重构为“账号资产”页

**Files:**
- Create: `tests/test_accounts_page_assets.py`
- Create: `tests_runtime/accounts_js_harness.py`
- Modify: `templates/accounts.html`
- Modify: `static/js/accounts.js`
- Modify: `static/css/workspace_components.css`

- [ ] **Step 1: 写账号资产页的失败测试**

```python
def test_accounts_template_contains_asset_toolbar_table_and_detail_drawer():
    template = Path("templates/accounts.html").read_text(encoding="utf-8")
    assert 'id="accounts-asset-toolbar"' in template
    assert 'id="accounts-detail-drawer"' in template
    assert 'id="accounts-table"' in template


def test_accounts_drawer_accessibility_contract():
    result = run_accounts_js_harness("drawer_focus_contract")
    assert result == {
        "focus_moved_into_drawer": True,
        "escape_closes_drawer": True,
        "focus_returned_to_trigger": True,
    }
```

- [ ] **Step 2: 运行账号资产页测试，确认失败**

Run:

```bash
timeout 60s pytest tests/test_accounts_page_assets.py -q
```

Expected: FAIL

- [ ] **Step 3: 实现账号资产页布局与详情抽屉**

```html
<section class="accounts-asset-page">
  <header id="accounts-asset-toolbar" class="workspace-filter-bar">...</header>
  <section class="workspace-table-shell">...</section>
  <aside id="accounts-detail-drawer" class="workspace-drawer" hidden></aside>
</section>
```

```javascript
function openAccountDrawer(account) {
  elements.detailDrawer.hidden = false;
  elements.detailDrawer.setAttribute('aria-modal', 'true');
  elements.detailDrawer.focus();
  elements.detailDrawer.innerHTML = renderAccountDetail(account);
}
```

- [ ] **Step 4: 重新运行账号资产页测试并确认通过**

Run:

```bash
timeout 60s pytest tests/test_accounts_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 7**

```bash
git add templates/accounts.html static/js/accounts.js static/css/workspace_components.css \
  tests/test_accounts_page_assets.py tests_runtime/accounts_js_harness.py
git commit -m "feat: redesign accounts page as asset workspace"
```

---

### Task 8: 合并实验与批次统计为统一复盘域

**Files:**
- Modify: `templates/registration_experiments.html`
- Modify: `templates/registration_batch_stats.html`
- Modify: `static/js/registration_experiments.js`
- Modify: `static/js/registration_batch_stats.js`
- Modify: `static/css/workspace_components.css`
- Test: `tests/test_registration_experiment_page_assets.py`
- Test: `tests/test_registration_batch_stats_page_assets.py`

- [ ] **Step 1: 写失败测试，锁定统一复盘结构**

```python
def test_experiment_and_batch_stats_templates_share_retro_shell_hooks():
    experiments = Path("templates/registration_experiments.html").read_text(encoding="utf-8")
    batch_stats = Path("templates/registration_batch_stats.html").read_text(encoding="utf-8")
    assert 'data-retro-section="summary"' in experiments
    assert 'data-retro-section="summary"' in batch_stats
```

- [ ] **Step 2: 运行复盘页测试，确认失败**

Run:

```bash
timeout 60s pytest \
  tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py -q
```

Expected: FAIL

- [ ] **Step 3: 实现统一分析页头、复盘面板和比较组件**

```html
<section class="retro-dashboard">
  <header class="retro-page-header">...</header>
  <div class="retro-summary-grid" data-retro-section="summary"></div>
  <div class="retro-analysis-panel" data-retro-section="analysis"></div>
</section>
```

- [ ] **Step 4: 重新运行复盘页测试并确认通过**

Run:

```bash
timeout 60s pytest \
  tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 8**

```bash
git add templates/registration_experiments.html templates/registration_batch_stats.html \
  static/js/registration_experiments.js static/js/registration_batch_stats.js \
  static/css/workspace_components.css \
  tests/test_registration_experiment_page_assets.py tests/test_registration_batch_stats_page_assets.py
git commit -m "feat: unify retro analysis pages"
```

---

### Task 9: 收敛邮箱 / 设置 / 支付为支撑域页面

**Files:**
- Create: `tests/test_support_pages_assets.py`
- Modify: `templates/email_services.html`
- Modify: `templates/settings.html`
- Modify: `templates/payment.html`
- Modify: `static/js/email_services.js`
- Modify: `static/js/settings.js`
- Modify: `static/js/payment.js`
- Modify: `static/css/workspace_components.css`

- [ ] **Step 1: 写支撑域页面失败测试**

```python
def test_support_pages_use_shared_page_header_and_panel_shell():
    for path in ["templates/email_services.html", "templates/settings.html", "templates/payment.html"]:
        template = Path(path).read_text(encoding="utf-8")
        assert "workspace-panel" in template
        assert "page-head" in template or "page-header" in template


def test_support_page_danger_modal_defaults_focus_to_cancel():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'data-danger-default="cancel"' in template
```

- [ ] **Step 2: 运行支撑域测试，确认失败**

Run:

```bash
timeout 60s pytest tests/test_support_pages_assets.py -q
```

Expected: FAIL

- [ ] **Step 3: 实现支撑域统一页头、面板和反馈模式**

```html
<section class="support-page-shell">
  <div class="workspace-panel support-page-summary">...</div>
  <div class="workspace-panel support-page-content">...</div>
</section>
```

```javascript
async function submitWithInlineFeedback(form, action) {
  setInlineStatus(form, 'loading', '处理中...');
  try {
    await action();
    setInlineStatus(form, 'success', '保存成功');
  } catch (error) {
    setInlineStatus(form, 'error', error.message || '保存失败');
  }
}

function openDangerModal(modal) {
  modal.hidden = false;
  modal.querySelector('[data-danger-default="cancel"]')?.focus();
}
```

- [ ] **Step 4: 重新运行支撑域测试并确认通过**

Run:

```bash
timeout 60s pytest tests/test_support_pages_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 9**

```bash
git add templates/email_services.html templates/settings.html templates/payment.html \
  static/js/email_services.js static/js/settings.js static/js/payment.js \
  static/css/workspace_components.css tests/test_support_pages_assets.py
git commit -m "feat: unify support domain pages"
```

---

### Task 10: 统一可访问性、加载反馈与最终回归验证

**Files:**
- Modify: `static/js/utils.js`
- Modify: `static/js/workspace.js`
- Modify: `static/js/dashboard.js`
- Modify: `static/js/accounts.js`
- Modify: `static/js/run_center.js`
- Modify: `static/js/scheduled_tasks.js`
- Modify: `static/js/registration_experiments.js`
- Modify: `static/js/registration_batch_stats.js`
- Modify: `static/css/workspace_shell.css`
- Modify: `static/css/workspace_components.css`
- Test: `tests/test_workspace_shell_assets.py`
- Test: `tests/test_dashboard_page_assets.py`
- Test: `tests/test_registration_page_assets.py`
- Test: `tests/test_scheduled_tasks_page_assets.py`
- Test: `tests/test_registration_experiment_page_assets.py`
- Test: `tests/test_registration_batch_stats_page_assets.py`
- Test: `tests/test_accounts_page_assets.py`
- Test: `tests/test_run_center_page_assets.py`
- Test: `tests/test_support_pages_assets.py`
- Test: `tests_runtime/app_js_harness.py`
- Test: `tests_runtime/run_center_js_harness.py`

- [ ] **Step 1: 写最后一批失败测试，锁定 a11y 与反馈契约**

```python
def test_workspace_theme_and_sidebar_restore_before_dom_ready_contract():
    script = Path("templates/_workspace_base.html").read_text(encoding="utf-8")
    assert "document.documentElement.classList.add('workspace-sidebar-collapsed')" in script
    assert "document.documentElement.setAttribute('data-theme'" in script


def test_toast_and_inline_errors_expose_accessible_roles():
    utils = Path("static/js/utils.js").read_text(encoding="utf-8")
    assert 'role="status"' in utils or "setAttribute('role', 'status')" in utils


def test_run_center_preserves_registration_workbench_task_semantics():
    result = run_run_center_js_scenario("registration_context_contract")
    assert result["source"] == "registration-workbench"
    assert result["task_uuid"] == "task-single-01"
    assert result["control_scope"] == "task"


def test_run_center_retry_contract_distinguishes_task_batch_and_scheduled_scope():
    result = run_run_center_js_scenario("retry_scope_contract")
    assert result == {
        "task_scope": "task",
        "batch_scope": "batch",
        "scheduled_scope": "scheduled",
    }


def test_drawer_and_modal_accessibility_contracts_are_enforced():
    result = run_accounts_js_harness("modal_a11y_contract")
    assert result == {
        "escape_closes": True,
        "focus_trap_active": True,
        "cancel_default_focus": True,
        "trigger_focus_restored": True,
    }
```

- [ ] **Step 2: 运行完整 UI 相关测试集，确认存在失败点**

Run:

```bash
timeout 60s pytest \
  tests/test_workspace_shell_assets.py \
  tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py \
  tests/test_accounts_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_support_pages_assets.py -q
```

Expected: FAIL，暴露缺少 role、loading/empty/error contract 或首帧状态契约问题。

- [ ] **Step 3: 实现统一反馈与可访问性收尾**

```javascript
// static/js/utils.js
toast.setAttribute('role', 'status');
toast.setAttribute('aria-live', 'polite');

function renderInlineError(target, message) {
  target.innerHTML = `<div class="workspace-inline-error" role="alert">${escapeHtml(message)}</div>`;
}

function trapFocus(container, event) { ... }
function restoreTriggerFocus(trigger) { ... }
```

```css
.workspace-focus-ring:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.workspace-icon-button {
  min-width: 44px;
  min-height: 44px;
}
```

- [ ] **Step 4: 运行完整 UI 回归测试并确认通过**

Run:

```bash
timeout 60s pytest \
  tests/test_workspace_shell_assets.py \
  tests/test_dashboard_page_assets.py \
  tests/test_registration_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py \
  tests/test_accounts_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_support_pages_assets.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 10**

```bash
git add static/js/utils.js static/js/workspace.js static/js/dashboard.js static/js/accounts.js \
  static/js/run_center.js static/js/scheduled_tasks.js static/js/registration_experiments.js \
  static/js/registration_batch_stats.js static/css/workspace_shell.css static/css/workspace_components.css \
  tests/test_workspace_shell_assets.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py \
  tests/test_scheduled_tasks_page_assets.py tests/test_registration_experiment_page_assets.py \
  tests/test_registration_batch_stats_page_assets.py tests/test_accounts_page_assets.py \
  tests/test_run_center_page_assets.py tests/test_support_pages_assets.py \
  tests_runtime/app_js_harness.py tests_runtime/run_center_js_harness.py
git commit -m "feat: finalize workspace accessibility and interaction polish"
```

---

## Final Verification Checklist

- [ ] `timeout 60s pytest tests/test_workspace_shell_assets.py -q`
- [ ] `timeout 60s pytest tests/test_dashboard_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_registration_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_scheduled_tasks_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_registration_experiment_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_registration_batch_stats_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_accounts_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_run_center_page_assets.py -q`
- [ ] `timeout 60s pytest tests/test_support_pages_assets.py -q`
- [ ] `timeout 60s pytest tests_runtime/app_js_harness.py tests_runtime/run_center_js_harness.py -q`
- [ ] `timeout 60s pytest -q`
