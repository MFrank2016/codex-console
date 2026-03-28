# codex-console 后端架构整改路线图设计

- 日期：2026-03-28
- 状态：Draft / Approved for spec review
- 目标读者：技术负责人、实施开发者、项目维护者
- 相关仓库：`/root/code-server/workspace/codex-console`

## 1. 背景

当前仓库已经具备 `web / application / core / services / database / scheduler` 等目录分层，但这套分层更多是“目录级存在”，而不是“职责级收口”。随着注册、批量注册、代理调度、失败分析、实时流、工作台 UI 等能力叠加，后端已经出现一组稳定复现的结构性问题：

1. Route 层持续承担业务编排、状态推进与页面读模型拼装。
2. Application service 开始承担 owner 角色，但仍裹挟大量执行细节与集成细节。
3. Core 层并不纯，历史主链路直接碰持久化、日志、副作用与运行态。
4. `crud.py` 充当数据库总入口，导致 repository 边界迟迟长不出来。
5. `task_manager` 同时承担运行态缓存、stream 事件总线与 websocket hub，形成运行时中枢。
6. 单任务、普通批量、Outlook 批量存在重复编排，改一条链路并不一定覆盖另一条。
7. 配置体系在 DB 持久化、env 覆盖、启动参数之间仍有语义混杂。

因此，这次工作不应定义为“拆几个大文件”，而应定义为：

**在不更换现有技术栈的前提下，把后端的 owner 关系重新收口，并以此倒推分阶段整改路线。**

---

## 2. 已确认约束

本轮设计已通过讨论明确以下约束：

1. 交付物是**后端架构整改路线图**，不是一次性实现方案。
2. 分析视角采用**理想架构导向**：先给出最佳实践目标形态，再倒推迁移路径。
3. **不更换技术栈**：仍以 FastAPI + SQLAlchemy + 当前任务模型为基础。
4. 颗粒度要求落到**文件 / 类 / 函数级**，不能只停留在模块名词层。
5. 本轮不直接进入实现，只输出可用于后续 planning 的设计文档。

---

## 3. 目标与非目标

### 3.1 目标

本次路线图设计要回答清楚以下问题：

1. 在现有技术栈下，理想后端分层应该是什么样。
2. 当前后端距离理想形态的关键断层有哪些。
3. 哪些问题优先级最高，为什么不能按“谁最大先拆谁”处理。
4. 应按什么阶段推进整改，才能兼顾风险、收益与可回归性。
5. 具体到文件 / 类 / 函数，哪些是首批重点治理对象。
6. 哪些历史兼容逻辑应先保留为 facade / wrapper，而不是粗暴删除。

### 3.2 非目标

本轮不包含：

1. 直接改造成前后端分离或独立 SPA。
2. 直接引入 Redis / Celery / Kafka 等新基础设施。
3. 一次性重写 scheduler、pipeline、实时流协议。
4. 在没有 owner 收口前先做“目录整理式重构”。
5. 把所有大文件立刻拆碎，哪怕这会制造更多小屎山。

---

## 4. 理想后端目标形态

在当前技术栈约束下，推荐的目标后端形态是 6 层：

```text
[Boot]
  启动、环境、lifespan、进程装配

[Web Adapter]
  FastAPI route / websocket / request-response schema

[Application]
  用例编排、事务边界、run lifecycle、批量任务协调

[Domain/Core]
  注册流程规则、代理选择规则、pipeline 规则、状态机语义

[Infrastructure]
  repository、SQLAlchemy 持久化、外部服务 client/provider

[Runtime Adapter]
  task manager、scheduler runner、event stream 推送
```

### 4.1 各层职责

**Boot**
- 只负责应用如何启动。
- 处理 env、CLI、lifespan、scheduler 装配。
- 不承载运行期业务配置语义。

**Web Adapter**
- 只负责请求接入、鉴权、参数映射、响应映射。
- 不直接编排业务，不推进 run lifecycle，不拼业务统计。

