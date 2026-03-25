# Unified Proxy Dispatch Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为当前项目补齐统一代理调度层与动态代理高级配置能力，让单任务/非批量任务获得稳定 fallback 链，并让批量任务拥有受控的内存态动态代理池。

**Architecture:** 采用“先配置、再基础设施、再调度、最后入口接入与前端配置面”的渐进式纵切方案。先把 settings/runtime model 扩展成可描述动态代理请求模板与任务大类默认值的结构化配置，再在 `dynamic_proxy.py` 中实现 curl 解析、批量列表解析与探测能力，随后新增 `proxy_dispatch_service.py` 与 `proxy_batch_pool.py` 收口单任务 fallback 与批量池策略，最后把 `registration` / `accounts` 等现有调用点切到统一调度层并完成设置页升级。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy ORM、Jinja2、vanilla JS、pytest、现有 settings/runtime 配置模型、现有注册/账号 route 与 application service 模式。

---

## Spec Reference

- `docs/superpowers/specs/2026-03-25-unified-proxy-dispatch-phase-a-design.md`

## Review Note

- 当前会话未获得用户对 reviewer/subagent 的显式授权，因此本计划先按现有上下文本地自审并落盘；如后续用户授权，再补 reviewer 循环。

## Execution Prerequisite

当前仓库主工作区的 Python 环境存在“系统 Python 有 pytest、项目 `.venv` 有 Jinja2 等依赖”的混合状态。执行本计划前，先统一好测试命令，避免环境错误污染红/绿步骤。

1. 若本地环境尚未补齐依赖，先执行：

```bash
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

2. 若仍遇到 `python -m pytest` 缺 `jinja2` 一类问题，则在本轮测试命令前统一加：

```bash
env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest
```

3. 下面所有命令默认都按仓库约束加 `timeout 60s`，推荐直接使用：

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest ...
```

4. 进入 Task 1 前先记录当前相关基线：

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_settings_service.py \
  tests/test_proxy_settings_routes.py \
  tests/test_settings_proxy_assets.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: PASS；若不是环境问题而是已有业务回归，先修好基线再进入下面任务。

---

## File Map

### Create

- `src/application/proxy_dispatch_service.py` — 单任务/非批量 fallback 与批量代理池准备入口。
- `src/application/proxy_batch_pool.py` — `batch_id` 维度的内存态代理池与四种分配策略。
- `tests/test_dynamic_proxy.py` — curl 解析、请求模板、列表响应解析、探测行为测试。
- `tests/test_proxy_dispatch_service.py` — 单任务 fallback 顺序、显式 `proxy` 优先级、失败分类测试。
- `tests/test_proxy_batch_pool.py` — `random/exclusive/consume_once/strict_isolation` 策略与耗尽行为测试。
- `tests/test_accounts_proxy_dispatch.py` — `accounts.py` 调用统一调度层的回归测试。

### Modify

- `src/core/dynamic_proxy.py` — 升级成动态代理基础设施层，支持 curl 解析、GET/POST、批量列表解析、连通性测试、出口 IP 探测。
- `src/application/__init__.py` — 导出新的代理调度 service（如现有导出风格需要）。
- `src/application/settings_service.py` — 扩展动态代理高级配置与任务大类默认配置更新逻辑。
- `src/config/settings.py` — 增加新的 settings definition、runtime model 字段与结构化默认值。
- `src/web/routes/settings.py` — 扩展动态代理设置的 request/response model 与测试接口。
- `templates/settings.html` — 增加动态代理高级配置区、curl 输入区、任务大类默认配置区。
- `static/js/settings.js` — 解析 curl、维护高级字段表单状态、序列化保存 payload。
- `tests/test_settings_service.py` — settings service 对新配置的 round-trip 回归。
- `tests/test_proxy_settings_routes.py` — settings route 对新配置的 GET/POST round-trip 回归。
- `tests/test_settings_proxy_assets.py` — settings 页面高级动态代理配置区与 JS 行为回归。
- `tests_runtime/settings_js_harness.py` — 补 curl 解析、payload 序列化等前端场景。
- `src/application/registration_service.py` — 单任务注册链路改成走统一调度层。
- `src/application/batch_registration_service.py` — 批量任务接入代理池准备、租约、策略更新。
- `src/web/routes/registration.py` — 请求模型支持覆盖项，批量开始前准备代理池。
- `src/web/routes/accounts.py` — 去掉本地 `_get_proxy()` 拼装逻辑，切到统一调度层。
- `tests/test_registration_service.py` — 单任务注册调度回归。
- `tests/test_batch_registration_service.py` — 批量 service 与代理池交互回归。
- `tests/test_registration_batch_routes.py` — 批量接口覆盖项、启动前失败、运行中耗尽回归。
- `tests/test_static_asset_versioning.py` — 如 `settings.html` 结构变化需要，补静态资源版本引用回归。

