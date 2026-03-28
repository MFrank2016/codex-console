# registration runs 持久化边界回迁设计

- 日期：2026-03-28
- 状态：Draft / Approved-for-spec
- 目标读者：技术负责人、实施开发者、项目维护者
- 相关仓库：`/root/code-server/workspace/codex-console`
- 参考来源：`feature/arch-refactor-task6-review`（仅作为架构与测试参考源，不作为整体合并目标）

## 1. 背景

当前 `main` 已经持续演进出大量新能力，包括：

1. 注册失败结构化记录与失败分析面板。
2. 邮箱后缀黑名单与相关设置页能力。
3. run-center、realtime log、workspace shell、统一页面壳与多轮 UI 演进。
4. scheduler、refill、proxy observability 等后续能力。

与此同时，保留下来的 `feature/arch-refactor-task6-review` 分支中，仍然包含一批对长期演进有价值的架构改造内容，尤其是：

1. 注册链路的 service 化拆分。
2. registration run 持久化边界与 owner 规则。
3. repository / service / route / task_manager 的职责重划。
4. 事务 ownership 的显式收口。

但该分支相对当前 `main` 已经明显落后，直接整分支合并会产生大规模冲突，且会覆盖当前主线中的大量新增能力。因此需要采用“**以当前 `main` 为基线，按净价值分批回迁**”的方式，把其中高价值的架构边界重新引回主线。

在这条回迁路线中，最值得先处理的不是 UI、也不是 boot/lifespan，而是：

**registration runs 持久化边界。**

原因是这一层：

1. 最能体现旧分支里真正有价值的“架构边界”。
2. 对单任务注册、批量注册、scheduler 都有承接作用。
3. 比 boot/lifespan 和整套路由重写更容易控风险。
4. 能为后续 application service 化提供清晰落点。

---

## 2. 目标与非目标

### 2.1 目标

本轮设计需要达成以下目标：

1. 为 `registration run` 建立清晰的生命周期语义与状态边界。
2. 明确 run 的 owner：谁有权创建、推进、收口 run 状态。
3. 将 run 持久化细节收敛到 repository 层，而不是散落在 route / task_manager / scheduler / 零散 helper 中。
4. 将 run 生命周期语义收敛到 service 层，而不是由多个调用方各自定义。
5. 在不破坏当前 `main` 既有功能的前提下，引入更清晰的 service / repository / transaction ownership 边界。
6. 为后续“单任务注册 service 化”和“批量注册 service 化”提供稳定基础。

### 2.2 非目标

本轮不包含：

1. boot / lifespan / app startup 体系改造。
2. settings service / settings repository 回迁。
3. 整个 route 层的全面重写。
4. UI / 页面 / 模板 / 静态资源回迁。
5. websocket / realtime 协议重构。
6. 把 `feature/arch-refactor-task6-review` 作为整体分支并回 `main`。
7. 一次性重写 task_manager 或 scheduler 全部职责。

---

## 3. 范围与总体方案

推荐采用：

**Repository-first 渐进式回迁方案。**

核心思想：

1. 以当前 `main` 为唯一真实基线。
2. 从旧分支中吸收 `registration run` 的边界设计，而不照搬旧实现整体形态。
3. 先建立新的 `registration runs service + repository` 边界。
4. 先让单任务接入，再逐步让批量与 scheduler 接入。
5. 先做兼容式迁移，再逐步减少旧调用路径。

### 3.1 为什么先迁 run 边界

原因包括：

1. 它是 application service 化的前置基础。
2. 其价值主要体现在架构边界，而不是旧 UI 或旧 route 结构。
3. 它比 boot / lifespan、settings route、旧页面壳更容易切成独立闭环。
4. 它能让后续单任务和批量注册流程共用统一的运行语义。

### 3.2 为什么不整体 merge 旧分支

原因包括：

