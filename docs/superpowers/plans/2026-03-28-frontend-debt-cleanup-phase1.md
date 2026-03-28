# Frontend Debt Cleanup Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理当前 main 上最明显的前端遗留资产与结构债，优先消除低风险旧代码、隐式全局依赖和内联事件/内联样式热点，同时不触碰高风险注册运行生命周期逻辑。

**Architecture:** 这轮只做“低风险高收益”的页面壳层与前端组织清理，不改后端 API 契约，不重写 registration runtime。实现策略分三层推进：先移除确认未使用的页面资产，再把 `scheduled_tasks` / `payment` 从内联事件迁移到显式事件绑定，最后补页面级 CSS 与测试护栏，避免旧模式回流。

**Tech Stack:** FastAPI + Jinja2 templates + vanilla JavaScript + pytest + TestClient + JS harness（Node/vm 风格）

---

## Scope / Non-Goals

- **In scope**
  - 清理 `scheduled-tasks` 页面确认未使用的旧资产
  - 收敛 `scheduled_tasks.js` 的 `window.*` 导出与字符串内联事件
  - 收敛 `payment.html` 的 `onclick/onchange` 与裸 `fetch`
  - 把两页最明显的 inline style 抽到页面 CSS / shared CSS
  - 用测试锁住“无旧模式回流”

- **Out of scope**
  - 不拆 `static/js/app.js`
  - 不改 `registration_service.py / batch_registration_service.py / task_manager.py` 的运行生命周期
  - 不全量重写 `settings.js`
  - 不在本轮统一所有页面的 API 调用风格，只覆盖本轮触达页面

## File Map

**Likely modify:**
- `templates/scheduled_tasks.html` — 移除未使用资产、去掉可替换的 inline style hook、给事件委托留稳定 data-* 标记
- `templates/payment.html` — 去掉 inline 事件、补稳定的 id/data-* hook
- `static/js/scheduled_tasks.js` — 用事件委托替换 HTML 字符串里的 `onclick/onchange`，缩减 `window.*` 暴露
- `static/js/payment.js` — 用显式事件绑定替换模板 inline 事件；用 `api` 客户端替代裸 `fetch`
- `static/css/run_center.css` or `static/css/workspace_components.css` — 若 `scheduled-tasks` 需要新的复用类，优先放共享层
- `static/css/support_pages.css` or new page CSS file if needed — 收敛 `payment` / `scheduled-tasks` 的明显 inline style
- `tests/test_scheduled_tasks_page_assets.py` — 资产与结构断言
- `tests/test_run_center_page_assets.py` — 保留运行中心资产基线，防止误删共享依赖
- `tests/test_static_asset_versioning.py` — 锁定页面资产版本化及依赖顺序
- `tests/test_support_pages_assets.py` — 支撑页模板基线
- `tests_runtime/scheduled_tasks_js_harness.py` — 新建，验证无 inline handler 也能触发计划操作/配置编辑
- `tests_runtime/payment_js_harness.py` — 新建，验证 payment 页面显式绑定和 `api` 调用路径
- `tests/test_payment_page_assets.py` — 新建，锁定 payment 页面无 inline handler、依赖 `utils.js`

**Must stay untouched this phase:**
- `src/application/registration_service.py`
- `src/application/batch_registration_service.py`
- `src/application/registration_runs_service.py`
- `src/web/task_manager.py`

---

### Task 1: 移除 `scheduled-tasks` 已确认未使用的旧资产

**Files:**
- Modify: `templates/scheduled_tasks.html`
- Modify: `tests/test_scheduled_tasks_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`
- Verify: `tests/test_run_center_page_assets.py`

- [ ] **Step 1: 写失败测试，证明 `scheduled-tasks` 不再需要 realtime log 样式**

在 `tests/test_scheduled_tasks_page_assets.py` 增加断言：

```python
def test_scheduled_tasks_template_does_not_load_realtime_log_console_assets():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert "/static/css/realtime_log_console.css?v=" not in template
```

并在 `tests/test_static_asset_versioning.py` 里去掉对 `/scheduled-tasks` 页面 `realtime_log_console.css` 的依赖断言。