**Application**
- 是单任务、批任务、Outlook 批量等 use case 的唯一编排层。
- 拥有事务边界。
- 拥有 run lifecycle。
- 协调 repository、runtime adapter、core、provider adapter。

**Domain/Core**
- 只表达注册规则、状态机、代理选择策略、流程语义。
- 不直接碰 Session、route、task_manager。

**Infrastructure**
- 只负责持久化与外部依赖访问。
- repository 负责读写，不偷做业务语义。

**Runtime Adapter**
- 负责执行态镜像、stream 事件、ws 推送、scheduler 执行桥接。
- 不再定义业务状态语义。

### 4.2 必须收口的 4 个 owner

这次整改必须明确 4 个唯一 owner：

1. **配置 owner**：启动配置归 Boot，运行时配置归 Runtime Settings。
2. **事务 owner**：只能是 Application service。
3. **run lifecycle owner**：只能是 Registration / Batch Application Service。
4. **运行态真相源 owner**：数据库是权威；内存态只能是镜像/缓存，不能成为并列真相源。

---

## 5. 当前结构断层地图

### 5.1 层次有名无实

表面上已有 `web / application / core / database / services` 分层，但实际情况是：

- Web 层在编排。
- Core 层在写库。
- Runtime 层在持有业务状态。
- CRUD 层在承载领域语义。
- Service 层还没有完全成为唯一 owner。

### 5.2 Route 越权

以 `src/web/routes/registration.py` 为代表，route 文件同时承担：

1. request 校验
2. application service 构造
3. batch 启动逻辑
4. 页面查询聚合
5. response 塑形
6. 兼容状态桥接

这意味着 route 已经不是 adapter，而是半个 application 层。

### 5.3 Service owner 不彻底

`RegistrationService` 与 `BatchRegistrationService` 已开始承接 run lifecycle，但仍夹杂：

- 任务流执行细节
- proxy retry/pool 细节
- 自动上传后处理
- task_manager 直接协调
- ORM 返回契约兼容细节

说明 service 虽然开始像 owner，但还没有被保护成纯 orchestration 层。

### 5.4 Runtime 真相源分裂

当前至少存在并行状态来源：

1. 数据库中的 task / run
2. `task_manager` 中的 task/batch/run 内存状态
3. batch 相关的 store / cache / 兼容别名

这类结构会稳定制造：
- 重启丢状态
- DB 与 stream 视图不一致
- batch 与 single 语义漂移

### 5.5 持久化边界失控

`src/database/crud.py` 已经演化成数据库总控室：

- 横跨账号、邮箱服务、任务、计划任务、代理、统计、设置等多个领域。
- 写操作和读聚合混杂。
- repository 没按领域生长。
- query 模型和 write 模型没有清晰区分。

### 5.6 主链路重复编排

单任务、普通批量、Outlook 批量都能跑，但编排散落在：

- route
- registration service
- batch service
- registration job
- provider/service 选择逻辑

结果是同类业务存在多套流程树，维护成本持续升高。

---

## 6. 问题优先级排序

本设计按以下标准排序：

1. 是否持续制造回归
2. 是否影响多个子系统
3. 是否阻塞后续拆分
4. 是否能在不换栈前提下稳定落地

据此，优先级如下：

### P0：run lifecycle 与事务边界

- 这是所有状态一致性问题的根因。
- 不先收口，后续拆分都会漂。

### P1：Web / Application 边界失真

- `registration.py` 等 route 文件正在承担用例编排。
- 不瘦 route，后续 service 边界会继续被顶开。

### P2：`crud.py` 型数据库总入口

- 阻塞 repository 和 query service 边界成型。
- 继续在这里加函数只会进一步恶化耦合。

### P3：注册主链路重复编排

- single / batch / outlook batch 的重复编排会制造“修一处漏一处”。

### P4：代理子域与配置子域未模块化

- 重要，但不应抢在前述 owner 问题之前。

---

## 7. 分阶段整改路线图

### Phase 0：立规则，不急着大拆

**目标：** 先冻结坏味道继续扩散。

