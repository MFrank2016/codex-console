# 邮箱后缀黑名单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为注册链路增加邮箱后缀黑名单能力，在命中 `registration_disallowed` 时自动拉黑后缀、同任务整轮重试，并在设置页提供黑名单 CRUD 管理。

**Architecture:** 采用“先核心域能力、再设置接口与前端、最后注册链路接入”的纵切方案。先新增后缀规范化工具、独立黑名单表与 CRUD，再补设置页 API 和 UI 管理能力，最后把 `RegistrationEngine`、`run_registration_job` 和 `codexgen` fallback 接入黑名单判定与自动重试，让当前流水线和 `codexgen_pipeline` 都共享同一套治理逻辑。

**Tech Stack:** SQLAlchemy ORM、FastAPI、Pydantic v2、Jinja2、vanilla JS、pytest、现有 registration/settings/application service 结构。

---

## Spec Reference

- `docs/superpowers/specs/2026-03-27-email-suffix-blacklist-design.md`

## Review Note

- 当前会话未获得用户对 reviewer/subagent 的显式授权，因此本计划按现有上下文本地自审后落盘；如后续用户明确授权，再补 reviewer 循环。

## Execution Notes

1. 所有测试命令统一带仓库要求的 `timeout 60s`。
2. 每个任务遵循严格 TDD：先补失败测试，再实现最小代码，再跑绿，再 commit。
3. 若某个测试集里已有无关基线失败，先单独定位并消除基线噪音，再继续当前任务。

---

## File Map

### Create

- `src/core/email_suffix_blacklist.py` — 后缀规范化、邮箱后缀提取、临时邮箱服务判定、`registration_disallowed` 专用异常。
- `tests/test_email_suffix_blacklist_core.py` — 黑名单核心工具、ORM/CRUD 业务方法测试。
- `tests/test_email_suffix_blacklist_routes.py` — 黑名单设置接口 CRUD/筛选/规范化测试。
- `tests/test_settings_email_blacklist_assets.py` — 设置页黑名单管理卡片、JS 场景与弹窗交互测试。
- `tests/test_registration_job.py` — `run_registration_job` 自动拉黑后整轮重试与重试上限测试。

### Modify

- `src/database/models.py` — 新增 `EmailSuffixBlacklist` 表。
- `src/database/crud.py` — 新增黑名单 CRUD 与业务方法。
- `src/web/routes/settings.py` — 增加黑名单接口与请求/响应模型。
- `templates/settings.html` — 在“注册配置”区域新增黑名单管理卡片与弹窗。
- `static/js/settings.js` — 增加黑名单列表加载、新增、编辑、启停、删除逻辑。
- `tests_runtime/settings_js_harness.py` — 增加设置页黑名单场景桩环境。
- `src/core/register.py` — 接入邮箱创建后黑名单检查、`registration_disallowed` 识别与共享建号失败解析。
- `src/core/pipeline/steps/codexgen.py` — 让 codexgen fallback 也能识别 `registration_disallowed`。
- `src/core/registration_job.py` — 增加自动拉黑后的整轮重试逻辑。
- `tests/test_registration_engine.py` — 覆盖邮箱创建黑名单跳过、建号阶段 `registration_disallowed` 识别。
- `tests/test_codexgen_pipeline.py` — 覆盖 codexgen fallback 触发共享禁止后缀错误。
- `tests/test_settings_service.py` — 如需要，补 settings 相关轻量回归（例如 route 依赖的分类字段或默认值）。

---

## Task 1: 建立邮箱后缀黑名单核心域能力

**Files:**
- Create: `src/core/email_suffix_blacklist.py`
- Create: `tests/test_email_suffix_blacklist_core.py`
- Modify: `src/database/models.py`
- Modify: `src/database/crud.py`

- [ ] **Step 1: 先写失败测试，锁定后缀规范化与 upsert 语义**

在 `tests/test_email_suffix_blacklist_core.py` 先增加最小失败测试，覆盖：