- [ ] **Step 2: 跑测试，确认当前会失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_static_asset_versioning.py -q
```

Expected: 至少 1 个 FAIL，指出 `scheduled_tasks.html` 仍加载 `realtime_log_console.css`。

- [ ] **Step 3: 做最小实现**

从 `templates/scheduled_tasks.html` 的 `head_extra` 中删除：

```html
<link rel="stylesheet" href="{{ '/static/css/realtime_log_console.css?v=' ~ static_version }}">
```

不要动 `run-center` 页面，因为运行中心仍然需要日志控制台能力。

- [ ] **Step 4: 重新跑测试并确认通过**

Run same command as Step 2.

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add templates/scheduled_tasks.html \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_static_asset_versioning.py

git commit -m "refactor: drop unused scheduled tasks log asset"
```

---

### Task 2: 把 `scheduled_tasks.js` 从 inline handler 迁移到显式事件委托

**Files:**
- Modify: `templates/scheduled_tasks.html`
- Modify: `static/js/scheduled_tasks.js`
- Create: `tests_runtime/scheduled_tasks_js_harness.py`
- Modify: `tests/test_scheduled_tasks_page_assets.py`
- Create: `tests/test_scheduled_tasks_js_behavior.py`

- [ ] **Step 1: 先写失败测试，锁定“页面脚本不再依赖 inline onclick/onchange”**

在 `tests/test_scheduled_tasks_page_assets.py` 增加结构断言：

```python
def test_scheduled_tasks_template_has_no_inline_event_handlers():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert "onclick=" not in template
    assert "onchange=" not in template
```

在 `tests/test_scheduled_tasks_js_behavior.py` 新增 harness 场景断言：

```python
def test_scheduled_tasks_delegated_plan_actions_still_work_without_inline_handlers():
    result = run_scheduled_tasks_js_scenario("delegated_plan_action_run_now")
    assert result["api_post_paths"] == ["/scheduled-plans/42/run"]
```

再增加配置编辑器场景：

```python
def test_scheduled_tasks_delegated_config_input_updates_entry_value():
    result = run_scheduled_tasks_js_scenario("delegated_config_value_change")
    assert result["updated_value"] == "12"
```

- [ ] **Step 2: 跑测试，确认当前失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_scheduled_tasks_js_behavior.py -q
```

Expected: FAIL，因为当前 `scheduled_tasks.js` 仍在 HTML 字符串中写 `onclick/onchange`，且没有 harness。

- [ ] **Step 3: 写最小 harness**

在 `tests_runtime/scheduled_tasks_js_harness.py` 模拟：

- `document.getElementById`
- `api.get/post/put`
- `toast`
- `window.runCenterShared`
- `DOMContentLoaded`
- 表格体和配置编辑器 body 的事件派发

至少支持两个场景：
- `delegated_plan_action_run_now`
- `delegated_config_value_change`

- [ ] **Step 4: 在 `scheduled_tasks.js` 中用事件委托替换字符串 handler**

把类似：

```js
onclick="handlePlanAction(this)"
onchange="handleConfigEntryInput(this)"
```

改成输出纯 data 属性：

```html
<button data-action="run-now" data-plan-id="42">
<input data-config-index="0" data-config-field="rawValue">
```

再在脚本里新增统一绑定：

```js
function bindPlanTableEvents() {
  scheduledTaskElements.plansBody?.addEventListener('click', (event) => {
    const actionButton = event.target.closest('[data-action][data-plan-id]');
    if (!actionButton) return;
    void handlePlanAction(actionButton);
  });
}

