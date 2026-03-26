# Dashboard Workbench Polish Realtime Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有统一实时事件流基础上，完成 Dashboard 浅色高亮改版、侧边栏折叠态修复、注册工作台单任务进度条模式与日志区增高，并彻查实时日志延迟问题，同时为所有任务类型引入统一的“是否使用代理”策略。

**Architecture:** 继续沿用现有 FastAPI + Jinja2 + vanilla JS + realtime stream 架构，不推翻主链路。视觉层面通过页面级 CSS 和少量模板结构调整完成，实时问题通过“先写失败回归 -> 诊断根因 -> 修复 payload / reducer / fallback”收口，代理逻辑则统一落入 `ProxyDispatchService` 的单点策略入口。

**Tech Stack:** FastAPI、Jinja2、vanilla JS、WebSocket、pytest、Node JS harness、SQLAlchemy。

---

## Spec Reference

- `docs/superpowers/specs/2026-03-26-dashboard-workbench-polish-realtime-proxy-design.md`
- 基础能力前置：`docs/superpowers/specs/2026-03-25-dashboard-and-registration-realtime-event-stream-design.md`

## File Structure

### Workspace shell / sidebar

- Modify: `templates/_workspace_base.html`
  - 将侧边栏折叠按钮与主题按钮从页面头部收回到侧边栏区域。
- Modify: `templates/_workspace_sidebar.html`
  - 为导航项增加图标/文本分层结构，支持折叠后仅展示图标。
- Modify: `static/css/style.css`
  - 调整工作区 rail、sidebar、折叠态、按钮位置和图标态样式。
- Modify: `static/js/workspace.js`
  - 保持现有折叠状态持久化逻辑，补足按钮状态/可访问性钩子。
- Modify: `tests/test_workspace_shell_assets.py`
  - 锁定模板和样式选择器。
- Create: `tests_runtime/workspace_js_harness.py`
  - 最小 harness，验证折叠态 body class 与图标/文案切换。

### Dashboard visual polish

- Modify: `templates/dashboard.html`
  - 维持现有骨架挂点，如需最小 class/hook 增补则在此处理。
- Modify: `static/js/dashboard.js`
  - 为指标卡和快捷动作注入 tone / variant class。
- Modify: `static/css/dashboard_page.css`
  - 实现浅色高亮卡片背景、数字底色标签和按钮化快捷动作。
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests_runtime/dashboard_js_harness.py`

### Registration workbench UI

- Modify: `templates/index.html`
  - 在配置区新增 `use_proxy` 开关；重构单任务反馈区为进度条模式挂点。
- Modify: `static/css/registration_workbench.css`
  - 增高日志区、强化批任务卡、实现单任务进度卡样式。
- Modify: `static/js/app.js`
  - 渲染单任务进度摘要卡；把日志、批量、单任务反馈与新 DOM 挂点对齐。
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

### Realtime contract and diagnostics

- Modify: `src/core/pipeline/runner.py`
  - 在步骤回调里提供稳定的当前步骤序号 / 总步骤数 / 已耗时契约。
- Modify: `src/application/registration_service.py`
  - 将 runner 步骤回调与 task stream payload 对齐。
- Modify: `src/application/batch_registration_service.py`
  - 保证批量/Outlook 批量日志和终态都继续走统一 stream。
- Modify: `src/web/task_manager.py`
  - task snapshot / task_step_updated 事件新增稳定 progress payload。
- Modify: `static/js/registration_stream.js`
  - reducer 接收 `task_progress` 等显式字段，避免前端从最近步骤猜总步数。
- Modify: `static/js/app.js`
  - 用显式 progress payload 渲染单任务进度条，并诊断/修复日志未实时追加的 UI 路径。
- Modify: `tests/test_task_manager.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_stream_routes.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

### Proxy policy

- Modify: `src/application/proxy_dispatch_service.py`
  - 统一 `use_proxy`、动态代理、代理列表、静态代理、失败文案的单点决策。
- Modify: `src/application/registration_service.py`
  - 单任务按统一代理策略选择代理或创建后立即失败。