```python
def test_normalize_email_suffix_strips_at_sign_and_lowercases():
    assert normalize_email_suffix(" @BadMail.COM ") == "badmail.com"


def test_extract_email_suffix_returns_none_for_invalid_email():
    assert extract_email_suffix("not-an-email") is None


def test_upsert_auto_blacklist_suffix_reenables_existing_row_and_increments_hit_count(temp_db):
    row = crud.create_email_suffix_blacklist(
        temp_db,
        suffix="badmail.com",
        enabled=False,
        source="manual",
        reason="manual seed",
    )

    updated = crud.upsert_auto_blacklist_suffix(
        temp_db,
        " @BadMail.COM ",
        reason="registration_disallowed",
        source="auto_registration_disallowed",
    )

    assert updated.id == row.id
    assert updated.enabled is True
    assert updated.hit_count == 1
    assert updated.source == "auto_registration_disallowed"
    assert updated.last_hit_at is not None
```

再补一个命中查询测试：

```python
def test_is_email_suffix_blacklisted_only_matches_enabled_rows(temp_db):
    crud.create_email_suffix_blacklist(temp_db, suffix="blocked.example", enabled=True)
    crud.create_email_suffix_blacklist(temp_db, suffix="disabled.example", enabled=False)

    assert crud.is_email_suffix_blacklisted(temp_db, "blocked.example") is True
    assert crud.is_email_suffix_blacklisted(temp_db, "disabled.example") is False
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s pytest tests/test_email_suffix_blacklist_core.py -q
```

Expected: FAIL，因为当前还没有 helper、模型和 CRUD 实现。

- [ ] **Step 3: 在 `models.py` 和 `crud.py` 中补齐最小持久化能力**

在 `src/database/models.py` 新增模型：

```python
class EmailSuffixBlacklist(Base):
    __tablename__ = "email_suffix_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    suffix = Column(String(255), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    source = Column(String(64), default="manual", nullable=False)
    reason = Column(Text)
    hit_count = Column(Integer, default=0, nullable=False)
    last_hit_at = Column(DateTime)
    created_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive)
```

在 `src/database/crud.py` 增加最小业务方法：

```python
def create_email_suffix_blacklist(db, *, suffix, enabled=True, source="manual", reason=None):
    ...


def list_email_suffix_blacklist(db, *, keyword=None, enabled=None, source=None):
    ...


def update_email_suffix_blacklist(db, row_id, **kwargs):
    ...


def delete_email_suffix_blacklist(db, row_id):
    ...


def is_email_suffix_blacklisted(db, suffix: str) -> bool:
    normalized = normalize_email_suffix(suffix)
    ...


def upsert_auto_blacklist_suffix(db, suffix: str, *, reason: str, source: str = "auto_registration_disallowed"):
    normalized = normalize_email_suffix(suffix)
    ...
```

- [ ] **Step 4: 在 `src/core/email_suffix_blacklist.py` 提供共享工具**

实现以下最小结构：

```python
TEMPORARY_EMAIL_BLACKLIST_SERVICE_TYPES = {
    "tempmail",
    "temp_mail",
    "duck_mail",
    "freemail",
    "moe_mail",
}


class RegistrationDisallowedSuffixError(RuntimeError):
    def __init__(self, *, email: str | None, suffix: str | None, detail: str):
        self.email = email
        self.suffix = suffix
        self.detail = detail
        super().__init__(detail)


def normalize_email_suffix(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def extract_email_suffix(email: str) -> str | None:
    text = str(email or "").strip()
    if "@" not in text:
        return None
    _, suffix = text.rsplit("@", 1)
    normalized = normalize_email_suffix(suffix)
    return normalized or None


def should_apply_email_suffix_blacklist(service_type: str | None) -> bool:
    return str(service_type or "").strip().lower() in TEMPORARY_EMAIL_BLACKLIST_SERVICE_TYPES
```

- [ ] **Step 5: 重跑测试，确认核心域能力变绿**

Run:

```bash
timeout 60s pytest tests/test_email_suffix_blacklist_core.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/core/email_suffix_blacklist.py src/database/models.py src/database/crud.py tests/test_email_suffix_blacklist_core.py
git commit -m "feat: add email suffix blacklist core"
```

---

## Task 2: 补齐设置接口与后端校验

**Files:**
- Create: `tests/test_email_suffix_blacklist_routes.py`
- Modify: `src/web/routes/settings.py`
- Modify: `src/database/crud.py`

- [ ] **Step 1: 先写失败测试，锁定设置接口 CRUD 行为**

在 `tests/test_email_suffix_blacklist_routes.py` 先写最小失败测试，覆盖：

