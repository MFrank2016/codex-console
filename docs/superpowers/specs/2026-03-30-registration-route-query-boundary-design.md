# registration route/query boundary 设计

- 日期：2026-03-30
- 状态：Draft / Proposed
- 目标读者：技术负责人、实施开发者、项目维护者
- 相关仓库：`/root/code-server/workspace/codex-console`
- 相关设计：
  - `2026-03-28-backend-architecture-remediation-roadmap-design.md`
  - `2026-03-28-registration-runs-boundary-migration-design.md`
- 相关已落地切片：
  - `2026-03-28-backend-architecture-remediation-foundation.md`

## 1. 背景

当前 `main` 已完成 registration start path 的第一批 owner 收口：

1. single / batch / outlook batch 的 bootstrap 语义已开始回到 application service。
2. route 启动路径已经不再直接返回 live ORM，而是返回 DTO / snapshot。
3. `RegistrationService`、`BatchRegistrationService`、`RegistrationRunsService` 已开始承担更清晰的 owner 角色。

但 `src/web/routes/registration.py` 仍然同时承载以下职责：

1. HTTP request/response adapter。
2. read-side query 组装。
3. failure filter/window 规则。
4. task / batch / service availability 读模型拼装。
5. runtime fallback 读取（如 task steps / batch status）。

这导致当前 registration route 仍不是纯 adapter，而是“半个 query service + 半个 response assembler”。如果不先把 read-side 从 route 中抽离，后续即使继续做 repository split、runtime split，route 仍会持续膨胀，新的结构边界也会继续被顶穿。

因此，本轮最合适的下一刀不是直接拆 `crud.py`，也不是立刻重写 `task_manager`，而是：

**先把 registration 的 route/query boundary 收口。**

---

## 2. 目标与非目标

### 2.1 目标

本轮设计需要达成以下目标：

1. 让 `registration.py` 对 read-side 退回 HTTP adapter。
2. 建立 registration query facade，统一承接 read-side 用例。
3. 建立 registration read-side DTO / view model，避免 route 继续手工拼装响应。
4. 将 read-side 中的 runtime fallback 语义集中到 facade，而不是散落在 route helper。
5. 保持现有 HTTP JSON 契约兼容，不破坏现有前端页面与 JS harness。
6. 为下一阶段 repository split 和 runtime split 提供稳定接口面。

### 2.2 非目标

本轮不包含：

1. 再次改动 `/registration/start`、`/registration/batch`、`/registration/outlook-batch` 的 bootstrap command owner。
2. 直接拆 `crud.py`。
3. 重写 `task_manager` 或 realtime 协议。
4. 把 batch 状态立刻持久化入库。
5. 清理 `register.py` / `registration_job.py` 中的 DB 访问。
6. 更换前端接口结构或字段命名。

---

## 3. 方案比较

### 方案 A：最小 query facade 收口（推荐）

做法：

1. 新增 `registration_query_facade.py`。
2. 新增 `registration_query_dtos.py`。
3. 将 registration route 中的 read-side 逻辑整体迁入 facade。
4. route 仅保留 request parsing、鉴权、HTTP error mapping、response_model 返回。

优点：

1. 风险可控，不改 DB schema。
2. 不会和下一阶段 repository split scope 打架。
3. 能立即阻止 `registration.py` 持续膨胀。
4. 形成后续 runtime/repository 迁移的稳定外壳。

缺点：

1. facade 第一阶段内部仍会依赖旧的 `crud`、`failure_repo`、`task_manager`。
2. 需要接受短期内“facade + compat helper”并存。

### 方案 B：直接按 bounded context 完整重组 registration 模块

做法：

1. 同时拆 route、query、command、repository、runtime。
2. 一次性重排目录结构。

优点：

1. 理论上最干净。

缺点：

1. 风险过高。
2. 会同时与 repository split、runtime split、core purification 冲突。
3. 当前不适合在一轮里同时碰 read-side 与 write-side。

### 方案 C：仅把 route helper 挪到同文件底部/旁文件

做法：

1. 只做函数搬家。
2. 不建立新的 facade / DTO。

优点：

1. 改动最小。

缺点：

1. 不会形成明确 owner。
2. 很容易演化成第二个 helper junk drawer。
3. 对后续 repository split 与 runtime split 基本没有帮助。

**结论：选择方案 A。**

---

## 4. 本轮 scope

本轮迁移的 read-side 接口如下：

### 4.1 task 查询

