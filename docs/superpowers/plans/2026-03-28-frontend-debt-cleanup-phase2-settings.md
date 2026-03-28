# Frontend Debt Cleanup Phase 2 Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 继续清理当前 main 的前端结构债，优先收敛 `settings` 页中最明显的字符串事件处理、模板内联样式和缺失的页面级测试护栏。

**Architecture:** 本轮不触碰后端接口和业务流程，只处理 `settings` 页面的壳层结构债。先把 `settings.js` 中服务列表/黑名单/代理列表等区域的字符串 `onclick/onchange` 迁移到事件委托，再把 `settings.html` 中高频重复的 inline style 抽成命名类，最后补资产测试与 JS harness，防止旧模式回流。

**Tech Stack:** FastAPI + Jinja2 templates + vanilla JavaScript + pytest + TestClient + JS harness（Node/vm）

---

## Scope / Non-Goals

- **In scope**
  - 清理 `settings.js` 中最明显的字符串事件处理
  - 抽离 `settings.html` 中高频 inline style 热点
  - 新增 `settings` 页的页面资产与行为测试
  - 建立 `settings` 页“禁止回到 inline handler”护栏

- **Out of scope**
  - 不改 `/api/settings/*` 后端接口
  - 不重构整个 `settings.js` 为多文件
  - 不在本轮处理 `accounts.js` / `app.js`
  - 不全量处理 `settings.html` 所有表头宽度 style，只先处理高频布局/状态类样式

## File Map

**Likely modify:**
- `templates/settings.html` — 去掉高频布局 inline style，补稳定 class hook
- `static/js/settings.js` — 用事件委托替换服务列表/黑名单/代理列表中的字符串 `onclick/onchange`
- `static/css/workspace_components.css` or page-local CSS block in `settings.html` — 添加 `settings` 页缺失的命名类
- `tests/test_static_asset_versioning.py` — 确保 `settings` 依赖资产顺序不回退
- `tests/test_settings_page_assets.py` — 新建，锁定 `settings` 页结构和“无 inline handler”约束
- `tests_runtime/settings_js_harness.py` — 新建，验证委托事件与关键 API 路径
- `tests/test_settings_js_behavior.py` — 新建，行为层回归

**Must stay untouched this phase:**
- `src/web/routes/settings.py`
- `src/services/*`
- `src/application/*`

---

### Task 1: 给 `settings` 页补页面级资产与结构护栏

**Files:**
- Create: `tests/test_settings_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 写失败测试，锁定 `settings` 依赖和结构边界**

新增 `tests/test_settings_page_assets.py`，至少覆盖：

```python
def test_settings_page_renders_and_loads_utils_before_page_script():
    ...
    assert "/static/js/utils.js?v=" in response.text
    assert "/static/js/settings.js?v=" in response.text
    assert response.text.index("/static/js/utils.js?v=") < response.text.index("/static/js/settings.js?v=")
```

```python
def test_settings_template_has_no_inline_event_handlers_in_template_layer():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert "onclick=" not in template
    assert "onchange=" not in template
```

```python
def test_settings_template_reduces_high_frequency_inline_style_hotspots():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'style="display: flex; justify-content: space-between; align-items: center; gap: var(--spacing-sm); flex-wrap: wrap;"' not in template
    assert 'style="margin-top: var(--spacing-lg);"' not in template
```

- [ ] **Step 2: 跑测试确认红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_settings_page_assets.py \
  tests/test_static_asset_versioning.py -q
```

Expected: FAIL，指出 `settings.html` 仍存在高频 inline style。

- [ ] **Step 3: 仅补最小实现需要的测试辅助**

如果 `test_static_asset_versioning.py` 对 `settings` 页只检查版本化，不需要修改逻辑；只在必要时补顺序断言。

- [ ] **Step 4: 重新跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add tests/test_settings_page_assets.py tests/test_static_asset_versioning.py

git commit -m "test: add settings page asset guards"
```

---

### Task 2: 迁移 `settings.js` 服务列表与黑名单区的字符串事件到事件委托

**Files:**
- Modify: `static/js/settings.js`
- Create: `tests_runtime/settings_js_harness.py`
- Create: `tests/test_settings_js_behavior.py`
- Modify: `tests/test_settings_page_assets.py`

- [ ] **Step 1: 写失败测试，锁定 JS 不再输出字符串事件**

在 `tests/test_settings_page_assets.py` 增加：

```python
def test_settings_script_avoids_inline_event_markup_for_service_tables():
    script = Path("static/js/settings.js").read_text(encoding="utf-8")
    assert "onclick=" not in script
    assert "onchange=" not in script
```

在 `tests/test_settings_js_behavior.py` 增加至少两个 harness 场景：

```python
def test_settings_delegated_custom_service_actions_still_work():
    result = run_settings_js_scenario("delegated_custom_service_test")
    assert result["api_post_paths"] == ["/email-services/7/test"]
```

```python
def test_settings_delegated_blacklist_actions_still_work():
    result = run_settings_js_scenario("delegated_blacklist_toggle")
    assert result["api_patch_paths"] == ["/settings/email-suffix-blacklist/12"]
```

- [ ] **Step 2: 跑测试确认红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_settings_page_assets.py \
  tests/test_settings_js_behavior.py -q
```