**动作：**
1. 以 ADR / spec 形式明确 4 个 owner。
2. 立硬规则：
   - route 不直接推进 run / task 关键状态
   - repository 不隐式 commit
   - core 不直接持有 Session 语义
   - task_manager 不定义业务终态规则
3. 补护栏测试：
   - 终态不可回写
   - service 拥有 commit boundary
   - route 不返回危险 ORM 实体
   - single / batch 的关键 checkpoint 顺序一致

**产出：** 架构红线与验证护栏。

**完成判定：**
- owner 边界已写成明确规则，可直接转成 implementation task。
- 至少有一组 focused tests 能验证终态保护、commit ownership、route 不返回危险 ORM 实体。
- 新增需求不再被允许继续把 run 状态推进写回 route / helper。

### Phase 1：收口 run lifecycle 与事务边界

**目标：** 让 Registration / Batch Service 真正成为 owner。

**动作：**
1. 单任务、批任务的 queued / started / running / terminal 只由 application service 推进。
2. `task_manager` 降级为运行态镜像、推送桥、UI 辅助缓存。
3. repository 去掉隐式 commit，service 统一控制事务。
4. service 对外优先返回 DTO / ID / 明确 detach 的对象。

**产出：** 单一状态 owner + 单一事务 owner。

**完成判定：**
- single / batch / outlook batch 的关键 checkpoint 由 application service 统一推进。
- repository 层不再依赖隐式 commit 语义。
- route 消费的是稳定 DTO / ID / 已明确生命周期的对象。

### Phase 2：把 Web 层瘦回 Adapter

**目标：** 让 route 回到 HTTP 门面。

**动作：**
1. 拆 `registration.py` 为 endpoint handler、command mapper、presenter、query facade。
2. 把 start/cancel/query 的编排逻辑下沉到 application service。
3. 把页面聚合查询从 route 中抽到 query service。

**产出：** Web 层不再是半个业务层。

**完成判定：**
- start/cancel/query handler 中不再出现批量编排或状态推进逻辑。
- 页面聚合查询已通过 query facade / presenter 暴露。
- 新接口增加时不需要复制既有 route 中的业务流程代码。

### Phase 3：拆掉 `crud.py` 的数据库总控室模式

**目标：** 按领域建立 repository / query service。

**动作：**
1. 拆出 registration/accounts/settings/proxy/scheduled/email-service 等 repository。
2. 把页面列表、筛选、统计类查询迁到 query service。
3. 用 wrapper/facade 兼容旧 import，避免一次性改爆。

**产出：** 领域化持久化边界。

**完成判定：**
- 新增数据库访问不再默认往 `crud.py` 添加函数。
- 主要领域已有独立 repository 契约，旧调用点通过 facade / wrapper 渐进兼容。
- 页面统计/筛选类查询不再和写模型 repository 混杂。

### Phase 4：净化 Core，并统一注册主链路

**目标：** 让 `register.py`、`registration_job.py` 回到纯业务/执行适配职责。

**动作：**
1. 把 `RegistrationEngine` 退化为 orchestration facade。
2. 围绕 auth flow / verification flow / workspace flow / persistence port 拆分职责。
3. 让 `registration_job.py` 只保留执行适配与标准 outcome 输出。
4. 统一 single / batch / outlook batch 的 orchestration 模板。

**产出：** 主链路可读性与可测试性显著提升。

**完成判定：**
- `RegistrationEngine` 与 `registration_job.py` 的职责边界能被一句话解释清楚。
- single / batch / outlook batch 共享统一 orchestration 模板，而不是复制流程树。
- provider / auth flow / persistence hook 可以被独立测试与替换。

### Phase 4 并行支线：代理与配置子域治理

**前置依赖说明：**
- 这条支线不应抢在 Phase 1 之前执行。
- 至少要先固定 run lifecycle owner、事务 owner 与 route/application 边界，再并行推进代理与配置子域治理。
- 若多人并行推进，代理子域优先依赖 Batch/Registration Service 契约稳定后再切分；配置子域优先依赖 Boot/Runtime 配置边界规则明确后再改启动实现。