1. 旧分支与当前 `main` 的直接差异过大，包含大量主线后来新增能力的反向覆盖。
2. 旧分支中的 UI、route、boot、realtime 结构已明显落后于主线。
3. 真正高价值的内容是边界设计，而不是旧分支的整体代码形态。

因此本轮设计明确要求：

> 旧分支只作为“架构与测试参考源”，不作为整体合并目标。

---

## 4. 目标架构与职责分层

本轮回迁后，run 相关职责建议收敛为 4 层：

### 4.1 Route 层

职责：

1. 接收 HTTP 请求。
2. 解析参数。
3. 调用 application service。
4. 返回 HTTP 响应。

不负责：

1. 直接创建或更新 run。
2. 拼装 run 落库细节。
3. 决定 run 生命周期推进规则。

### 4.2 Application Service 层

职责：

1. 拥有 run 生命周期业务语义。
2. 决定何时：
   - 创建 run
   - 标记 started
   - 标记 running/progress
   - 标记 completed / failed / cancelled
3. 协调 route、task_manager、scheduler、job runner。
4. 统一单任务、批量任务、scheduler 触发场景下的 run owner 规则。

代表对象：

- `registration_service`
- `batch_registration_service`
- `registration_runs_service`

### 4.3 Repository 层

职责：

1. 负责 run 的持久化读写。
2. 封装查询、创建、状态更新、日志落库等数据库细节。
3. 提供条件更新能力，例如“仅当当前不是终态时更新”。

不负责：

1. 判断什么时候应该 completed / failed / cancelled。
2. 决定业务流程。
3. 主导事务边界。

### 4.4 Runtime Adapter 层

职责：

1. 暴露运行时事件与执行信号。
2. 对接：
   - `task_manager`
   - `scheduler`
   - job runner
3. 把运行时事件交给 service 解释与持久化。

不负责：

1. 自己定义 run 生命周期语义。
2. 自己主导 run 持久化规则。

---

## 5. run 生命周期模型与状态流转

### 5.1 建议状态集合

第一版统一采用以下状态：

1. `created`
2. `started`
3. `running`
4. `completed`
5. `failed`
6. `cancelled`

### 5.2 建议状态语义

- `created`：run 已创建，但尚未真正开始执行。
- `started`：run 已开始执行，有了明确起点。
- `running`：执行中，允许更新进度、日志、当前步骤等信息。
- `completed`：正常完成。
- `failed`：异常结束。
- `cancelled`：被显式停止或终止。

### 5.3 建议允许的状态流转

主路径：

- `created -> started -> running -> completed`
- `created -> started -> running -> failed`
- `created -> started -> running -> cancelled`

兼容路径：

- `created -> failed`
- `created -> cancelled`
- `started -> failed`
- `started -> cancelled`

禁止路径：

- `completed -> running`
- `failed -> running`
- `cancelled -> running`
- `completed -> failed`
- `failed -> completed`
- `cancelled -> completed`

### 5.4 终态保护规则

第一版明确采用以下硬规则：

1. 一旦进入终态（`completed / failed / cancelled`），普通更新不得把状态改回非终态。
2. 终态更新必须幂等：重复写入相同终态不应破坏状态。
3. 终态后允许补充附加信息（例如日志、结果摘要、错误详情），但不允许恢复执行态。

### 5.5 progress / log 更新规则

在 `running` 阶段允许：

1. 更新进度。
2. 更新当前步骤。
3. 附加日志。
4. 更新结果摘要快照。

在终态阶段允许：

1. 补充最终错误详情。
2. 补充最终结果摘要。
3. flush 晚到日志。

但不允许：

1. 再把状态改回 `running`。
2. 让晚到事件覆盖终态。

---

## 6. owner 规则

### 6.1 单任务注册

owner：`registration_service`

职责：

1. 创建 run。
2. 标记 started。
3. 推进 running/progress。
4. 根据 job 结果收口 completed / failed / cancelled。