---

## Task 1: 扩展 runtime settings 与动态代理高级配置后端契约

**Files:**
- Modify: `src/config/settings.py`
- Modify: `src/application/settings_service.py`
- Modify: `src/web/routes/settings.py`
- Modify: `tests/test_settings_service.py`
- Modify: `tests/test_proxy_settings_routes.py`

- [ ] **Step 1: 先写失败测试，锁定高级动态代理配置 round-trip**

在 `tests/test_settings_service.py` 先增加一组最小失败测试，覆盖：

```python
def test_update_dynamic_proxy_settings_persists_advanced_request_templates(temp_db):
    service = SettingsService(temp_db)

    updated = service.update_dynamic_proxy_settings(
        {
            "enabled": True,
            "request_method": "POST",
            "request_url": "https://proxy.example.com/pool",
            "request_headers_template": {"Authorization": "Bearer token-1"},
            "request_body_template": {"count": "{{count}}", "region": "us"},
            "request_timeout_seconds": 8,
            "request_count_param_name": "count",
            "request_count_default": 3,
            "response_root_field": "data.items",
            "response_item_mode": "object_list",
            "response_field_mapping": {"host": "server", "port": "port"},
            "task_defaults": {
                "batch_registration": {
                    "probe_url": "https://probe.example.com/ip",
                    "dynamic_request_count": 12,
                    "allocation_strategy": "exclusive",
                    "proxy_list_candidate_limit": 5,
                    "batch_prefetch_multiplier": 3,
                    "batch_prefetch_max": 100,
                }
            },
        }
    )

    assert updated.proxy_dynamic_request_method == "POST"
    assert updated.proxy_dynamic_request_body_template["count"] == "{{count}}"
    assert updated.proxy_dynamic_response_item_mode == "object_list"
    assert updated.proxy_dynamic_task_defaults["batch_registration"]["allocation_strategy"] == "exclusive"
```

再在 `tests/test_proxy_settings_routes.py` 增加 route round-trip：

```python
def test_dynamic_proxy_settings_route_round_trip_advanced_payload(client):
    payload = {
        "enabled": True,
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_headers_template": {"Authorization": "Bearer abc"},
        "request_body_template": {"count": "{{count}}"},
        "request_count_param_name": "count",
        "request_count_default": 5,
        "response_root_field": "data.items",
        "response_item_mode": "string_list",
        "response_field_mapping": {},
        "task_defaults": {
            "single_registration": {"probe_url": "https://probe.example.com/single"}
        },
    }

    response = client.post("/api/settings/proxy/dynamic", json=payload)
    assert response.status_code == 200

    fetched = client.get("/api/settings/proxy/dynamic")
    body = fetched.json()
    assert body["request_method"] == "POST"
    assert body["request_body_template"]["count"] == "{{count}}"
    assert body["task_defaults"]["single_registration"]["probe_url"] == "https://probe.example.com/single"
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_settings_service.py \
  tests/test_proxy_settings_routes.py -q
```

Expected: FAIL，因为当前 settings model / service / route 还不认识这些新字段。

- [ ] **Step 3: 在 `src/config/settings.py` 中补齐新的 definition 与 runtime model 字段**

按已有 `SettingDefinition` 模式新增最小配置集，至少补齐：

```python
"proxy_dynamic_request_method": SettingDefinition(..., default_value="GET", ...)
"proxy_dynamic_request_url": SettingDefinition(..., default_value="", ...)
"proxy_dynamic_request_headers_template": SettingDefinition(..., default_value={}, ...)
"proxy_dynamic_request_body_template": SettingDefinition(..., default_value={}, ...)
"proxy_dynamic_request_timeout_seconds": SettingDefinition(..., default_value=10, ...)
"proxy_dynamic_request_count_param_name": SettingDefinition(..., default_value="count", ...)
"proxy_dynamic_request_count_default": SettingDefinition(..., default_value=3, ...)
"proxy_dynamic_response_root_field": SettingDefinition(..., default_value="", ...)
"proxy_dynamic_response_item_mode": SettingDefinition(..., default_value="string_list", ...)
"proxy_dynamic_response_field_mapping": SettingDefinition(..., default_value={}, ...)
"proxy_dynamic_task_defaults": SettingDefinition(..., default_value={}, ...)
```