```python
def test_email_suffix_blacklist_routes_support_crud_and_normalize_suffix():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/settings/email-suffix-blacklist",
            json={"suffix": "@BadMail.COM", "enabled": True, "reason": "manual add"},
        )
        assert create_response.status_code == 200
        created = create_response.json()["item"]
        assert created["suffix"] == "badmail.com"

        list_response = client.get("/api/settings/email-suffix-blacklist")
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1

        patch_response = client.patch(
            f"/api/settings/email-suffix-blacklist/{created['id']}",
            json={"enabled": False, "reason": "disabled"},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["item"]["enabled"] is False

        delete_response = client.delete(f"/api/settings/email-suffix-blacklist/{created['id']}")
        assert delete_response.status_code == 200
```

再补两个边界测试：

```python
def test_email_suffix_blacklist_route_rejects_full_email_value():
    ...
    assert response.status_code == 400


def test_email_suffix_blacklist_route_supports_keyword_and_enabled_filters():
    ...
    assert body["total"] == 1
```

- [ ] **Step 2: 运行接口测试，确认先红灯**

Run:

```bash
timeout 60s pytest tests/test_email_suffix_blacklist_routes.py -q
```

Expected: FAIL，因为当前 settings route 还没有对应接口和请求模型。

- [ ] **Step 3: 在 `src/web/routes/settings.py` 中增加黑名单 request/response model 与四个接口**

新增最小模型：

```python
class EmailSuffixBlacklistCreateRequest(BaseModel):
    suffix: str
    enabled: bool = True
    reason: str | None = None


class EmailSuffixBlacklistUpdateRequest(BaseModel):
    suffix: str | None = None
    enabled: bool | None = None
    reason: str | None = None
```

新增接口：

```python
@router.get("/email-suffix-blacklist")
async def list_email_suffix_blacklist(...):
    ...


@router.post("/email-suffix-blacklist")
async def create_email_suffix_blacklist_item(request: EmailSuffixBlacklistCreateRequest):
    ...


@router.patch("/email-suffix-blacklist/{row_id}")
async def update_email_suffix_blacklist_item(row_id: int, request: EmailSuffixBlacklistUpdateRequest):
    ...


@router.delete("/email-suffix-blacklist/{row_id}")
async def delete_email_suffix_blacklist_item(row_id: int):
    ...
```

校验规则：

1. 创建/更新前统一 `normalize_email_suffix(...)`
2. 若值为空，返回 `400`
3. 若输入看起来是完整邮箱（包含本地部分），返回 `400`
4. 重复后缀返回友好错误（`400` 或 `409`，本轮统一一种即可，但测试与实现要一致）

- [ ] **Step 4: 若 route 需要额外 CRUD 支持，补最小查询/序列化方法**

若 `crud.py` 尚未提供筛选与序列化支持，补齐：

```python
def get_email_suffix_blacklist_by_id(db, row_id): ...
def list_email_suffix_blacklist(db, *, keyword=None, enabled=None, source=None): ...
```

并为模型增加：

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "id": self.id,
        "suffix": self.suffix,
        "enabled": self.enabled,
        "source": self.source,
        "reason": self.reason,
        "hit_count": self.hit_count,
        "last_hit_at": self.last_hit_at.isoformat() if self.last_hit_at else None,
        "created_at": ...,
        "updated_at": ...,
    }
```

- [ ] **Step 5: 重跑接口测试，确认变绿**

Run:

```bash
timeout 60s pytest tests/test_email_suffix_blacklist_routes.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/web/routes/settings.py src/database/crud.py tests/test_email_suffix_blacklist_routes.py
git commit -m "feat: add email suffix blacklist settings api"
```

---

## Task 3: 完成设置页黑名单管理卡片与前端交互

**Files:**
- Create: `tests/test_settings_email_blacklist_assets.py`
- Modify: `templates/settings.html`
- Modify: `static/js/settings.js`
- Modify: `tests_runtime/settings_js_harness.py`

- [ ] **Step 1: 先写失败测试，锁定模板 hook 和 JS 行为**

在 `tests/test_settings_email_blacklist_assets.py` 先写最小失败测试，至少覆盖：

```python
def test_settings_template_contains_email_suffix_blacklist_management_hooks():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'id="email-suffix-blacklist-table"' in template
    assert 'id="add-email-suffix-blacklist-btn"' in template
    assert 'id="email-suffix-blacklist-modal"' in template


