# codex-console 架构治理与渐进式重构设计

- 日期：2026-03-24
- 状态：Draft / Approved-for-planning
- 目标读者：技术负责人、实施开发者、项目维护者
- 相关仓库：`/root/project/codex-console`

## 1. 背景

当前项目已经具备以下良好基础：

1. 已形成 `web / core / services / scheduler / database` 的基本目录分层。
2. `scheduler` 子系统已经具备较清晰的 `engine / service / runners` 边界。
3. `pipeline` 子系统已经具备 `context / definitions / runner / registry / steps` 的可扩展骨架。
4. 测试覆盖较完整，当前本地基线为 `350 passed`，说明项目具备安全重构窗口。

但随着功能持续叠加，老的注册主链路和运行态管理已经出现明显架构债：

1. 启动配置、环境变量、数据库设置和 CLI 覆盖逻辑互相交织。
2. 注册任务运行态同时散落在数据库、`TaskManager` 内存结构、`registration.py` 中的全局变量里。
3. Route 层直接承担复杂业务编排，`crud.py` 成为超大数据访问总入口。
4. 日志与状态更新事务粒度过碎，默认 SQLite 下后续会越来越吃力。
5. 时间模型、FastAPI 生命周期、Pydantic/SQLAlchemy 新版本兼容项存在集中技术债。
6. 敏感数据存储策略仍偏“可用优先”，不适合长期演进。

本设计目标不是推翻现有工程，而是在**不中断现有功能迭代**的前提下，把项目从“可维护修复版”推进到“可持续演进版”。

---

## 2. 已确认范围

本轮设计已确认采用“**低风险、渐进式重构**”路线，范围如下：

1. 优先治理配置、启动边界和运行态一致性问题。
2. 保持当前 FastAPI + SQLAlchemy + Jinja2 + vanilla JS 技术栈不变。
3. 不进行前后端分离，不引入全新任务队列体系作为前置条件。
4. 不一次性重写 `scheduler` 与 `pipeline`；优先复用其已有清晰边界。
5. 允许新增 `application` / `boot` / `repositories` 等中间层，以消化现有耦合。
6. 所有改造必须以可测试、可回滚、可分批 PR 的方式推进。

---

## 3. 目标与非目标

### 3.1 目标

本轮架构治理必须达成以下目标：

1. 明确“启动配置”和“运行时设置”的职责边界。
2. 将注册任务、批量任务、日志和状态的运行态收敛为单一权威来源。
3. 让 Route 层只负责请求/响应，不再直接编排复杂业务。
4. 让事务边界由应用服务决定，而不是由零散 CRUD 方法隐式决定。
5. 统一时间处理模型，清理主要框架弃用项。
6. 为后续 PostgreSQL 优先部署、外部任务队列接入、配置安全强化预留清晰扩展点。

### 3.2 非目标

本轮不包含：

1. 全量改造成 async ORM。
2. 前后端彻底分离为独立 SPA。
3. 一次性拆完所有大文件。
4. 立即引入 Redis / Celery / Kafka 作为必须前提。
5. 重做 `scheduler` 核心机制。
6. 重写所有邮箱服务实现。

---

## 4. 现状诊断

### 4.1 配置边界混杂

当前 `src/config/settings.py` 名义上是“完全基于数据库存储”，但实际仍混合：

- `.env`
- 环境变量
- CLI 参数
- DB settings
- 默认值

同时 `webui.py` 会把 CLI 覆盖通过 `update_settings()` 写回数据库，导致“本次启动临时覆盖”与“持久化设置修改”语义混淆。README 中对优先级与持久化行为的描述也与代码不完全一致。

### 4.2 运行态存在多个真相源

当前注册链路至少存在三套运行态：

1. 数据库中的 `registration_tasks`。
2. `src/web/task_manager.py` 中的 `_task_status / _batch_status / _log_queues`。
3. `src/web/routes/registration.py` 中的 `running_tasks / batch_tasks`。

结果是：

- 单进程可运行，但边界模糊；
- 多实例扩展困难；
- 进程重启后内存态丢失；
- WebSocket 推送、批量看板、数据库查询容易出现语义不一致。

### 4.3 Web 层承担过重业务编排职责

当前存在多个千行级文件：

- `src/web/routes/registration.py`
- `src/web/routes/accounts.py`
- `src/web/routes/settings.py`
- `src/database/crud.py`
- `src/core/register.py`

其中 Route 层不仅做参数校验，还直接：

- 编排任务流程
- 调用数据层
- 写运行态缓存
- 聚合批量统计
- 处理部分业务规则