并在 `Settings` model 中补对应字段：

```python
proxy_dynamic_request_method: str = "GET"
proxy_dynamic_request_url: str = ""
proxy_dynamic_request_headers_template: Dict[str, Any] = {}
proxy_dynamic_request_body_template: Dict[str, Any] = {}
proxy_dynamic_request_timeout_seconds: int = 10
proxy_dynamic_request_count_param_name: str = "count"
proxy_dynamic_request_count_default: int = 3
proxy_dynamic_response_root_field: str = ""
proxy_dynamic_response_item_mode: str = "string_list"
proxy_dynamic_response_field_mapping: Dict[str, str] = {}
proxy_dynamic_task_defaults: Dict[str, Dict[str, Any]] = {}
```

- [ ] **Step 4: 在 `SettingsService` 与 `settings.py` route 中实现最小保存/读取契约**

把 `update_dynamic_proxy_settings()` 改成更新新字段：

```python
update_dict = {
    "proxy_dynamic_enabled": payload.get("enabled", False),
    "proxy_dynamic_request_method": payload.get("request_method", "GET"),
    "proxy_dynamic_request_url": payload.get("request_url", ""),
    "proxy_dynamic_request_headers_template": payload.get("request_headers_template", {}),
    "proxy_dynamic_request_body_template": payload.get("request_body_template", {}),
    "proxy_dynamic_request_timeout_seconds": payload.get("request_timeout_seconds", 10),
    "proxy_dynamic_request_count_param_name": payload.get("request_count_param_name", "count"),
    "proxy_dynamic_request_count_default": payload.get("request_count_default", 3),
    "proxy_dynamic_response_root_field": payload.get("response_root_field", ""),
    "proxy_dynamic_response_item_mode": payload.get("response_item_mode", "string_list"),
    "proxy_dynamic_response_field_mapping": payload.get("response_field_mapping", {}),
    "proxy_dynamic_task_defaults": payload.get("task_defaults", {}),
}
```

同步升级 route 的 request/response model，让 GET 返回完整结构，POST 接收完整结构；`api_key` / token 类敏感字段继续遵守“留空不覆盖”的现有语义。

- [ ] **Step 5: 重跑测试，确认新契约变绿**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_settings_service.py \
  tests/test_proxy_settings_routes.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/config/settings.py src/application/settings_service.py src/web/routes/settings.py tests/test_settings_service.py tests/test_proxy_settings_routes.py
git commit -m "feat: extend dynamic proxy runtime settings"
```

---

## Task 2: 升级动态代理基础设施（curl / GET/POST / 列表解析 / 探测）

**Files:**
- Modify: `src/core/dynamic_proxy.py`
- Create: `tests/test_dynamic_proxy.py`
- Modify: `tests/test_proxy_settings_routes.py`

- [ ] **Step 1: 写失败测试，锁定 curl 解析、请求数量注入与列表解析**

创建 `tests/test_dynamic_proxy.py`，先写最小失败测试：

```python
from src.core.dynamic_proxy import (
    parse_dynamic_proxy_curl,
    build_dynamic_proxy_request,
    parse_dynamic_proxy_candidates,
)


def test_parse_dynamic_proxy_curl_extracts_method_url_headers_and_body():
    parsed = parse_dynamic_proxy_curl(
        "curl 'https://proxy.example.com/pool' -X POST "
        "-H 'Authorization: Bearer abc' "
        "-H 'Content-Type: application/json' "
        "--data '{\"count\": 5}'"
    )

    assert parsed["request_method"] == "POST"
    assert parsed["request_url"] == "https://proxy.example.com/pool"
    assert parsed["request_headers_template"]["Authorization"] == "Bearer abc"
    assert parsed["request_body_template"]["count"] == 5


def test_build_dynamic_proxy_request_injects_count_into_query_or_body():
    request = build_dynamic_proxy_request(
        request_method="POST",
        request_url="https://proxy.example.com/pool",
        request_headers_template={"Authorization": "Bearer abc"},
        request_body_template={"count": "{{count}}", "region": "us"},
        request_count_param_name="count",
        count=7,
    )

    assert request.method == "POST"
    assert request.body["count"] == 7