function bindConfigEditorEvents() {
  scheduledTaskElements.planConfigEntriesBody?.addEventListener('change', (event) => {
    const input = event.target.closest('[data-config-index][data-config-field]');
    if (!input) return;
    handleConfigEntryInput(input);
  });

  scheduledTaskElements.planConfigEntriesBody?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-config-action][data-config-index]');
    if (!button) return;
    handleConfigEntryAction(button);
  });
}
```

- [ ] **Step 5: 缩减 `window.*` 暴露到最小集合**

优先保留真正跨模板调用需要的极少数公共 API；若模板已完全无 inline handler，则删掉：

```js
window.handlePlanAction = handlePlanAction;
window.handleConfigEntryInput = handleConfigEntryInput;
window.handleConfigEntryAction = handleConfigEntryAction;
```

只有测试、外链或重试按钮确实需要的再保留。

- [ ] **Step 6: 跑测试验证行为通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_scheduled_tasks_js_behavior.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add templates/scheduled_tasks.html \
  static/js/scheduled_tasks.js \
  tests_runtime/scheduled_tasks_js_harness.py \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_scheduled_tasks_js_behavior.py

git commit -m "refactor: delegate scheduled task page actions"
```

---

### Task 3: 清理 `payment` 页面的 inline 事件与裸 `fetch`

**Files:**
- Modify: `templates/payment.html`
- Modify: `static/js/payment.js`
- Create: `tests_runtime/payment_js_harness.py`
- Create: `tests/test_payment_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`
- Modify: `tests/test_support_pages_assets.py`

- [ ] **Step 1: 写失败测试，锁定 payment 页面不再允许 inline 事件**

新增 `tests/test_payment_page_assets.py`：

```python
from pathlib import Path
from tests_runtime.payment_js_harness import run_payment_js_scenario


def test_payment_template_has_no_inline_event_handlers():
    template = Path("templates/payment.html").read_text(encoding="utf-8")
    assert "onclick=" not in template
    assert "onchange=" not in template


def test_payment_js_binds_plan_switch_country_change_and_submit_actions():
    result = run_payment_js_scenario("event_binding_matrix")
    assert result["selected_plan"] == "team"
    assert result["currency"] == "USD"
    assert result["api_post_paths"] == ["/payment/generate-link"]
```

- [ ] **Step 2: 跑测试确认当前失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_payment_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py -q
```

Expected: FAIL，因为模板仍有 `onclick/onchange`，JS 也直接用裸 `fetch`。

- [ ] **Step 3: 用显式事件绑定替换模板 inline 事件**

`templates/payment.html` 改成只保留稳定 hook：

```html
<div class="plan-card" id="plan-team" data-plan="team"></div>
<select id="country-select"></select>
<button class="btn btn-primary" id="generate-link-btn">生成支付链接</button>
<button class="btn btn-secondary" id="copy-link-btn">复制链接</button>
<button class="btn btn-primary" id="open-incognito-btn">无痕打开浏览器</button>
```

`payment.js` 在 `DOMContentLoaded` 中统一绑定：

```js
document.getElementById('plan-team')?.addEventListener('click', () => selectPlan('team'));
document.getElementById('country-select')?.addEventListener('change', onCountryChange);
document.getElementById('generate-link-btn')?.addEventListener('click', generateLink);
```

- [ ] **Step 4: 把 `payment.js` 的裸 `fetch` 收敛为 `api` 客户端**

把：

```js
const resp = await fetch('/api/payment/generate-link', { ... })
```

收敛为：

```js
const data = await api.post('/payment/generate-link', body)
```

同理处理：
- `/api/accounts?page=1&page_size=100&status=active`
- `/api/payment/open-incognito`

保留 `blob` 或特殊响应时，若必须继续用 `fetch`，要在测试里注明这是“下载/非 JSON 特例”。但当前 payment 页面三个请求都可走 `api`。

- [ ] **Step 5: 写/补 harness 验证事件与请求路径**

`tests_runtime/payment_js_harness.py` 至少覆盖：
- 点击套餐卡切换选中态
- 国家切换更新币种
- 点击“生成支付链接”走 `api.post('/payment/generate-link', ...)`
- 点击“无痕打开浏览器”走 `api.post('/payment/open-incognito', ...)`

- [ ] **Step 6: 跑测试并确认通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_payment_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add templates/payment.html \
  static/js/payment.js \
  tests_runtime/payment_js_harness.py \
  tests/test_payment_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py

git commit -m "refactor: remove inline payment page handlers"
```

---