这使得边界难以理解，也提高了改动回归面。

### 4.4 事务粒度过碎

当前大量 CRUD 方法内部直接 `commit()`，而注册日志还采用“每条日志一次 DB 写入”的模式。对默认 SQLite 而言，这会放大锁竞争和 I/O 压力，也让真正的事务一致性难以界定。

### 4.5 技术债已经可观测

测试虽全部通过，但 warning 显示：

1. `FastAPI on_event` 已弃用。
2. `Pydantic class Config` 已弃用。
3. `sqlalchemy.ext.declarative.declarative_base` 已弃用。
4. `datetime.utcnow()` 已被标记为不推荐继续使用。

这说明项目功能基线稳，但平台层兼容性债已经累计到需要集中处理的阶段。

---

## 5. 推荐方案

推荐采用“**渐进治理型方案**”。

### 5.1 为什么选渐进治理型

与“先重构运行态”或“直接重建大分层”相比，渐进治理型方案有三个优势：

1. **风险最低**：优先处理启动边界和公共基础设施，可减少后续重构中的变量。
2. **收益递增**：Phase 1 完成后，后续运行态和业务层拆分会更容易收敛。
3. **贴合现状**：当前项目已有较多生产向修复逻辑，不能承受大爆炸式重构。

### 5.2 总体架构目标

改造后建议形成 5 层结构：

1. **Boot 层**
   - 负责 env / CLI / 打包环境差异 / 进程生命周期。
   - 只解决“应用如何启动”。

2. **Web 层**
   - FastAPI route、WebSocket、Jinja 页面入口。
   - 只解决“HTTP / WS 如何接入”。

3. **Application 层**
   - use case / service / orchestration。
   - 负责事务边界、流程编排、状态写入、错误映射。

4. **Domain/Core 层**
   - 注册引擎、pipeline、scheduler 规则、邮箱服务接口。
   - 负责“业务规则如何执行”。

5. **Infrastructure 层**
   - 数据库存取、配置持久化、外部 API 客户端、日志事件存储。
   - 负责“状态落在哪里，外部系统怎么接”。

### 5.3 核心原则

整个改造过程遵循以下原则：

1. **只有一套运行态真相源。**
2. **Route 不直接驱动复杂业务。**
3. **事务边界由应用服务控制。**
4. **启动配置与运行时设置明确分离。**
5. **优先兼容现有测试和现有页面，不做无关重构。**

---

## 6. 分阶段设计

### 6.1 Phase 0：基础收口

目标：先把后续演进的公共障碍清掉。

范围：

1. 引入统一 UTC aware 时间工具。
2. 将 `on_event` 切换到 lifespan。
3. 将 Pydantic 响应模型迁移到 `ConfigDict`。
4. 将 SQLAlchemy base 定义切换到新写法。

收益：

- 减少 warning；
- 为配置与运行态改造提供更稳定的应用生命周期；
- 降低后续升级框架时的技术风险。

### 6.2 Phase 1：配置与启动边界重构

目标：把“应用怎么启动”和“系统运行时可配置项”完全拆开。

设计：

1. 新增 `BootSettings`：
   - host
   - port
   - debug
   - database url
   - access password override
   - data/log 路径

2. `src/config/settings.py` 收敛为 `RuntimeSettings`：
   - 只承载运行期业务配置；
   - 由 DB 持久化；
   - 不再直接负责 CLI 覆盖解释。

3. `webui.py` 不再把 CLI 覆盖写回 DB；
   - CLI / env 只影响本次进程；
   - 若用户要持久化修改，必须通过设置接口或显式管理命令完成。

4. `src/web/app.py` 改造成真正 app factory；
   - import 时不做隐式重初始化；
   - startup/shutdown 统一走 lifespan。

### 6.3 Phase 2：统一注册运行态

目标：消除当前“数据库 + 内存字典 + WebSocket 状态”并存的问题。

设计：

1. 新增“运行记录”概念，可命名为：
   - `registration_runs`
   - `registration_run_events`

2. 运行记录负责承载：
   - 当前状态
   - 触发来源
   - 批量归属
   - 时间戳
   - 结构化日志事件
   - 错误信息

3. `registration_tasks` 保留为业务任务实体；
   `registration_runs` 成为运行态实体。

4. `TaskManager` 不再维护主状态，退化为：
   - 事件广播适配器；
   - WebSocket 连接管理器；
   - optional 的短期缓存层。

5. `batch_tasks` / `running_tasks` 全局变量逐步移除。

### 6.4 Phase 3：应用服务分层