def test_parse_dynamic_proxy_candidates_supports_string_and_object_lists():
    string_rows = parse_dynamic_proxy_candidates(
        payload={"data": ["http://1.1.1.1:8000", "socks5://2.2.2.2:9000"]},
        response_root_field="data",
        response_item_mode="string_list",
        response_field_mapping={},
    )
    object_rows = parse_dynamic_proxy_candidates(
        payload={"data": {"items": [{"server": "3.3.3.3", "port": 8080, "protocol": "http"}]}},
        response_root_field="data.items",
        response_item_mode="object_list",
        response_field_mapping={"host": "server", "type": "protocol"},
    )

    assert string_rows[0].proxy_url == "http://1.1.1.1:8000"
    assert object_rows[0].host == "3.3.3.3"
    assert object_rows[0].scheme == "http"
```

再加一个探测测试，先锁定“严格隔离拿不到出口 IP 时允许退化到 proxy_url 粒度”所需的基础返回结构：

```python
def test_probe_proxy_candidate_returns_connectivity_and_optional_egress_ip(monkeypatch):
    ...
    assert result.ok is True
    assert result.egress_ip is None
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_dynamic_proxy.py -q
```

Expected: FAIL，因为这些 helper 与标准化结果结构还不存在。

- [ ] **Step 3: 在 `src/core/dynamic_proxy.py` 里补最小基础设施实现**

建议先实现几个聚焦 helper，而不是一口气堆进一个巨大函数：

```python
@dataclass(slots=True)
class DynamicProxyCandidate:
    proxy_url: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    source_metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class DynamicProxyRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: dict[str, Any] | None = None


@dataclass(slots=True)
class DynamicProxyProbeResult:
    ok: bool
    proxy_url: str
    egress_ip: str | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
```

再补以下函数：

1. `parse_dynamic_proxy_curl(...)`
2. `build_dynamic_proxy_request(...)`
3. `parse_dynamic_proxy_candidates(...)`
4. `probe_proxy_candidate(...)`

实现要求：

1. 支持 `GET/POST`
2. `count` 可注入 query 或 body
3. 支持 `response_root_field` 点号路径
4. 支持自动识别常见对象键名：

```python
AUTO_FIELD_KEYS = {
    "host": ("host", "ip", "server", "address"),
    "port": ("port",),
    "username": ("username", "user"),
    "password": ("password", "pass"),
    "type": ("type", "protocol", "scheme"),
}
```

- [ ] **Step 4: 顺手升级 settings 测试接口，让它复用新的请求/探测 helper**

把 `/api/settings/proxy/dynamic/test` 改成走新的构造/请求/探测逻辑，而不是继续写死“单个代理 URL + api_key_header”路径。  
先只做到最小可用：

```python
request = build_dynamic_proxy_request(...)
candidates = fetch_dynamic_proxy_candidates(...)
probe = probe_proxy_candidate(candidates[0], probe_url=...)
```

- [ ] **Step 5: 重跑动态代理基础设施与 route 测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_dynamic_proxy.py \
  tests/test_proxy_settings_routes.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/core/dynamic_proxy.py tests/test_dynamic_proxy.py tests/test_proxy_settings_routes.py
git commit -m "feat: add dynamic proxy request parsing and probing"
```

---

## Task 3: 实现单任务/非批量统一代理调度服务

**Files:**
- Create: `src/application/proxy_dispatch_service.py`
- Modify: `src/application/__init__.py`
- Create: `tests/test_proxy_dispatch_service.py`

- [ ] **Step 1: 写失败测试，锁定显式 proxy 优先级、fallback 链与失败分类**

创建 `tests/test_proxy_dispatch_service.py`，先加这些失败测试：