def test_settings_js_builds_blacklist_create_payload_with_normalized_suffix():
    result = run_settings_js_scenario("save_email_suffix_blacklist")
    assert result["post_path"] == "/settings/email-suffix-blacklist"
    assert result["payload"]["suffix"] == "badmail.com"


def test_settings_js_renders_blacklist_rows_with_toggle_and_delete_actions():
    result = run_settings_js_scenario("render_email_suffix_blacklist_rows")
    assert "toggleEmailSuffixBlacklistItem" in result["html"]
    assert "deleteEmailSuffixBlacklistItem" in result["html"]
```

- [ ] **Step 2: 运行前端资产测试，确认先红灯**

Run:

```bash
timeout 60s pytest tests/test_settings_email_blacklist_assets.py -q
```

Expected: FAIL，因为模板、JS 和 harness 还没有黑名单区块。

- [ ] **Step 3: 在 `settings.html` 中新增管理卡片与弹窗**

在“注册配置”tab 下新增一个卡片，至少包含：

```html
<div class="card" id="email-suffix-blacklist-card">
  <div class="card-header">
    <h3>邮箱后缀黑名单</h3>
    <button class="btn btn-primary btn-sm" id="add-email-suffix-blacklist-btn">+ 新增后缀</button>
  </div>
  <div class="card-body" style="padding: 0;">
    <div class="table-container table-shell">
      <table class="data-table">
        <tbody id="email-suffix-blacklist-table"></tbody>
      </table>
    </div>
  </div>
</div>
```

再增加弹窗：

```html
<div class="modal" id="email-suffix-blacklist-modal">
  ...
  <form id="email-suffix-blacklist-form">
    <input type="hidden" id="email-suffix-blacklist-id">
    <input type="text" id="email-suffix-blacklist-suffix">
    <input type="checkbox" id="email-suffix-blacklist-enabled">
    <textarea id="email-suffix-blacklist-reason"></textarea>
  </form>
</div>
```

- [ ] **Step 4: 在 `settings.js` 和 harness 中补齐最小 CRUD 交互**

在 `static/js/settings.js` 中新增：

```javascript
async function loadEmailSuffixBlacklist() { ... }
function renderEmailSuffixBlacklist(items) { ... }
function openEmailSuffixBlacklistModal(item = null) { ... }
async function handleSaveEmailSuffixBlacklist(e) { ... }
async function toggleEmailSuffixBlacklistItem(id, enabled) { ... }
async function deleteEmailSuffixBlacklistItem(id) { ... }
function normalizeEmailSuffixInput(value) {
  return String(value || '').trim().replace(/^@+/, '').toLowerCase();
}
```

在 `DOMContentLoaded` 和 `loadSettings()` 初始化逻辑中接上黑名单数据加载。

同步在 `tests_runtime/settings_js_harness.py` 导出这些函数，并增加场景：

```javascript
case 'save_email_suffix_blacklist': ...
case 'render_email_suffix_blacklist_rows': ...
```

- [ ] **Step 5: 重跑前端资产测试，确认变绿**

Run:

```bash
timeout 60s pytest tests/test_settings_email_blacklist_assets.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add templates/settings.html static/js/settings.js tests_runtime/settings_js_harness.py tests/test_settings_email_blacklist_assets.py
git commit -m "feat: add email suffix blacklist settings ui"
```

---

## Task 4: 把当前注册引擎接入黑名单拦截与禁止后缀错误

**Files:**
- Modify: `src/core/register.py`
- Modify: `src/core/email_suffix_blacklist.py`
- Modify: `tests/test_registration_engine.py`

- [ ] **Step 1: 先写失败测试，锁定邮箱创建阶段跳过黑名单与建号错误识别**

在 `tests/test_registration_engine.py` 先增加最小失败测试，覆盖：

```python
def test_create_email_retries_when_generated_suffix_is_blacklisted(monkeypatch, temp_db):
    ...
    assert payload["email"] == "usable@example.net"
    assert email_service.create_calls == 2


def test_create_user_account_raises_registration_disallowed_suffix_error(monkeypatch):
    ...
    with pytest.raises(RegistrationDisallowedSuffixError) as exc:
        engine._create_user_account()

    assert exc.value.suffix == "badmail.com"