目标：把复杂编排从 Route 层抽出。

设计：

1. 新增 `application` 层：
   - `registration_service`
   - `batch_registration_service`
   - `settings_service`
   - `account_service`
   - `registration_run_service`

2. Route 统一只做：
   - 输入校验
   - 调用 service
   - 映射 response

3. `crud.py` 按领域拆分：
   - `accounts_repository`
   - `registration_repository`
   - `scheduler_repository`
   - `settings_repository`
   - `upload_repository`

4. 保留现有 ORM 模型，先拆访问入口，不先大改表结构。

### 6.5 Phase 4：事务与日志治理

目标：降低 SQLite 压力，并为 PostgreSQL 优先部署铺路。

设计：

1. CRUD helper 从“每个方法直接 commit”转为“应用服务控制 commit”。
2. 注册日志从字符串追加模式升级为结构化事件写入。
3. 高频日志支持批量 flush 或阶段性归档。
4. SQLite 继续兼容，但文档与部署建议逐步转向 PostgreSQL 优先。

### 6.6 Phase 5：安全与基础设施强化

目标：解决敏感数据长期裸存风险。

设计：

1. 对 token / cookies / password / service config 做字段级保护。
2. 真正使用 `encryption_key` 或引入明确的密钥管理适配层。
3. 将“配置对象”与“敏感密钥对象”分层建模。
4. 对导出、日志展示、API 响应中的敏感字段做统一脱敏。

---

## 7. 推荐落地顺序

推荐按以下顺序推进：

1. **Phase 0 + Phase 1**：先把地基铺平。
2. **Phase 2**：统一运行态，解决当前最大结构性隐患。
3. **Phase 3**：拆业务层与仓储层，降低维护成本。
4. **Phase 4 + Phase 5**：补足事务性能和安全能力。

原因：

- 如果不先分清 Boot/Runtime 配置，后面的运行态改造会持续受启动时序影响；
- 如果不先统一运行态，继续拆 Route 层会出现“新代码还得兼容旧状态字典”的双重负担；
- 事务与安全强化放在后半段，能基于更清晰的边界一次性收口。

---

## 8. 关键风险与缓解

### 8.1 风险：一次改动过大导致回归面过宽

缓解：

- 每个 Phase 拆成独立 PR；
- 每个 PR 都要求配套 focused tests；
- 先抽象适配层，再逐步迁移调用方。

### 8.2 风险：运行态改造影响 WebSocket 页面实时体验

缓解：

- 保留 `TaskManager` 作为广播适配器；
- 页面先兼容旧字段，后切换新字段；
- 通过 API 和前端 harness 同步验证。

### 8.3 风险：SQLite 写入开销在迁移期变得更复杂

缓解：

- 在 Phase 2 前先避免新增更多高频 commit 点；
- 结构化事件表尽量简化 schema；
- 为 PostgreSQL 切换预留明确开关和文档。

### 8.4 风险：安全强化会影响已有导出/上传流程

缓解：

- 先统一“解密读取”边界；
- 保持现有接口签名不变；
- 通过 accounts/upload 相关测试逐步验证。

---

## 9. 验收标准

本轮架构治理完成后，应满足：

1. 启动参数、环境变量、DB 设置的优先级与持久化语义明确且文档一致。
2. 注册任务状态查询只有一个权威来源。
3. 新增业务功能默认落在 application/service，而非 route。
4. `crud.py` 不再作为唯一超大数据访问入口继续膨胀。
5. warning 显著下降，测试基线继续保持稳定。
6. 后续如需引入 Redis / worker / PostgreSQL 优先部署时，不需要推翻本轮边界设计。

---

## 10. 建议的里程碑

### M1
完成 Phase 0 + Phase 1。

预期收益：

- 启动行为清晰；
- 生命周期稳定；
- 后续改造不再受配置混杂影响。

### M2
完成 Phase 2。

预期收益：

- 最大架构隐患被清除；
- 状态查询与日志语义统一。

### M3
完成 Phase 3。

预期收益：

- 业务迭代成本明显下降；
- 新需求不再持续堆进 route 大文件。

### M4
完成 Phase 4 + Phase 5。

预期收益：

- 项目从“修复维护版”进入“可持续演进版”；
- 更适合长周期运行与多环境部署。

---

## 11. 结论

本项目当前最适合的不是推倒重来，而是：

> **以配置边界和运行态统一为先导，逐步引入 application/service 分层，并在不打断现有功能的前提下完成架构收口。**

这是风险最低、收益最稳、最符合当前仓库现实状态的路径。