```python
from src.application.proxy_dispatch_service import ProxyDispatchService


def test_resolve_single_candidates_returns_explicit_proxy_only_when_present():
    service = ProxyDispatchService(
        dynamic_candidates_provider=lambda **_: ["http://dynamic-1:8000"],
        proxy_list_provider=lambda limit: ["http://local-1:8000"],
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    candidates = service.resolve_single_candidates(
        task_group="generic_single",
        explicit_proxy="http://manual-1:8000",
        overrides={},
    )

    assert [item.proxy_url for item in candidates] == ["http://manual-1:8000"]


def test_resolve_single_candidates_orders_dynamic_then_proxy_list_then_static():
    service = ProxyDispatchService(
        dynamic_candidates_provider=lambda **_: ["http://dynamic-1:8000", "http://dynamic-2:8000"],
        proxy_list_provider=lambda limit: ["http://local-1:8000", "http://local-2:8000"],
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    candidates = service.resolve_single_candidates("generic_single", None, {"proxy_list_candidate_limit": 2})

    assert [item.source for item in candidates] == [
        "dynamic_pool",
        "dynamic_pool",
        "proxy_list",
        "proxy_list",
        "static",
    ]


def test_is_proxy_related_failure_matches_network_and_block_signals():
    service = ProxyDispatchService(...)
    assert service.is_proxy_related_failure(RuntimeError("403 blocked by upstream")) is True
    assert service.is_proxy_related_failure(RuntimeError("429 captcha required")) is True
    assert service.is_proxy_related_failure(RuntimeError("invalid password")) is False
```

再补一个随机候选上限测试：

```python
def test_resolve_single_candidates_limits_proxy_list_random_sample_to_requested_cap():
    ...
    assert len([item for item in candidates if item.source == "proxy_list"]) == 5
```

- [ ] **Step 2: 运行测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_proxy_dispatch_service.py -q
```

Expected: FAIL，因为统一调度 service 还不存在。

- [ ] **Step 3: 实现最小的 `ProxyDispatchService`**

建议先实现以下接口：

```python
@dataclass(slots=True)
class ResolvedProxyCandidate:
    proxy_url: str
    source: str
    egress_ip: str | None = None
    proxy_key: str | None = None


class ProxyDispatchService:
    def resolve_single_candidates(self, task_group: str, explicit_proxy: str | None, overrides: dict[str, Any]) -> list[ResolvedProxyCandidate]:
        ...

    def is_proxy_related_failure(self, error: Exception | str) -> bool:
        ...
```

实现规则：

1. `explicit_proxy` 非空时只返回它自己
2. 否则先拼动态代理候选
3. 再随机采样本地代理列表，数量按 override 或默认值裁剪
4. 最后附加静态代理（如果存在）
5. 失败分类按用户确认规则内置实现

- [ ] **Step 4: 让 service 读取 task-group 默认配置与 override**

补最小配置合并逻辑：

```python
effective = {
    **settings.proxy_dynamic_task_defaults.get(task_group, {}),
    **(overrides or {}),
}
```

其中要至少消费：

1. `dynamic_request_count`
2. `proxy_list_candidate_limit`

- [ ] **Step 5: 重跑 service 测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_proxy_dispatch_service.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/application/proxy_dispatch_service.py src/application/__init__.py tests/test_proxy_dispatch_service.py
git commit -m "feat: add unified single proxy dispatch service"
```

---

## Task 4: 实现批量代理池与四种分配策略

**Files:**
- Create: `src/application/proxy_batch_pool.py`
- Modify: `src/application/proxy_dispatch_service.py`
- Create: `tests/test_proxy_batch_pool.py`

- [ ] **Step 1: 写失败测试，锁定四种策略与耗尽语义**

创建 `tests/test_proxy_batch_pool.py`，至少覆盖：

```python
from src.application.proxy_batch_pool import ProxyBatchPool


def test_exclusive_strategy_never_duplicates_proxy_while_two_tasks_are_running():
    pool = ProxyBatchPool(
        batch_id="batch-1",
        strategy="exclusive",
        candidates=["http://a:1", "http://b:1"],
    )

    first = pool.lease()
    second = pool.lease()

    assert first.proxy_url != second.proxy_url


def test_consume_once_strategy_never_reuses_proxy_after_release():
    pool = ProxyBatchPool(...)
    first = pool.lease()
    pool.complete(first.proxy_url, success=False)

    second = pool.lease()
    assert second.proxy_url != first.proxy_url


def test_strict_isolation_falls_back_to_proxy_identity_when_egress_ip_missing():
    pool = ProxyBatchPool(
        batch_id="batch-2",
        strategy="strict_isolation",
        candidates=[
            {"proxy_url": "http://a:1", "egress_ip": None},
            {"proxy_url": "http://a:1", "egress_ip": None},
        ],
    )

    first = pool.lease()
    pool.complete(first.proxy_url, success=True)

    with pytest.raises(ProxyPoolExhaustedError):
        pool.lease()
```