- `list_tasks`
- `get_task`
- `get_task_logs`
- `get_registration_stats`

### 4.2 failure analysis 查询

- `get_registration_failures_summary`
- `get_registration_failures`

### 4.3 batch 查询

- `get_batch_status`
- `get_outlook_batch_status`

### 4.4 service availability 查询

- `get_available_email_services`
- `get_outlook_accounts_for_registration`

### 4.5 本轮不动的 command 接口

- `start_registration`
- `start_batch_registration`
- `start_outlook_batch_registration`
- `cancel_task`
- `delete_task`
- `cancel_batch`
- `cancel_outlook_batch`

说明：

本轮不要求 command route 全部 service 化。当前只要求 **query owner 收口**，避免 read-side 和 command-side 再次耦合。

---

## 5. 目标结构

建议引入以下结构：

```text
src/application/
  registration_query_facade.py
  registration_query_dtos.py

src/web/routes/
  registration.py
```

职责划分如下：

### 5.1 route

只负责：

1. 接收 HTTP 请求。
2. 参数解析与基础校验。
3. 调用 facade。
4. 将 facade 结果返回给 `response_model`。

不再负责：

1. 直接查 DB。
2. 直接访问 `failure_repo`。
3. 直接读 `batch_tasks`。
4. 手工组装 task/failure/service 的 read model。

### 5.2 query facade

负责：

1. registration read-side 用例编排。
2. 从 DB、runtime mirror、settings 组装只读视图。
3. 统一 read-side fallback 语义。
4. 统一 404 / 空集 / 兼容读取策略。

### 5.3 query DTO

负责：

1. 封装 facade 输出结构。
2. 将 route 从 read model 拼装细节中解耦。
3. 为后续 runtime split / repository split 提供稳定契约。

---

## 6. 文件级设计

### 6.1 新增 `registration_query_dtos.py`

建议定义以下 DTO / view：

1. `RegistrationTaskView`
2. `RegistrationTaskListView`
3. `RegistrationTaskLogsView`
4. `RegistrationBatchStatusView`
5. `OutlookBatchStatusView`
6. `RegistrationStatsView`
7. `AvailableEmailServicesView`
8. `OutlookRegistrationAccountsView`
9. `RegistrationFailureSummaryView`
10. `RegistrationFailureListView`

说明：

DTO 可以先保持简单 dataclass / lightweight object，不要求本轮把所有 Pydantic model 都搬出 route。当前阶段的目标是：

**先让 route 不再亲自拼装 read model。**

### 6.2 新增 `registration_query_facade.py`

建议至少暴露以下方法：

1. `list_tasks(...)`
2. `get_task_detail(task_uuid)`
3. `get_task_logs(task_uuid)`
4. `get_registration_stats()`
5. `get_batch_status(batch_id)`
6. `get_outlook_batch_status(batch_id)`
7. `get_available_email_services()`
8. `get_outlook_accounts_for_registration()`
9. `build_failure_summary(...)`
10. `list_failures(...)`

依赖注入建议：

1. `db_factory`
2. `task_manager`
3. `failure_repository`
4. `utc_now_provider`
5. `settings_reader`
6. `batch_tasks_store`

说明：

第一阶段允许 facade 内部继续依赖：

- `crud`
- `failure_repo`
- `task_manager`
- `get_settings`

但这些依赖只能集中在 facade，不再散落在 route。

### 6.3 修改 `registration.py`

需要迁出的 helper / query 逻辑包括：

1. `_step_run_to_dict`
2. `_collect_task_steps`
3. `task_to_response`
4. `_build_failure_filters`
5. `_current_day_intersection_count`
6. `list_tasks`
7. `get_task`
8. `get_task_logs`
9. `get_registration_stats`
10. `get_registration_failures_summary`
11. `get_registration_failures`
12. `get_batch_status`
13. `get_available_email_services`
14. `get_outlook_accounts_for_registration`
15. `get_outlook_batch_status`

迁移后 route 应保留：

1. request/response model
2. route decorator
3. `require_authenticated`
4. 基础 query 参数校验
5. 调 facade 并返回

---

## 7. 关键 read-side 语义

### 7.1 task step fallback

当前 `task` 详情与列表的步骤信息存在两层来源：

1. DB：`PipelineStepRun`
2. runtime mirror：`task_manager.get_task_steps(...)`

本轮要求：

- 该 fallback 语义保留；
- 但必须由 query facade 持有；
- route 不再直接知道“先查 DB、再退到 runtime”。

