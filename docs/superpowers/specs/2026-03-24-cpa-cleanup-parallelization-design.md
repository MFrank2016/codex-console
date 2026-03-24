# CPA 清理并发优化设计文档

- 日期：2026-03-24
- 项目：codex-console
- 主题：CPA 清理任务提速（参考 `chatgpt-register4/auto_pool_maintainer`）

## 1. 背景

当前 `cpa_cleanup` 任务在以下三个关键阶段存在明显串行瓶颈：

1. `src/scheduler/cpa_client.py` 的 fallback 401 探测逐条调用 `api-call`
2. `src/scheduler/cpa_client.py` 的远端失效账号删除逐条调用 `DELETE auth-files`
3. `src/scheduler/runners/cleanup.py` 逐条调用 `crud.mark_account_expired_by_email_and_cpa()`，每条都会单独提交事务

参考 `auto_pool_maintainer` 的实现，401 探测和删除都使用了 `ThreadPoolExecutor` 并发执行，因此当前实现的主要性能差距来自缺少并发执行与批量数据库更新。

## 2. 目标

- 在不改变 `cpa_cleanup` 外部接口与 summary 结构的前提下，显著降低单次清理运行时长
- 新增清理任务的并发控制参数，允许按计划维度调节 probe / delete 并发度
- 保持现有 stop 请求、进度日志、失败统计、最大探测/最大清理数量语义不变

## 3. 非目标

- 不改动 `cpa_refill` / `account_refresh` 的执行模型
- 不引入新的后台进程或分布式调度
- 不改变计划调度中心的整体架构
- 不把并发实现扩展成通用任务线程池框架

## 4. 设计方案

### 4.1 新增清理并发配置项

在 `cpa_cleanup` 计划配置中新增两个可选参数：

- `probe_workers`：fallback 401 探测并发数，默认 `10`
- `delete_workers`：远端删除并发数，默认 `20`

保留现有参数：

- `max_probe_count`
- `max_cleanup_count`

参数语义：

- `max_probe_count` / `max_cleanup_count` 控制处理规模
- `probe_workers` / `delete_workers` 控制执行并发度

### 4.2 CPA client 并发化

#### fallback 401 探测

当远端 `invalid=1` 过滤接口无法直接给出失效标记时，现有实现会退回到 `api-call` 探测。此阶段改为：

- 先准备待探测候选项
- 使用 `ThreadPoolExecutor(max_workers=probe_workers)` 并发发起 `POST /api-call`
- 通过线程安全计数器在 future 完成时汇总 `invalid` 数量与进度
- 保持 `limit` / `max_probe_count` 语义不变：
  - `max_probe_count` 限制最多实际探测多少个候选项
  - `limit` 限制最多返回多少个失效账号

#### 远端删除

把当前逐条 delete 改为：

- 使用 `ThreadPoolExecutor(max_workers=delete_workers)` 并发删除 `name`
- 在 future 完成时汇总成功/失败数量
- 返回结构继续保持 `{deleted, failed}`

### 4.3 本地账号失效批量更新

新增批量 helper，例如：

- `crud.mark_accounts_expired_by_emails_and_cpa(...)`

行为：

- 输入邮箱列表 + `cpa_service_id` + `reason`
- 单条 SQL `UPDATE` 批量更新命中的本地账号
- 单次 `commit()`
- 返回实际更新条数

`cleanup runner` 只负责按批次组织邮箱列表和日志，不再逐条调用会提交事务的 helper。

### 4.4 cleanup runner 调整

`run_cleanup_plan()` 改为：

- 解析新配置项 `probe_workers` / `delete_workers`
- 调用 `probe_invalid_accounts(..., workers=probe_workers)`
- 本地失效同步按批次调用新的 bulk CRUD helper
- 远端删除调用 `delete_invalid_accounts(..., workers=delete_workers)`
- 继续保留 stop-check 与 100 条级别的 staged progress log

## 5. 兼容性与风险控制

- 默认并发值保守，避免瞬时流量过大
- 若配置缺失，则使用默认并发值，保持老计划可继续运行
- 若配置非法，沿用现有 `validate_plan_payload()` 的非负整数校验路径
- 远端删除与 fallback probe 只改内部执行方式，不改外部调用签名语义

## 6. 验收标准

1. `scheduled_tasks.js` 中 `cpa_cleanup` 配置编辑器可展示 `probe_workers` / `delete_workers`
2. `validate_plan_payload()` 能校验两个新字段
3. `cleanup runner` 能将新字段透传给 CPA client
4. fallback probe 与 delete 的测试能证明不再是串行单工实现
5. 本地失效同步改为批量 update，不再逐条 commit
6. 相关测试通过：
   - `tests/test_scheduler_cpa_client.py`
   - `tests/test_scheduler_cleanup_runner.py`
   - `tests/test_scheduler_service.py`
   - `tests/test_scheduled_tasks_page_assets.py`