再加两个关键失败测试：

```python
def test_prepare_batch_proxy_pool_raises_when_available_candidates_less_than_required():
    ...


def test_runtime_pool_exhaustion_raises_instead_of_falling_back_to_static_or_proxy_list():
    ...
```

- [ ] **Step 2: 运行测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_proxy_batch_pool.py -q
```

Expected: FAIL，因为批量代理池抽象还不存在。

- [ ] **Step 3: 实现最小 `ProxyBatchPool` 与策略状态**

先收口成一个可测的小类，而不是直接把状态散落到 `batch_registration_service.py`：

```python
class ProxyBatchPool:
    def __init__(self, batch_id: str, strategy: str, candidates: list[ResolvedProxyCandidate]):
        self.batch_id = batch_id
        self.strategy = strategy
        self.available = [...]
        self.in_use = set()
        self.consumed = set()
        self.isolated_keys = set()

    def lease(self) -> ResolvedProxyCandidate:
        ...

    def complete(self, candidate: ResolvedProxyCandidate, *, success: bool) -> None:
        ...
```

策略规则必须严格按 spec：

1. `random`：允许重复
2. `exclusive`：仅运行中不重复，完成后可回池
3. `consume_once`：分配过即消费
4. `strict_isolation`：优先 `egress_ip`，没有时退化到 `proxy_url`

- [ ] **Step 4: 在 `ProxyDispatchService` 中补 `prepare_batch_proxy_pool()`**

建议新增：

```python
def prepare_batch_proxy_pool(self, *, batch_id: str, task_group: str, concurrency: int, overrides: dict[str, Any]) -> ProxyBatchPool:
    ...
```

要求：

1. 根据 task-group 默认值与 override 计算预抓数量
2. 用 `concurrency * 3` 与 `100` 作为默认批量参数
3. 候选数量不足时立即抛错
4. 不做运行中补抓

- [ ] **Step 5: 重跑代理池与调度 service 测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_proxy_dispatch_service.py \
  tests/test_proxy_batch_pool.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add src/application/proxy_batch_pool.py src/application/proxy_dispatch_service.py tests/test_proxy_batch_pool.py tests/test_proxy_dispatch_service.py
git commit -m "feat: add batch proxy pool strategies"
```

---

## Task 5: 把 registration / accounts 调用点切到统一调度层

**Files:**
- Modify: `src/application/registration_service.py`
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/web/routes/registration.py`
- Modify: `src/web/routes/accounts.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_batch_routes.py`
- Create: `tests/test_accounts_proxy_dispatch.py`

- [ ] **Step 1: 写失败测试，锁定入口接入统一调度层**

先在 `tests/test_registration_service.py` 增加单任务回归：

```python
def test_registration_service_uses_resolved_proxy_candidates_until_non_proxy_error(temp_db, monkeypatch):
    candidates = [
        ResolvedProxyCandidate(proxy_url="http://dynamic-1:8000", source="dynamic_pool"),
        ResolvedProxyCandidate(proxy_url="http://local-1:8000", source="proxy_list"),
    ]
    ...
    assert attempted_proxies == ["http://dynamic-1:8000", "http://local-1:8000"]
```

在 `tests/test_batch_registration_service.py` 增加批量池回归：

```python
def test_batch_registration_service_prepares_pool_before_running_parallel_batch(...):
    ...
    assert prepare_calls[0]["task_group"] == "batch_registration"
    assert prepare_calls[0]["concurrency"] == 4
    assert prepare_calls[0]["overrides"]["dynamic_proxy_strategy"] == "exclusive"
```

在 `tests/test_registration_batch_routes.py` 锁定请求 override 字段：

```python
def test_start_batch_registration_accepts_dynamic_proxy_overrides(route_db, monkeypatch):
    response = client.post(
        "/api/registration/batch",
        json={
            "count": 10,
            "email_service_type": "tempmail",
            "concurrency": 4,
            "dynamic_proxy_request_count": 12,
            "dynamic_proxy_probe_url": "https://probe.example.com/ip",
            "dynamic_proxy_strategy": "exclusive",
        },
    )
    assert response.status_code == 200