### 6.2 批量注册

owner：`batch_registration_service`

职责：

1. 创建批次级 run。
2. 标记 started。
3. 汇总子任务结果。
4. 收口批次级 completed / failed / cancelled。

第一版不要求把所有子任务 run 模型都彻底重构完；本轮先明确“批次 run 的 owner 与状态边界”。

### 6.3 scheduler 触发

scheduler 只是 trigger source，不是 run lifecycle owner。

规则：

1. scheduler 触发对应 service。
2. service 决定 run 状态推进。
3. scheduler 不绕过 service 直接定义 run 终态。

### 6.4 task_manager

task_manager 是运行时协调器 / 事件源，不是 run 持久化 owner。

它可以：

1. 提供运行时状态事件。
2. 提供取消、停止、运行时通知。

但不应：

1. 自己定义 run 生命周期语义。
2. 直接承担最终持久化规则。

---

## 7. repository / service 接口边界与事务 ownership

### 7.1 repository 的职责边界

repository 应该负责：

1. 创建 run 记录。
2. 查询 run。
3. 更新 run 状态字段。
4. 更新 run 元信息。
5. 追加 / 落库 run 相关日志与快照。
6. 执行带条件的状态更新（例如仅当当前非终态时更新）。

repository 不应该负责：

1. 判断何时该 completed / failed / cancelled。
2. 判断失败是否可重试。
3. 决定业务语义。

### 7.2 service 的职责边界

service 应该负责：

1. 决定创建 run 的时机。
2. 决定状态推进是否合法。
3. 决定何时收口 completed / failed / cancelled。
4. 决定需要持久化哪些附加元信息。
5. 统一 route / task_manager / scheduler 的调用入口。

service 不应该负责：

1. 手写底层数据库 update / query 细节。
2. 自己变成 repository。

### 7.3 推荐接口形态

建议 `registration_runs_service` 提供语义化接口，例如：

- `create_run(...)`
- `mark_started(...)`
- `mark_running(...)`
- `record_progress(...)`
- `append_log(...)`
- `mark_completed(...)`
- `mark_failed(...)`
- `mark_cancelled(...)`

建议 repository 提供数据操作接口，例如：

- `create_registration_run(...)`
- `get_registration_run_by_id(...)`
- `update_registration_run(...)`
- `update_registration_run_status_if_not_terminal(...)`
- `append_registration_run_log(...)`

### 7.4 事务 ownership 原则

第一版明确采用：

> **事务 ownership 默认归 application service。**

即：

1. route 不拥有事务语义。
2. repository 默认不 commit。
3. repository 可以 flush，但不拥有最终提交边界。
4. service 决定一次业务操作的提交边界。

### 7.5 终态保护的双层实现

建议双层保护：

1. **service 层保护**：先判断状态是否合法转换。
2. **repository 层保护**：提供条件更新，避免晚到事件覆盖终态。

---

## 8. 单任务 / 批量 / scheduler 的接入方式

### 8.1 单任务接入

建议接法：

1. route 只负责参数校验与调用 service。
2. `registration_service` 创建并推进 run。
3. `registration_runs_service` 负责具体 run 语义与持久化调用。
4. job runner 只负责执行与返回结果，不直接主导 run 生命周期。

### 8.2 批量接入

建议接法：

1. route 触发 `batch_registration_service`。
2. `batch_registration_service` 负责批次 run 的创建、started、running、终态收口。
3. 批次内子任务结果通过 service 汇总，而不是由 route 直接拼装 run 语义。

### 8.3 scheduler 接入

建议接法：

1. scheduler 调用对应 application service。
2. service 负责 run 语义和状态推进。
3. scheduler 负责调度与停止请求，不直接主导 run 终态持久化。

### 8.4 task_manager 接入

建议位置：

- task_manager 保留为运行时协调器 / 事件源
- run 的状态解释与落库由 service 负责

推荐流向：