```

其中第一条测试要覆盖：

1. 当前邮箱服务类型属于临时邮箱服务。
2. 第一次返回 `foo@blocked.example`
3. 黑名单命中后日志提示重新获取
4. 第二次返回 `bar@example.net`
5. `_create_email()` 最终成功

- [ ] **Step 2: 运行注册引擎测试，确认先红灯**

Run:

```bash
timeout 60s pytest tests/test_registration_engine.py -q
```

Expected: FAIL，因为当前 `_create_email()` 不会检查黑名单，`_create_user_account()` 也不会抛专用异常。

- [ ] **Step 3: 在 `register.py` 中实现邮箱创建后的黑名单检查**

给 `RegistrationEngine` 增加共享小方法，例如：

```python
def _current_email_suffix(self) -> str | None:
    return extract_email_suffix(self.email or "")


def _should_apply_email_suffix_blacklist(self) -> bool:
    return should_apply_email_suffix_blacklist(self.email_service.service_type.value)
```

把 `_create_email()` 改为带有限循环的获取逻辑：

```python
for attempt in range(10):
    self.email_info = self.email_service.create_email()
    self.email = self.email_info["email"]
    suffix = extract_email_suffix(self.email)
    if self._should_apply_email_suffix_blacklist() and suffix and _is_blacklisted(suffix):
        self._log(f"邮箱后缀 {suffix} 已在黑名单中，重新获取邮箱", "warning")
        continue
    return True

self._log("连续获取到黑名单邮箱后缀，已停止本次任务", "error")
return False
```

其中 `_is_blacklisted(suffix)` 使用 `get_db()` + `crud.is_email_suffix_blacklisted(...)`。

- [ ] **Step 4: 在 `register.py` 中实现共享的 `registration_disallowed` 解析**

抽一个最小共享方法，供当前流水线和 codexgen fallback 共用：

```python
def _raise_if_registration_disallowed(self, response) -> None:
    try:
        payload = response.json()
    except Exception:
        return
    error = payload.get("error") or {}
    if error.get("code") != "registration_disallowed":
        return
    suffix = extract_email_suffix(self.email or "")
    detail = error.get("message") or "registration_disallowed"
    raise RegistrationDisallowedSuffixError(
        email=self.email,
        suffix=suffix,
        detail=detail,
    )
```

然后在 `_create_user_account()` 的非 200 分支中优先调用该方法，再走原有 warning / False 返回逻辑。

- [ ] **Step 5: 重跑注册引擎测试，确认变绿**

Run:

```bash
timeout 60s pytest tests/test_registration_engine.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/core/register.py src/core/email_suffix_blacklist.py tests/test_registration_engine.py
git commit -m "feat: enforce email suffix blacklist in registration engine"
```

---

## Task 5: 在任务层完成自动拉黑、整轮重试，并覆盖 codexgen fallback

**Files:**
- Create: `tests/test_registration_job.py`
- Modify: `src/core/registration_job.py`
- Modify: `src/core/pipeline/steps/codexgen.py`
- Modify: `tests/test_codexgen_pipeline.py`

- [ ] **Step 1: 先写失败测试，锁定自动拉黑后的整轮重试**

在 `tests/test_registration_job.py` 先增加最小失败测试：

```python
def test_run_registration_job_auto_blacklists_suffix_and_retries_current_pipeline(temp_db, monkeypatch):
    attempts = {"count": 0}

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RegistrationDisallowedSuffixError(
                    email="first@badmail.com",
                    suffix="badmail.com",
                    detail="Sorry, we cannot create your account with the given information.",
                )
            return RegistrationResult(success=True, email="ok@example.net", ...)

    ...

    result = run_registration_job(...)
    assert result.success is True
    assert attempts["count"] == 2
    assert crud.is_email_suffix_blacklisted(temp_db, "badmail.com") is True
```

再补一个超出重试上限测试：

```python
def test_run_registration_job_stops_after_registration_retry_limit(temp_db, monkeypatch):
    ...
    assert result.success is False
    assert "registration_disallowed" in (result.error_message or "")