```

再创建 `tests/test_accounts_proxy_dispatch.py`，锁定 `accounts.py` 不再走 `_get_proxy()` 自拼逻辑：

```python
def test_accounts_refresh_uses_proxy_dispatch_service_when_request_proxy_missing(client, monkeypatch):
    ...
    assert dispatched_task_group == "generic_single"
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py \
  tests/test_accounts_proxy_dispatch.py -q
```

Expected: FAIL，因为入口还没有接入 `ProxyDispatchService`，也没有 override 字段。

- [ ] **Step 3: 给 request model 加最小 override 字段**

在 `src/web/routes/registration.py` 与 `src/web/routes/accounts.py` 的相关 request model 中补：

```python
dynamic_proxy_request_count: int | None = None
dynamic_proxy_probe_url: str | None = None
dynamic_proxy_strategy: str | None = None
proxy_list_candidate_limit: int | None = None
```

只给真正需要的 request model 补字段：

1. `RegistrationTaskCreate`
2. `BatchRegistrationRequest`
3. `OutlookBatchRegistrationRequest`
4. `accounts.py` 中 refresh / validate 请求模型

- [ ] **Step 4: 单任务链路改成“拿候选列表 + 代理相关失败再切下一个”**

`registration_service.py` 与 `accounts.py` 不再自己取一个 proxy 后直接跑到底，而是改成：

```python
candidates = proxy_dispatch_service.resolve_single_candidates(
    task_group="single_registration",
    explicit_proxy=proxy,
    overrides=override_dict,
)

for candidate in candidates:
    try:
        return run_with_proxy(candidate.proxy_url)
    except Exception as exc:
        if not proxy_dispatch_service.is_proxy_related_failure(exc):
            raise
        last_error = exc

raise last_error
```

`accounts.py` 的 `_get_proxy()` 应删除或降级成纯兼容 wrapper，不再拼接“代理列表 → 动态代理 → 静态代理”逻辑。

- [ ] **Step 5: 批量链路接入 `prepare_batch_proxy_pool()` 与 `lease/complete`**

`batch_registration_service.py` 与 `registration.py` 中需要：

1. 批量开始前准备代理池
2. 子任务启动前从池里 `lease()`
3. 子任务完成后 `complete()`
4. 池准备不足时直接失败
5. 运行中耗尽时剩余任务失败

最小伪代码：

```python
pool = proxy_dispatch_service.prepare_batch_proxy_pool(
    batch_id=batch_id,
    task_group="batch_registration",
    concurrency=concurrency,
    overrides=override_dict,
)

candidate = pool.lease()
try:
    run_one_task(proxy=candidate.proxy_url)
    pool.complete(candidate, success=True)
except Exception:
    pool.complete(candidate, success=False)
    raise
```

- [ ] **Step 6: 重跑入口接入相关测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py \
  tests/test_accounts_proxy_dispatch.py -q
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src/application/registration_service.py src/application/batch_registration_service.py src/web/routes/registration.py src/web/routes/accounts.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_accounts_proxy_dispatch.py
git commit -m "refactor: route registration and accounts through proxy dispatch"
```

---

## Task 6: 升级 settings 动态代理配置面与前端序列化逻辑

**Files:**
- Modify: `templates/settings.html`
- Modify: `static/js/settings.js`
- Modify: `tests/test_settings_proxy_assets.py`
- Modify: `tests_runtime/settings_js_harness.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 写失败资产测试，锁定高级动态代理配置 UI 结构**

在 `tests/test_settings_proxy_assets.py` 增加模板断言：

```python
def test_settings_template_contains_dynamic_proxy_advanced_request_controls():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'id="dynamic-proxy-request-method"' in template
    assert 'id="dynamic-proxy-curl-input"' in template
    assert 'id="dynamic-proxy-request-headers"' in template
    assert 'id="dynamic-proxy-request-body"' in template
    assert 'id="dynamic-proxy-response-item-mode"' in template
    assert 'data-task-group="batch_registration"' in template
```

再补 JS/harness 断言：

```python
def test_settings_js_parses_curl_into_dynamic_proxy_form_fields():
    result = run_settings_js_scenario("dynamic_proxy_parse_curl")
    assert result["request_method"] == "POST"
    assert result["request_url"] == "https://proxy.example.com/pool"
    assert result["authorization_header"] == "Bearer abc"