- Modify: `src/application/batch_registration_service.py`
  - 普通批量 / 无限 / Outlook 批量按统一策略准备候选代理或失败。
- Modify: `src/web/routes/registration.py`
  - 请求模型新增 `use_proxy`，并把静态代理 / 动态代理覆盖参数传到 service。
- Modify: `static/js/app.js`
  - 所有任务类型请求体加入 `use_proxy`。
- Modify: `templates/index.html`
  - 配置区新增 `use_proxy` 控件文案与提示。
- Modify: `tests/test_proxy_dispatch_service.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_batch_routes.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

## Parallelization Notes

- **Track A（Dashboard 视觉）**：Task 1 可独立执行。
- **Track B（侧边栏壳层）**：Task 2 可与 Task 1 并行，但只改 workspace shell 相关文件。
- **Track C（工作台 UI + 实时契约）**：Task 4 依赖 Task 3 的明确 progress payload 才能收口，Task 3 先行。
- **Track D（代理策略）**：Task 5 与 Task 1/2 可并行，但与 Task 3 都会触碰 `app.js` / `index.html`，因此建议串行整合。
- 推荐顺序：Task 1 和 Task 2 可先并行；**Task 3 先于 Task 4**，先把显式 progress contract 与实时日志修复落稳，再让 Task 4 绑定新 contract 渲染单任务进度卡；最后做 Task 5 和 Task 6。

### Task 1: Dashboard 改成浅色高亮卡片，并把快捷动作按钮化

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `static/js/dashboard.js`
- Modify: `static/css/dashboard_page.css`
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests_runtime/dashboard_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定 B 基线的指标卡 tone class 与快捷动作按钮结构**

```python
# tests/test_dashboard_page_assets.py

def test_dashboard_js_harness_renders_metric_tones_and_buttonized_quick_actions():
    result = run_dashboard_js_scenario("render_dashboard")
    assert "dashboard-metric-card--registration" in result["metric_html"]
    assert "dashboard-metric-value-badge--success-rate" in result["metric_html"]
    assert "dashboard-quick-action--primary" in result["quick_actions_html"]
    assert "dashboard-quick-action--secondary" in result["quick_actions_html"]
```

- [ ] **Step 2: 运行测试，确认当前 Dashboard 还没输出这些 tone / button class**

Run: `timeout 60s pytest tests/test_dashboard_page_assets.py::test_dashboard_js_harness_renders_metric_tones_and_buttonized_quick_actions -q`
Expected: FAIL

- [ ] **Step 3: 最小实现 Dashboard tone class 与按钮样式变体**

```javascript
// static/js/dashboard.js
function renderMetricCard(label, value, hint, tone) {
  return `
    <article class="dashboard-metric-card dashboard-metric-card--${tone}">
      ...
      <span class="dashboard-metric-value-badge dashboard-metric-value-badge--${tone}">${escapeHtml(value)}</span>
    </article>
  `;
}
```

```css
/* static/css/dashboard_page.css */
.dashboard-metric-card--registration { ... }
.dashboard-metric-value-badge--registration { ... }
.dashboard-quick-action--primary { ... }
.dashboard-quick-action--secondary { ... }
```

- [ ] **Step 4: 跑 Dashboard 相关测试，确认视觉 contract 成立**

Run: `timeout 60s pytest tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py -k 'dashboard' -q`
Expected: PASS

- [ ] **Step 5: 提交 Task 1**

```bash
git add templates/dashboard.html static/js/dashboard.js static/css/dashboard_page.css tests/test_dashboard_page_assets.py tests_runtime/dashboard_js_harness.py tests/test_static_asset_versioning.py
git commit -m "feat: polish dashboard cards and quick actions"
```

### Task 2: 修复侧边栏缩放按钮位置，并实现折叠后仅展示图标

**Files:**
- Modify: `templates/_workspace_base.html`
- Modify: `templates/_workspace_sidebar.html`
- Modify: `static/css/style.css`
- Modify: `static/js/workspace.js`
- Modify: `tests/test_workspace_shell_assets.py`
- Create: `tests_runtime/workspace_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定折叠按钮迁入侧边栏、折叠态仅展示图标**