```

再在 `tests/test_codexgen_pipeline.py` 增加 fallback 测试：

```python
def test_codexgen_create_account_fallback_raises_registration_disallowed_suffix_error(...):
    ...
    with pytest.raises(RegistrationDisallowedSuffixError):
        runtime.run_create_account_profile_step()
```

- [ ] **Step 2: 运行任务层与 codexgen 聚焦测试，确认先红灯**

Run:

```bash
timeout 60s pytest tests/test_registration_job.py tests/test_codexgen_pipeline.py -q
```

Expected: FAIL，因为当前 `run_registration_job()` 不会捕获专用异常重试，codexgen fallback 也不会识别该错误。

- [ ] **Step 3: 在 `registration_job.py` 中增加自动拉黑后的整轮重试**

把 `run_registration_job()` 改成显式尝试循环，最小结构类似：

```python
max_attempts = max(1, int(get_settings().registration_max_retries) + 1)

for attempt in range(1, max_attempts + 1):
    try:
        ...
        return RegistrationJobResult(success=True, ...)
    except RegistrationDisallowedSuffixError as exc:
        if exc.suffix:
            crud.upsert_auto_blacklist_suffix(
                db,
                exc.suffix,
                reason=exc.detail,
                source="auto_registration_disallowed",
            )
        if callback_logger:
            callback_logger(f"检测到 registration_disallowed，已将邮箱后缀 {exc.suffix or '-'} 加入黑名单")
            callback_logger("当前任务将使用新邮箱重新尝试注册")
        if attempt >= max_attempts:
            _update_registration_task_failure(...)
            return RegistrationJobResult(success=False, email=exc.email, error_message=exc.detail)
        continue
```

注意：

1. 每一轮都重新创建 email service / engine / runtime。
2. `known_email` / `known_service_id` / `result_payload` 仍要按当前逻辑维护。
3. 失败回写时保留最后一次禁止错误的 detail。

- [ ] **Step 4: 在 `codexgen.py` fallback 中接共享禁止错误识别**

修改 `_run_create_account_fallback()`，在两个 `session.post(...)` 的非 200 路径上都调用：

```python
self._engine._raise_if_registration_disallowed(response)
```

这样 codexgen 自定义 fallback 和当前流水线共享同一条禁止后缀错误通道。

- [ ] **Step 5: 重跑聚焦测试并做一次端到端回归**

Run:

```bash
timeout 60s pytest tests/test_registration_job.py tests/test_codexgen_pipeline.py -q
```

Expected: PASS。

再跑本功能相关完整回归：

```bash
timeout 60s pytest \
  tests/test_email_suffix_blacklist_core.py \
  tests/test_email_suffix_blacklist_routes.py \
  tests/test_settings_email_blacklist_assets.py \
  tests/test_registration_engine.py \
  tests/test_registration_job.py \
  tests/test_codexgen_pipeline.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/core/registration_job.py src/core/pipeline/steps/codexgen.py tests/test_registration_job.py tests/test_codexgen_pipeline.py
git commit -m "feat: retry registration after auto blacklisting email suffix"
```

---

## Final Verification

- [ ] **Step 1: 跑本轮全部关键回归**

Run:

```bash
timeout 60s pytest \
  tests/test_email_suffix_blacklist_core.py \
  tests/test_email_suffix_blacklist_routes.py \
  tests/test_settings_email_blacklist_assets.py \
  tests/test_registration_engine.py \
  tests/test_registration_job.py \
  tests/test_codexgen_pipeline.py \
  tests/test_registration_service.py \
  tests/test_settings_service.py -q
```

Expected: 全绿，无新增基线回归。

- [ ] **Step 2: 人工检查设置页与注册日志关键路径**

手工检查清单：

1. 登录 Web UI 后进入 `/settings`，确认“注册配置”下能看到“邮箱后缀黑名单”卡片。
2. 手动新增 `@badmail.com` 后，列表展示为 `badmail.com`。
3. 禁用后再次命中自动拉黑时，记录会被重新启用，命中次数累加。
4. 日志中能看到：
   - `邮箱后缀 ... 已在黑名单中，重新获取邮箱`
   - `检测到 registration_disallowed，已将邮箱后缀 ... 加入黑名单`

- [ ] **Step 3: 产出总结并准备合并**

```bash
git status
git log --oneline --decorate -5
```

Expected: 工作区干净，只剩本轮相关提交。