Expected: FAIL，因为 `settings.js` 当前仍拼出大量 `onclick/onchange`。

- [ ] **Step 3: 新建最小 harness**

`tests_runtime/settings_js_harness.py` 至少模拟：
- `document.getElementById`
- `api.get/post/patch/delete`
- `toast`
- `DOMContentLoaded`
- 服务列表表格和黑名单表格的 click/change 委托

- [ ] **Step 4: 在 `settings.js` 中收敛以下区域到事件委托**

优先处理这几块：
- 自定义邮箱服务列表
- 邮箱后缀黑名单列表
- Team Manager / CPA / Sub2API 服务列表

把 HTML 字符串中的：

```js
onclick="testService(${service.id})"
onclick="toggleService(${service.id}, ${!service.enabled})"
```

替换为纯 data 属性：

```html
<button data-service-action="test" data-service-id="7"></button>
<button data-service-action="toggle" data-service-id="7" data-next-enabled="false"></button>
```

并新增统一委托入口，例如：

```js
function bindSettingsDelegatedTableEvents() {
  elements.emailServicesTable?.addEventListener('click', handleSettingsDelegatedClick);
  elements.emailSuffixBlacklistTable?.addEventListener('click', handleSettingsDelegatedClick);
  elements.tmServicesTable?.addEventListener('click', handleSettingsDelegatedClick);
  elements.cpaServicesTable?.addEventListener('click', handleSettingsDelegatedClick);
  elements.sub2ApiServicesTable?.addEventListener('click', handleSettingsDelegatedClick);
}
```

- [ ] **Step 5: 跑测试确认通过**

- [ ] **Step 6: 提交**

```bash
git add static/js/settings.js \
  tests_runtime/settings_js_harness.py \
  tests/test_settings_page_assets.py \
  tests/test_settings_js_behavior.py

git commit -m "refactor: delegate settings table actions"
```

---

### Task 3: 抽离 `settings.html` 高频布局 inline style

**Files:**
- Modify: `templates/settings.html`
- Modify: `static/css/workspace_components.css` or page-local style block
- Modify: `tests/test_settings_page_assets.py`

- [ ] **Step 1: 写失败测试，限定只清理高频布局类 inline style**

锁定以下模式先被移除：
- `style="margin-top: var(--spacing-lg);"`
- 大段 `display:flex; justify-content: space-between; align-items: center; gap: ...`
- 代理筛选栏上重复的 `margin:0; min-width:...`
- `card-body` 的 `padding: 0`

不要把所有表头宽度 style 一次性纳入，避免范围失控。

- [ ] **Step 2: 跑测试确认红灯**

- [ ] **Step 3: 抽成命名类**

建议最先补这些类：

```css
.settings-section-stack { margin-top: var(--spacing-lg); }
.settings-card-body--flush { padding: 0; }
.settings-toolbar-row { display: flex; justify-content: space-between; align-items: center; gap: var(--spacing-sm); flex-wrap: wrap; }
.settings-filter-form { margin-top: var(--spacing-md); display: flex; gap: var(--spacing-sm); flex-wrap: wrap; align-items: end; }
.settings-filter-field { margin: 0; }
```

然后替换模板中的重复布局 style。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add templates/settings.html static/css/workspace_components.css tests/test_settings_page_assets.py

git commit -m "refactor: extract settings layout inline styles"
```

---

### Task 4: 跑聚合回归，锁住 Phase 2 边界

**Files:**
- Modify: `tests/test_settings_page_assets.py`
- Modify: `tests/test_settings_js_behavior.py`
- Verify: `tests/test_static_asset_versioning.py`
- Verify: `tests/test_support_pages_assets.py`

- [ ] **Step 1: 增加回归护栏**

至少锁住：
- `settings.html` 模板层无 inline 事件
- `settings.js` 不再输出本轮目标区域的 `onclick/onchange`
- `settings` 页继续先加载 `utils.js`
- 委托事件仍能命中关键 API 路径

- [ ] **Step 2: 跑聚合验证**

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_settings_page_assets.py \
  tests/test_settings_js_behavior.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py -q
```

Expected: 全绿。

- [ ] **Step 3: 提交**

```bash
git add tests/test_settings_page_assets.py tests/test_settings_js_behavior.py \
  tests/test_static_asset_versioning.py tests/test_support_pages_assets.py

git commit -m "test: guard settings page legacy patterns"
```

---

## Final Verification

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_settings_page_assets.py \
  tests/test_settings_js_behavior.py \
  tests/test_static_asset_versioning.py \
  tests/test_support_pages_assets.py -q
```

再检查：

```bash
git status --short
git log --oneline -5
```

Expected:
- 测试全绿
- 只包含本轮 `settings` 相关改动

## Notes for the Implementer

- 这轮优先处理 `settings.js` 里**服务表格和黑名单**的字符串事件，不要一次性扫掉所有菜单/弹窗逻辑，避免范围炸开。
- 如果代理列表的“更多”下拉菜单事件委托改动过大，可延后到 Phase 2B，先把最易验证的表格动作做完。
- 模板 inline style 只先抽离高频重复布局类，不要本轮就把所有 `<th style="width: ...">` 全量替换。