```python
# tests/test_workspace_shell_assets.py

def test_workspace_sidebar_template_contains_sidebar_controls_and_nav_icon_label_structure():
    sidebar = Path("templates/_workspace_sidebar.html").read_text(encoding="utf-8")
    assert 'id="workspace-sidebar-toggle"' in sidebar
    assert 'id="workspace-theme-toggle"' in sidebar
    assert 'workspace-nav-icon' in sidebar
    assert 'workspace-nav-label' in sidebar
```

- [ ] **Step 2: 运行失败测试，确认按钮还在 page head、导航还没有 icon/label 分层**

Run: `timeout 60s pytest tests/test_workspace_shell_assets.py::test_workspace_sidebar_template_contains_sidebar_controls_and_nav_icon_label_structure -q`
Expected: FAIL

- [ ] **Step 3: 最小实现侧边栏结构与折叠态样式**

```html
<!-- templates/_workspace_sidebar.html -->
<button id="workspace-sidebar-toggle" ...>☰</button>
...
<a class="workspace-nav-link ...">
  <span class="workspace-nav-icon">🏠</span>
  <span class="workspace-nav-label">控制台总览</span>
</a>
```

```css
.workspace-sidebar-collapsed .workspace-nav-label { display: none; }
.workspace-sidebar-collapsed .workspace-nav-link { justify-content: center; }
```

- [ ] **Step 4: 跑 shell/样式测试，确认折叠态 contract 成立**

Run: `timeout 60s pytest tests/test_workspace_shell_assets.py -q`
Expected: PASS

- [ ] **Step 5: 提交 Task 2**

```bash
git add templates/_workspace_base.html templates/_workspace_sidebar.html static/css/style.css static/js/workspace.js tests/test_workspace_shell_assets.py tests_runtime/workspace_js_harness.py
git commit -m "feat: polish workspace sidebar collapsed state"
```

### Task 3: 诊断并修复“实时日志还是不实时”，同时补齐稳定的单任务 progress payload 契约

**Files:**
- Modify: `src/core/pipeline/runner.py`
- Modify: `src/application/registration_service.py`
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/web/task_manager.py`
- Modify: `static/js/registration_stream.js`
- Modify: `static/js/app.js`
- Modify: `tests/test_task_manager.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_stream_routes.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

- [ ] **Step 1: 先写失败测试，锁定两件事：日志必须由 `log_appended` 立即进入 DOM；单任务必须收到显式 `step_index/total_steps` 契约**

```python
# tests/test_task_manager.py

def test_task_stream_snapshot_includes_explicit_progress_contract():
    ...
    assert snapshot["payload"]["task_progress"] == {
        "step_index": 2,
        "total_steps": 5,
        "progress_percent": 40,
    }


def test_task_step_updated_event_includes_explicit_progress_contract():
    ...
    assert events[-1]["kind"] == "task_step_updated"
    assert events[-1]["payload"]["task_progress"]["step_index"] == 2
    assert events[-1]["payload"]["task_progress"]["total_steps"] == 5
```

```python
# tests/test_registration_page_assets.py

def test_realtime_log_appended_event_updates_console_without_waiting_for_task_detail_refresh():
    result = run_app_js_scenario("single_task_log_event_immediate_append")
    assert result["rendered_log_count"] == 2
    assert result["last_rendered_contains_live_line"] is True
```

- [ ] **Step 2: 运行失败测试，确认当前没有显式 progress payload，且日志实时 contract 至少缺一项**

Run: `timeout 60s pytest tests/test_task_manager.py::test_task_stream_snapshot_includes_explicit_progress_contract tests/test_task_manager.py::test_task_step_updated_event_includes_explicit_progress_contract tests/test_registration_page_assets.py::test_realtime_log_appended_event_updates_console_without_waiting_for_task_detail_refresh -q`
Expected: FAIL

- [ ] **Step 3: 先做根因修复的最小实现，不允许前端再从“最近步骤”猜进度**