**代理子域：**
- 将 `dynamic_proxy.py` 拆为 parser / selector / probe / fetch / policy。

**配置子域：**
- BootSettings 与 RuntimeSettings 彻底分家。
- 解决 DB 持久化、env 覆盖、启动参数之间的语义混杂。

---

## 8. 文件 / 类 / 函数级热点与推荐拆法

### 8.1 `src/web/routes/registration.py`

**现状问题：**
- 既是 route，又是 query assembler、batch starter、presenter。
- `start_batch_registration`、`start_outlook_batch_registration`、`get_available_email_services` 明显越权。

**推荐拆法：**
1. endpoint handlers：只处理 HTTP 接入。
2. command mappers：将 request 映射为 use-case command。
3. query facade：聚合页面读模型。
4. presenter：`task_to_response` 等响应塑形。

**首批必瘦函数：**
- `start_batch_registration`
- `start_outlook_batch_registration`
- `get_available_email_services`

### 8.2 `src/application/registration_service.py`

**现状问题：**
- 方向正确，但 `_run_single_task_sync_impl()` 过胖，混合 checkpoint、DB 回写、task_manager 协调、proxy retry、job 执行、自动上传、异常补偿。

**推荐拆法：**
1. `RunLifecycleCoordinator`
2. `TaskStateWriter`
3. `ProxyExecutionPolicy`
4. `JobExecutionAdapter`
5. `PostSuccessHooks`

**首批必拆函数：**
- `_run_single_task_sync_impl`
- `_run_auto_uploads`

### 8.3 `src/application/batch_registration_service.py`

**现状问题：**
- 已演化成第二套编排系统。
- `run_batch_parallel` 与 `run_batch_pipeline` 维护重复的执行框架。
- `create_batch_tasks()` 暴露 ORM 生命周期细节。
- `batch_tasks_store` 延续了多套真相源问题。

**推荐拆法：**
1. `BatchDefinitionService`
2. `BatchExecutionOrchestrator`
3. `BatchProgressAggregator`
4. `BatchProxyPoolCoordinator`
5. `BatchSummaryQueryService`

**首批必拆函数：**
- `run_batch_parallel`
- `run_batch_pipeline`
- `create_batch_tasks`

### 8.4 `src/web/task_manager.py`

**现状问题：**
- 同时承担 runtime store、stream event bus、websocket hub。
- 状态、事件、传输三层耦合严重。

**推荐拆法：**
1. `RuntimeStateStore`
2. `StreamEventBus`
3. `WebSocketHub`
4. `TaskManager` 暂时保留 facade 以兼容旧调用点。

**首批必拆职责簇：**
- `update_status` / `add_log` / `set_task_steps`
- `update_batch_status` / `add_batch_log`
- `_broadcast_stream_event` / `_finish_websocket_replay`

### 8.5 `src/database/crud.py`

**现状问题：**
- 已是数据库版 monolith。
- 领域边界无法自然生长。

**推荐拆法：**
按领域拆 repository：
- `accounts_repository.py`
- `email_services_repository.py`
- `registration_tasks_repository.py`
- `registration_runs_repository.py`
- `scheduled_runs_repository.py`
- `proxies_repository.py`
- `settings_repository.py`

同时将页面列表/汇总/筛选类逻辑抽到 query service。

### 8.6 `src/core/registration_job.py`

**现状问题：**
- 同时知道 provider config、task 持久化、failure record、pipeline 和 runtime log。
- 处于 core 与 application 的边界混乱地带。

**推荐拆法：**
1. `JobInputResolver`
2. `RegistrationExecutor`
3. `RegistrationPersistenceHooks`
4. `RuntimeContextReporter`

### 8.7 `src/core/register.py`

**现状问题：**
- `RegistrationEngine` 接近 1200 行，是历史核心屎山。
- 将流程、状态、外部交互、持久化都变成对象内部私事。