def test_settings_js_serializes_dynamic_proxy_task_defaults_and_mappings():
    result = run_settings_js_scenario("dynamic_proxy_save_payload")
    assert result["payload"]["response_item_mode"] == "object_list"
    assert result["payload"]["task_defaults"]["batch_registration"]["allocation_strategy"] == "exclusive"
```

- [ ] **Step 2: 运行前端聚焦测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_settings_proxy_assets.py -q
```

Expected: FAIL，因为模板和 `settings.js` 还没有这些控件与序列化逻辑。

- [ ] **Step 3: 在 `settings.html` 增加最小高级配置区**

建议在现有“动态代理配置” card 内增加一个折叠的高级区，至少包含：

1. 请求方法下拉框
2. curl 输入 textarea + “解析 curl”按钮
3. headers/body 编辑区
4. 返回模式下拉框（字符串列表 / 对象列表）
5. 字段映射编辑区
6. 任务大类默认配置区：
   - `single_registration`
   - `batch_registration`
   - `unlimited_registration`
   - `outlook_batch`
   - `generic_single`

保持这轮 UI 最小可用，不必做完整花哨交互。

- [ ] **Step 4: 在 `settings.js` 实现最小表单状态管理与 curl 解析**

实现方向：

1. 新增 DOM 引用
2. 新增 `parseDynamicProxyCurlInput()`，把 curl 解析结果填回表单
3. 新增 `buildDynamicProxyPayload()`，把高级字段组装成 POST payload
4. `loadSettings()` 时反填高级字段
5. `handleSaveDynamicProxySettings()` 改用新 payload

最小伪代码：

```javascript
function buildDynamicProxyPayload() {
  return {
    enabled: getChecked(...),
    request_method: elements.dynamicProxyRequestMethod.value,
    request_url: elements.dynamicProxyRequestUrl.value.trim(),
    request_headers_template: parseJsonTextarea(elements.dynamicProxyRequestHeaders.value, {}),
    request_body_template: parseJsonTextarea(elements.dynamicProxyRequestBody.value, {}),
    response_item_mode: elements.dynamicProxyResponseItemMode.value,
    response_field_mapping: collectDynamicProxyFieldMappings(),
    task_defaults: collectDynamicProxyTaskDefaults(),
  };
}
```

- [ ] **Step 5: 重跑前端配置页测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_settings_proxy_assets.py \
  tests/test_static_asset_versioning.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add templates/settings.html static/js/settings.js tests/test_settings_proxy_assets.py tests_runtime/settings_js_harness.py tests/test_static_asset_versioning.py
git commit -m "feat: add advanced dynamic proxy settings ui"
```

---

## Task 7: 做最终聚焦回归与差异收口

**Files:**
- No new files expected unless verification暴露遗漏。

- [ ] **Step 1: 运行动态代理与 settings 相关后端套件**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_dynamic_proxy.py \
  tests/test_settings_service.py \
  tests/test_proxy_settings_routes.py -q
```

Expected: PASS。

- [ ] **Step 2: 运行调度层与批量池套件**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_proxy_dispatch_service.py \
  tests/test_proxy_batch_pool.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行 route / 页面资源 / accounts 接入回归**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_registration_batch_routes.py \
  tests/test_accounts_proxy_dispatch.py \
  tests/test_settings_proxy_assets.py \
  tests/test_static_asset_versioning.py -q
```

Expected: PASS。

- [ ] **Step 4: 只在必要时补一个窄烟雾回归**

如果 Task 5 改动触发 registration 页或 settings 页额外影响，再跑：

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" python -m pytest \
  tests/test_registration_page_assets.py \
  tests/test_proxy_settings_routes.py -q
```

Expected: PASS。

- [ ] **Step 5: 检查 diff 范围，确认没有把 Phase B 混进来**

Run:

```bash
git diff -- src/core/dynamic_proxy.py src/application/ src/config/settings.py src/web/routes/registration.py src/web/routes/accounts.py src/web/routes/settings.py templates/settings.html static/js/settings.js tests/
```

Expected: 只包含 Phase A 相关改动；不应出现代理列表分页、导入结果弹窗、检测弹窗完整交互的实现。

- [ ] **Step 6: Commit 最终集成收口**

```bash
git add src/core/dynamic_proxy.py src/application/ src/config/settings.py src/web/routes/registration.py src/web/routes/accounts.py src/web/routes/settings.py templates/settings.html static/js/settings.js tests/
git commit -m "feat: complete unified proxy dispatch phase a"
```