```python
# src/core/pipeline/runner.py
callback({
  "current_step": current_step_payload,
  "steps": steps,
  "task_progress": {
    "step_index": order,  # 1-based，需与“第 2 / 5 步”文案一致
    "total_steps": len(pipeline.steps),
    "progress_percent": int(order / len(pipeline.steps) * 100),  # 最后一步必须稳定收敛到 100
    "elapsed_ms": self._duration_ms(pipeline_started_at, self._utc_now()),
  },
})
```

```python
# src/application/registration_service.py
service.task_manager.set_task_steps(
    task_uuid,
    steps,
    task_progress=payload.get("task_progress"),
)
```

```python
# src/web/task_manager.py
"payload": {
  "task": task_snapshot,
  "current_step": current_step,
  "steps": steps,
  "task_progress": task_progress,
  "logs_tail": logs_tail,
}
```

```javascript
// static/js/registration_stream.js
case 'task_step_updated':
  return {
    ...currentState,
    currentStep: ...,
    steps: ...,
    taskProgress: event.payload ? event.payload.task_progress : currentState.taskProgress,
  };
```

- [ ] **Step 4: 再跑实时/契约测试，确认日志追加和 progress payload 都成立**

Run: `timeout 60s pytest tests/test_task_manager.py tests/test_registration_stream_routes.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_page_assets.py -q`
Expected: PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add src/core/pipeline/runner.py src/application/registration_service.py src/application/batch_registration_service.py src/web/task_manager.py static/js/registration_stream.js static/js/app.js tests/test_task_manager.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_stream_routes.py tests/test_registration_page_assets.py tests_runtime/app_js_harness.py
git commit -m "fix: stabilize realtime log and task progress payloads"
```

### Task 4: 注册工作台改成单任务进度条模式，并拉高日志区

**Files:**
- Modify: `templates/index.html`
- Modify: `static/css/registration_workbench.css`
- Modify: `static/js/app.js`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定单任务改为 progress summary card，而不是步骤瀑布主视图**

```python
# tests/test_registration_page_assets.py

def test_app_js_renders_single_task_progress_summary_instead_of_waterfall_primary_view():
    result = run_app_js_scenario("single_task_progress_summary")
    assert result["progress_step_text"] == "第 2 / 5 步"
    assert result["progress_current_step"] == "submit_login_email"
    assert result["progress_elapsed_text"] == "00:12"
    assert result["progress_bar_width"] == "40%"
```

- [ ] **Step 2: 运行失败测试，确认当前仍渲染 waterfall 列表主视图**

Run: `timeout 60s pytest tests/test_registration_page_assets.py::test_app_js_renders_single_task_progress_summary_instead_of_waterfall_primary_view -q`
Expected: FAIL

- [ ] **Step 3: 最小实现单任务进度卡和日志面板高度增强**

```html
<!-- templates/index.html -->
<section id="registration-single-progress" ...>
  <div id="single-progress-current-step"></div>
  <div id="single-progress-step-text"></div>
  <div id="single-progress-elapsed"></div>
  <div class="progress"><div id="single-progress-bar"></div></div>
</section>
```

```css
.feedback-panel-log { min-height: 420px; }
.single-progress-card { ... }
```

- [ ] **Step 4: 跑注册页面资产 / harness 测试**

Run: `timeout 60s pytest tests/test_registration_page_assets.py -k 'progress or registration' -q`
Expected: PASS

- [ ] **Step 5: 提交 Task 4**

```bash
git add templates/index.html static/css/registration_workbench.css static/js/app.js tests/test_registration_page_assets.py tests_runtime/app_js_harness.py
git commit -m "feat: render single task progress summary card"
```

### Task 5: 为所有任务类型实现统一的 `use_proxy` 策略，并在无代理可用时创建后立即失败

**Files:**
- Modify: `src/application/proxy_dispatch_service.py`
- Modify: `src/application/registration_service.py`
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/web/routes/registration.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_proxy_dispatch_service.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_batch_routes.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests_runtime/app_js_harness.py`

- [ ] **Step 1: 写失败测试，锁定 `use_proxy` 关闭时完全无代理、开启时按“动态 -> 代理列表 -> 静态 -> 失败”顺序决策**