**推荐拆法：**
1. `AuthFlowSession`
2. `IdentityVerificationFlow`
3. `WorkspaceAuthorizationFlow`
4. `RegistrationPersistencePort`
5. `RegistrationLogger/EventRecorder`

**注意：** 不建议粗暴拆成大量 util 函数。

### 8.8 `src/core/dynamic_proxy.py`

**现状问题：**
- 实际上已经是代理子域，却仍以大工具模块存在。

**推荐拆法：**
- `proxy_request_parser.py`
- `proxy_candidate_parser.py`
- `proxy_probe_service.py`
- `proxy_selection_policy.py`
- `proxy_fetch_service.py`

### 8.9 `src/config/settings.py` + `webui.py`

**现状问题：**
- 文件头声称“完全基于数据库存储”，实现里却仍混合 env fallback 与启动参数语义。
- `_settings` 单例、DB 持久化、env 覆盖、boot parameter 混在一起。

**推荐拆法：**
1. `BootSettings`
2. `RuntimeSettings`
3. `SettingsLoader`
4. `SettingsRepository`

---

## 9. Top 10 具体整改动作

### 9.1 第一批（最小高收益包）

1. 把 run lifecycle 收口到 application service。
2. 明确事务 owner 只能是 application service。
3. 把 `registration.py` 瘦回 HTTP adapter。
4. 把 `BatchRegistrationService` 从大编排器拆成协作组件。

### 9.2 第二批

5. 拆 `TaskManager` 为 store / event bus / websocket hub。
6. 废掉 `crud.py` 的数据库总控室模式，建立领域 repository + query service。
7. 把 `registration_job.py` 收成执行适配器。

### 9.3 第三批

8. 把 `RegistrationEngine` 从大一统对象退化成流程 façade。
9. 将动态代理能力升级成独立子域。
10. 把 BootSettings 与 RuntimeSettings 彻底分家。

---

## 10. 不建议的做法

明确不建议以下路径：

1. 先全面重写 scheduler / realtime 协议。
2. 在 owner 关系没收口前先做目录整理式重构。
3. 一上来硬拆 `register.py` 或 `crud.py`，指望“拆大文件”自然解决边界问题。
4. 一次性删除所有 legacy facade / wrapper。
5. 引入更多中间层名词，但没有配套 owner 规则与验证护栏。

---

## 11. 风险与缓解

### 11.1 风险

1. owner 收口会暴露历史兼容路径对隐式行为的依赖。
2. batch / realtime / proxy 链路具有较高回归敏感度。
3. 直接修改 service 返回契约会影响 route 和前端页面。
4. 大文件拆分过程中，容易把流程语义打散成更难维护的小碎片。

### 11.2 缓解策略

1. 先立测试护栏，再移动 owner。
2. 先 facade/wrapper 兼容，再逐步替换 import。
3. 优先做 focused tests，而不是一次性全量重写。
4. 拆分时围绕业务语义切，而不是围绕代码块长度切。

---

## 12. 验收标准

这份路线图在后续 implementation planning 中应满足以下验收标准：

1. 能明确分出首批实现范围，不需要再重新争论优先级。
2. 能给出基于现有技术栈的阶段性实施计划，而不是理想化重构口号。
3. 能将“先收 owner，再拆结构”落成可执行步骤。
4. 能让后续 plan 具体映射到文件 / 类 / 函数，而不是停留在抽象术语。
5. 不要求一次性清债，而是支持低风险、可验证、可回滚的分批推进。

---

## 13. 最终结论

这次后端治理的核心不是“重写”，也不是“拆大文件”本身，而是：

**先把 owner 收口，再把结构拆开。**

在当前仓库里，真正决定后续可维护性的是下面 4 件事：

1. 谁推进状态。
2. 谁提交事务。
3. 谁保存运行态真相。
4. 谁负责业务编排。

只有这 4 个问题先稳定下来，后续对 route、repository、runtime、engine、proxy 子域的拆分才会是收益递增，而不是持续制造更多结构噪音。