```text
HTTP / scheduler / runtime trigger
        ↓
      Route
        ↓
Application Service
        ↓
Registration Runs Service
        ↓
   Repository
        ↓
   Database
```

---

## 9. 兼容迁移策略

本轮明确采用：

**兼容式迁移，而不是替换式迁移。**

具体规则：

1. 先建立新的 `registration_runs_service` / repository 入口。
2. 先让单任务调用新入口。
3. 再让批量调用新入口。
4. 最后再逐步收口旧调用路径。

迁移过程中不允许：

1. 整文件替换 route / service / task_manager 为旧分支版本。
2. 通过“整体 merge 旧分支”来获得边界改造。
3. 为了迁移而回退当前 `main` 上的 later features。

---

## 10. 风险与兼容性约束

### 10.1 当前主线能力被覆盖的风险

当前 `main` 已拥有：

- failure analysis
- email suffix blacklist
- refill pipeline 配置
- proxy observability
- run-center / realtime / workspace UI 后续演进

因此第一批必须遵守：

- 只迁边界
- 不迁旧分支整体实现形态

### 10.2 状态时序与日志时序变化风险

风险包括：

1. started / running / completed 写入顺序变化。
2. 晚到日志覆盖终态。
3. scheduler / task_manager / service 对同一 run 的状态口径不一致。

### 10.3 事务 ownership 调整风险

风险包括：

1. 双提交。
2. 漏提交。
3. 同一业务动作被多个调用方分段提交。

### 10.4 过度统一 single / batch / scheduler 风险

第一批不追求彻底统一全部内部结构，只先统一 run 边界与 owner 规则。

### 10.5 UI / realtime 隐式依赖风险

第一批尽量不改 UI 协议，只做 smoke 回归，以保证 run 持久化边界变化不会破坏页面行为。

---

## 11. 验证计划

### 11.1 新增边界验证

重点验证：

1. run 创建。
2. started / running / completed / failed / cancelled 状态推进。
3. 终态保护。
4. 重复终态幂等。
5. 日志与状态写入的边界行为。

### 11.2 持久化验证

重点验证：

1. repository 创建与更新行为。
2. 条件更新不覆盖终态。
3. 事务 ownership 边界。

### 11.3 主流程回归

重点验证：

1. 单任务注册。
2. 批量注册。
3. scheduler 触发相关 run 记录。
4. task_manager 状态协同。

### 11.4 页面 smoke 回归

重点验证“不坏”：

1. run-center。
2. registration page assets。
3. scheduled tasks page assets。

---

## 12. 完成标准

第一批完成时，至少要满足：

1. `registration run` 的 owner 明确。
2. run 持久化不再由 route 零散直写。
3. 单任务至少一条主链路接入新边界。
4. 终态保护测试通过。
5. 主流程回归通过。
6. 页面 smoke tests 不回退。

若只做到“抽出一层代码”，但没有完成以上验证，不算本批完成。

---

## 13. 后续路线承接

本设计完成后，为后续批次提供基础：

1. 第二批：单任务注册 service 化。
2. 第三批：批量注册 service 化。
3. 第四批：settings service / repository 边界。
4. 第五批：boot / lifespan / config 边界。

本设计不试图提前解决这些批次的问题，只要求为它们建立稳定承接面。

---

## 14. 推荐结论

本轮推荐结论如下：

1. 将 `feature/arch-refactor-task6-review` 视为**架构参考源**，而不是可直接合并分支。
2. 第一批回迁只聚焦 **registration runs 持久化边界**。
3. 采用 **Repository-first 渐进式回迁方案**。
4. 坚持 **兼容式迁移**，避免替换式重构。
5. 优先保留边界设计，其次才是旧实现细节。

本设计的核心落点可概括为：

> **run 的业务语义归 service，持久化归 repository，事务 ownership 归 application service；route / task_manager / scheduler 不再各自散写 run 语义。**