```python
# tests/test_proxy_dispatch_service.py

def test_resolve_single_candidates_prefers_dynamic_then_pool_then_static_when_use_proxy_enabled():
    ...
    assert [item.source for item in candidates] == ["dynamic_pool", "proxy_list", "static"]


def test_resolve_single_candidates_returns_empty_when_use_proxy_disabled():
    ...
    assert candidates == []
```

```python
# tests/test_registration_service.py

def test_registration_service_marks_task_failed_after_creation_when_use_proxy_enabled_but_no_proxy_available(...):
    ...
    assert result.task.status == "failed"
    assert "代理已启用" in result.task.error_message
    assert any("代理已启用" in item["payload"]["message"] for item in stream_events)
```

- [ ] **Step 2: 运行失败测试，确认当前 `explicit_proxy` 仍会直接覆盖动态代理优先级**

Run: `timeout 60s pytest tests/test_proxy_dispatch_service.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py -k 'proxy' -q`
Expected: FAIL

- [ ] **Step 3: 最小实现统一代理决策与请求体字段**

```python
# src/web/routes/registration.py
class RegistrationTaskCreate(BaseModel):
    use_proxy: bool = False
    proxy: Optional[str] = None  # 仍代表静态代理/手动代理


class BatchRegistrationRequest(BaseModel):
    use_proxy: bool = False
    ...


class OutlookBatchRegistrationRequest(BaseModel):
    use_proxy: bool = False
    ...
```

```python
# src/application/proxy_dispatch_service.py
if not use_proxy:
    return []
# 有动态代理 => 动态优先
# 否则代理列表
# 最后 static_proxy_provider()
```

```javascript
// static/js/app.js
requestData.use_proxy = !!elements.useProxy?.checked;
requestData.proxy = requestData.use_proxy ? (elements.proxy?.value || null) : null;
```

- [ ] **Step 4: 跑代理相关测试，确认所有任务类型和失败语义一致**

Run: `timeout 60s pytest tests/test_proxy_dispatch_service.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_registration_page_assets.py -q`
Expected: PASS

- [ ] **Step 5: 提交 Task 5**

```bash
git add src/application/proxy_dispatch_service.py src/application/registration_service.py src/application/batch_registration_service.py src/web/routes/registration.py templates/index.html static/js/app.js tests/test_proxy_dispatch_service.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_registration_page_assets.py tests_runtime/app_js_harness.py
git commit -m "feat: add unified use-proxy policy across registration flows"
```

### Task 6: 最终联调、样式收口与回归验证

**Files:**
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests/test_workspace_shell_assets.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`
- Modify: `static/css/dashboard_page.css`
- Modify: `static/css/registration_workbench.css`
- Modify: `static/css/style.css`

- [ ] **Step 1: 补最后一组回归测试，锁定普通批量 / Outlook 批量 / 单任务在新 UI 下都不回退到旧 contract**

```python
# tests/test_registration_page_assets.py

def test_registration_template_contains_use_proxy_control_and_single_progress_hooks():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="use-proxy"' in template
    assert 'id="single-progress-current-step"' in template
    assert 'id="single-progress-bar"' in template
```

- [ ] **Step 2: 跑完整相关回归套件**

Run: `timeout 60s pytest tests/test_dashboard_page_assets.py tests/test_workspace_shell_assets.py tests/test_task_manager.py tests/test_registration_stream_routes.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_registration_page_assets.py tests/test_proxy_dispatch_service.py tests/test_static_asset_versioning.py -q`
Expected: PASS

- [ ] **Step 3: 跑全量 tests 分片验证（如单条 `pytest -q` 可能超时，则按既有 60s 分片策略执行）**

Run example:

```bash
timeout 60s pytest tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py tests/test_task_manager.py tests/test_registration_stream_routes.py -q
```

以及剩余 tests 分片直至全部完成。

- [ ] **Step 4: 提交 Task 6**

```bash
git add static/css/dashboard_page.css static/css/registration_workbench.css static/css/style.css tests/test_dashboard_page_assets.py tests/test_workspace_shell_assets.py tests/test_registration_page_assets.py tests/test_static_asset_versioning.py
git commit -m "test: finalize dashboard workbench polish regression coverage"
```