### 7.2 batch status 读取

当前 batch 状态的真实来源仍是 application-owned store：

- `BatchRegistrationService.batch_tasks`

route 当前直接读取兼容别名：

- `batch_tasks`

本轮要求：

- route 不再直接读 `batch_tasks`
- query facade 持有该读取逻辑
- 当前阶段不强行改 batch owner

### 7.3 failure summary/list

failure read-side 当前包含：

1. 失败时间窗口解析
2. failure filter 归一化
3. “今日失败数”的交集计算语义
4. repository 聚合

本轮要求：

- 这些规则集中到 facade；
- route 只处理输入和 400 映射；
- 不再让 route 成为 failure 规则 owner。

### 7.4 available services

当前邮箱服务 availability 既有：

1. `EmailService` 数据库记录；
2. `settings` fallback（如 custom domain）。

这属于典型 query facade 逻辑。

本轮要求：

- facade 统一组装 availability 视图；
- route 不再自己查 DB + settings 混合拼装。

---

## 8. 错误处理策略

本轮 facade 不直接抛 `HTTPException`，而是：

1. 返回明确空结果；
2. 或抛出语义化异常 / `ValueError`；
3. route 负责转换成 HTTP 语义。

推荐规则：

1. task/batch 不存在：facade 返回 `None`，route 转 404。
2. failure window 无效：facade 可抛 `ValueError`，route 转 400。
3. 空结果列表：返回空集合，不抛异常。

这样可以避免 application 层直接依赖 FastAPI。

---

## 9. 测试设计

### 9.1 新增测试

新增：

- `tests/test_registration_query_facade.py`

应覆盖：

1. task list/detail/logs/stats 的只读契约
2. task steps 的 DB 优先 + runtime fallback
3. batch/outlook batch status 的读取契约
4. available services 的 settings fallback
5. failure summary/list 的过滤与时间窗口语义

### 9.2 需要保持通过的回归集

至少应回归：

- `tests/test_registration_batch_routes.py`
- `tests/test_registration_failure_routes.py`
- `tests/test_registration_stream_routes.py`
- `tests/test_realtime_stream_routes.py`
- `tests/test_registration_page_assets.py`
- `tests/test_run_center_page_assets.py`

### 9.3 推荐验证命令

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py \
  tests/test_registration_batch_routes.py \
  tests/test_registration_failure_routes.py \
  tests/test_registration_stream_routes.py \
  tests/test_realtime_stream_routes.py \
  tests/test_registration_page_assets.py \
  tests/test_run_center_page_assets.py -q
```

---

## 10. 风险与控制

### 风险 1：facade 变成第二个 mega file

控制方式：

1. 按 read-side 场景分组方法。
2. 不在第一阶段继续塞 command 逻辑。
3. 必要时允许 facade 内部再拆 task/failure/service 子 helper。

### 风险 2：route 虽然调用 facade，但旧 helper 没删干净

控制方式：

1. 只要归属 read-side，就整体迁走。
2. 不保留一半 helper 在 route、一半在 facade。

### 风险 3：顺手碰到 repository split / runtime split

控制方式：

1. 本轮 facade 内部允许继续依赖旧 `crud` / `task_manager`。
2. repository split 与 runtime split 留给下一阶段。

### 风险 4：response JSON 漂移

控制方式：

1. 以现有 route tests 为契约。
2. facade 输出字段结构要与当前 response_model 对齐。

---

## 11. 完成标准

本轮完成后，应满足：

1. `registration.py` 中的 read-side endpoint 不再直接调用 `crud` / `failure_repo` / `batch_tasks`。
2. task/failure/service availability 的 read model 由 facade 统一组装。
3. route 层只剩 adapter 职责。
4. HTTP 响应 JSON 保持兼容。
5. 不影响已完成的 bootstrap foundation。
6. 为下一阶段 repository split 提供稳定 facade 边界。

---

## 12. 下一阶段输入

本轮完成后，下一份计划应紧接着处理：

1. `registration repository split`
2. `runtime / task_manager split`

因为：

- read-side boundary 收完后，write-side 持久化 owner 才能更稳定地下沉到 repository；
- route 不再直接读 runtime store 后，runtime split 也不需要同时兼顾 route 脱脂。

最终目标不是“让 route 看起来更整洁”，而是：

**先把 registration 的 query owner 收清，再为 persistence owner 与 runtime owner 收口创造稳定落点。**