### Task 4: 抽离 `scheduled-tasks` / `payment` 的明显 inline style，建立页面级样式护栏

**Files:**
- Modify: `templates/scheduled_tasks.html`
- Modify: `templates/payment.html`
- Modify: `static/css/run_center.css` and/or `static/css/workspace_components.css`
- Create or Modify: page-specific CSS file for payment if absent
- Modify: `tests/test_support_pages_assets.py`
- Modify: `tests/test_scheduled_tasks_page_assets.py`
- Modify: `tests/test_payment_page_assets.py`

- [ ] **Step 1: 写失败测试，锁定两页关键区域不再使用 inline style**

示例断言：

```python
def test_scheduled_tasks_template_reduces_inline_style_hotspots():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'style="max-width: 1080px;"' not in template
    assert 'style="display:none;"' not in template
```

```python
def test_payment_template_reduces_inline_style_hotspots():
    template = Path("templates/payment.html").read_text(encoding="utf-8")
    assert 'style="width:100%"' not in template
```

- [ ] **Step 2: 跑测试确认失败**

Run targeted page-asset tests.

- [ ] **Step 3: 抽成命名类，不在模板里写布局值**

示例：

```html
<div class="scheduled-plan-modal-content"></div>
<div class="payment-account-select-shell"></div>
<input class="payment-currency-readonly" ...>
```

并在 CSS 中定义：

```css
.scheduled-plan-modal-content { max-width: 1080px; }
.payment-account-select-shell { width: 100%; }
.payment-currency-readonly { background: var(--surface-hover); cursor: default; }
```

- [ ] **Step 4: 跑测试确认通过**

Run relevant asset tests.

- [ ] **Step 5: 提交**

```bash
git add templates/scheduled_tasks.html templates/payment.html \
  static/css/run_center.css static/css/workspace_components.css \
  tests/test_scheduled_tasks_page_assets.py tests/test_payment_page_assets.py \
  tests/test_support_pages_assets.py

git commit -m "refactor: extract support page inline styles"
```

---

### Task 5: 补回归护栏，防止旧模式回流

**Files:**
- Modify: `tests/test_scheduled_tasks_page_assets.py`
- Modify: `tests/test_payment_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`
- Modify: `tests/test_support_pages_assets.py`

- [ ] **Step 1: 增加“旧模式禁入”断言**

至少锁住：
- `scheduled_tasks.html` 不再加载未使用的 `realtime_log_console.css`
- `scheduled_tasks.html` / `payment.html` 不再含 `onclick=` / `onchange=`
- `payment.html` 必须先加载 `utils.js`
- `scheduled_tasks.js` 不再导出仅供 inline handler 使用的多余 `window.*`

- [ ] **Step 2: 跑聚合回归**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_payment_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py -q
```

Expected: 全绿。

- [ ] **Step 3: 跑受影响的 JS harness 回归**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_js_behavior.py \
  tests/test_payment_page_assets.py -q
```

- [ ] **Step 4: 提交**

```bash
git add tests/test_scheduled_tasks_page_assets.py \
  tests/test_payment_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py

git commit -m "test: guard against support page legacy patterns"
```

---

## Final Verification

实施完全部任务后，统一验证：

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_scheduled_tasks_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py \
  tests/test_payment_page_assets.py \
  tests/test_scheduled_tasks_js_behavior.py -q
```

再做 Git 收尾检查：

```bash
git status --short
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected:
- 测试全绿
- 工作区只包含本轮文件
- 推送后 `HEAD == origin/main`

## Notes for the Implementer

- 这轮**不要顺手动** `app.js`、`settings.js`、`registration_service.py` 的深层结构；它们应该单独成下一轮 plan。
- 如果在 `payment.js` 的某个请求上发现 `api` 客户端不支持当前响应模式，先加最小测试再决定是否保留 `fetch` 特例；不要混用两套风格而不解释。
- 如果 `scheduled_tasks.js` 去掉 inline handler 后仍需要极少数 `window.*` 暴露（例如测试或跨页 bridge），必须把保留原因写进测试名或注释里。
