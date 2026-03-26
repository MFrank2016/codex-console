# 注册工作台与定时任务统一实时日志同步设计文档

- 日期：2026-03-26
- 状态：Approved-for-planning
- 目标读者：产品负责人、实施开发者、项目维护者
- 当前仓库：`codex-console`

## 1. 背景

用户本轮明确反馈：

1. 注册工作台的任务日志“仍旧没有实时展示”，需要彻底分析并修复。
2. 定时任务运行日志当前也缺少真正的实时同步能力。
3. 两类页面都需要统一使用 WebSocket 做实时日志数据同步。
4. 如有必要，可以进行有边界的重构。
5. 统一后的前端日志控制台不仅要共用底层链路，还要共用 UI 组件与状态管理。
6. 日志展示要更紧凑，提高信息密度，并按当前主题自动调整 INFO / WARN / ERROR 的文字颜色。

在澄清过程中，用户进一步确认了以下关键选择：

1. 范围选择 **B**：注册工作台 + 定时任务日志统一收口。
2. 同步策略选择 **A**：WebSocket 为主，HTTP snapshot / replay / 补偿兜底。
3. 前端范围选择 **A**：统一成完整日志控制台，不只是统一底层链路。
4. 日志布局选择 **A**：默认采用紧凑列式布局。
5. INFO / WARN / ERROR 必须使用不同文字色，并跟随亮色 / 暗色主题自动切换色调。

因此，本轮并不是单纯“修一条 WebSocket”或“给定时任务加轮询”，而是要把 **注册工作台与定时任务的实时日志模型、传输协议、前端控制台组件** 一次性收口，解决“看不到实时日志”“日志状态机分裂”“不同页面各自维护一套控制台”的结构性问题。

---

## 2. 当前问题分析

## 2.1 注册工作台现状

当前注册工作台已经具备部分实时事件流基础：

1. 后端已有 task / batch stream 缓冲、`seq` 游标、WebSocket 回放与 pending flush 机制。
2. 前端已有 `registrationStream.reduce(...)` 形式的最小状态机。
3. 单任务与批量任务都已经部分使用 snapshot + WebSocket 的消费方式。

但当前仍然存在三个问题：

1. **实时状态与 DOM 直写并存**：页面仍保留 `addLog(...)` / `appendLogLine(...)` 这类直接操作日志 DOM 的旧逻辑。
2. **回放 / 补偿 / 终态处理割裂**：WebSocket、fallback polling、旧日志渲染路径并存，状态来源不唯一。
3. **控制台能力分散**：注册工作台日志区仍是简单输出区，尚未升级为统一的专业控制台。

结论：注册工作台不是“完全没有 WebSocket”，而是 **已有事件流基础，但没有彻底收口为单一实时模型**。

## 2.2 定时任务现状

定时任务运行日志目前仍是典型轮询架构：

1. `append_run_log(...)` 只负责写数据库中的文本日志。
2. 前端通过 `/scheduled-runs/{run_id}/logs?offset=...` 轮询拉取增量文本块。
3. 日志控制台虽然已有搜索、过滤、换行、复制等能力，但其数据源仍然是 HTTP chunk 轮询，而不是 WebSocket 实时流。

这导致：

1. 当前只能做到“准实时”，无法做到真正实时。
2. 轮询间隔越短，服务器开销越高；间隔越长，展示越滞后。
3. 实时链路与注册工作台完全不统一，前端与后端都形成双轨制。

## 2.3 跨页面统一性问题

当前两类页面的实时日志能力存在三层割裂：

1. **协议层割裂**：注册页主要消费 stream 事件；定时任务主要消费 offset chunk。
2. **状态层割裂**：注册页使用 reducer；定时任务使用独立 console state。
3. **UI 层割裂**：注册页是简单 log line；定时任务是另一套控制台结构。

这正是“用户感觉日志仍不实时”的核心原因：**虽然局部功能存在，但整体不是一个统一、可恢复、可补偿的实时日志系统。**

---

## 3. 目标与非目标

## 3.1 本轮目标

本轮必须完成以下目标：

1. 为注册工作台与定时任务运行日志建立统一的实时流模型。
2. 以 WebSocket 为主链路，提供真正的实时日志增量推送。
3. 在 WebSocket 断线、回放游标过期等场景下，通过 HTTP snapshot / replay 进行补偿。
4. 将两类页面统一到一套日志 store 与日志控制台组件。
5. 将日志控制台升级为高密度紧凑列式布局。
6. INFO / WARN / ERROR 文本色按主题自适应：亮色主题偏深色、暗色主题偏亮色。
7. 保留现有页面主体业务交互：
   - 注册工作台仍展示单任务步骤进度 / 批量统计。
   - 定时任务日志弹窗仍保留运行状态栏与停止按钮。
8. 在不引入额外基础设施（Redis、MQ、Kafka 等）的前提下，基于当前仓库完成渐进式落地。

## 3.2 非目标

本轮不包含以下内容：

1. 重写数据库日志存储结构，不将日志拆成独立日志表。
2. 将项目迁移到 React / Vue 或前后端分离架构。
3. 为所有历史页面统一接入实时流，本轮只覆盖：
   - 注册工作台
   - 定时任务运行日志
4. 引入全文检索、服务端日志搜索或日志聚合平台。
5. 改造注册、调度业务本身的核心业务流程。
6. 为定时任务实现完整的“结构化历史日志查询 API”替代现有 chunk 接口。

---

## 4. 方案对比与最终结论

本轮评估三种设计路线：

## 4.1 方案 A：扩展现有 realtime stream 基础设施并统一日志系统（已批准）

核心思路：

1. 复用现有 `task_manager` / `realtime_streams` / WebSocket replay 机制。
2. 新增 `run:{run_id}` stream，使定时任务运行日志进入同一实时体系。
3. 抽出统一前端 `stream client + log store + log console`。
4. 注册工作台与定时任务页面共用一套实时同步基础设施与日志控制台组件。

优点：

1. 最大化复用注册工作台已有实时事件流基础。
2. 改动范围可控，适合“彻底修复 + 有边界重构”。
3. 能同时解决注册日志不实时与定时任务不实时两类问题。

缺点：

1. 需要对现有前端日志消费逻辑做系统收口。
2. 需要补充一批 WebSocket / replay / UI 统一相关测试。

## 4.2 方案 B：新建全新 realtime hub，所有实时能力重挂

优点：

1. 理论上架构最纯粹。
2. 长期扩展性最好。

缺点：

1. 改动面最大。
2. 风险最高。
3. 容易将本轮问题从“修复与统一”演化为“大型基础设施重构”。

## 4.3 方案 C：仅补定时任务 WebSocket，前端表面统一

优点：

1. 交付速度可能更快。
2. 对现有代码侵入较小。

缺点：

1. 后端底层仍然双轨制。
2. 只能部分统一，后续维护成本仍高。
3. 难以称为“彻底修复”。

## 4.4 最终结论

**最终采用方案 A。**

原因如下：

1. 它与用户已经批准的范围完全一致。
2. 它允许复用注册工作台已有 stream 基础，而不是推倒重来。
3. 它能把定时任务补齐到同一套实时模型中。
4. 它能在本轮范围内实现“统一链路 + 统一控制台 + 可恢复补偿”。

---

## 5. 整体架构设计

## 5.1 核心思路

将实时日志能力拆成三个清晰层次：

1. **业务写入层**
   - 注册任务
   - 批量注册
   - 定时任务运行
2. **统一实时流中枢**
   - stream id
   - seq 计数
   - 事件缓冲
   - snapshot 构建
   - replay / pending flush
   - WebSocket 广播
3. **前端统一消费层**
   - realtime log client
   - realtime log store
   - realtime log console

架构示意如下：

```text
RegistrationService / BatchService / SchedulerEngine / SchedulerRunners
                         │
                         ▼
                统一实时流中枢（stream bus）
          ├─ task:{task_uuid}
          ├─ batch:{batch_id}
          └─ run:{run_id}
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
   snapshot / events HTTP           WebSocket live stream
          │                             │
          └──────────────┬──────────────┘
                         ▼
                  realtime log client
                         ▼
                   realtime log store
                         ▼
                 realtime log console UI
```

## 5.2 设计原则

1. **实时优先，持久化保留**：UI 的实时显示以 stream 为准，数据库继续承担历史保存责任。
2. **单一状态源**：所有实时消息先进入统一 store，再由 store 驱动渲染。
3. **补偿可恢复**：断线、回放游标过期、页面重新进入时，都能通过 snapshot / events 正确恢复。
4. **渐进式迁移**：先接入统一基础设施，再删除旧的轮询 / DOM 直写路径。
5. **边界清晰**：控制台 UI、实时 client、业务状态栏解耦，避免页面脚本继续膨胀。

## 5.3 stream 类型

本轮统一支持 3 类 stream：

1. `task:{task_uuid}` —— 注册工作台单任务。
2. `batch:{batch_id}` —— 注册工作台批量任务。
3. `run:{run_id}` —— 定时任务运行日志。

前端统一日志组件只感知“当前 stream 类型与其 snapshot / event 接口”，不再关心它来自哪个页面。

---

## 6. 统一事件模型设计

## 6.1 外层 envelope

所有实时事件统一采用如下格式：

```json
{
  "seq": 12,
  "stream": "run:123",
  "kind": "log_appended",
  "timestamp": "2026-03-26T10:00:00+08:00",
  "payload": {}
}
```

字段含义：

1. `seq`：单 stream 严格递增序号。
2. `stream`：流标识。
3. `kind`：事件类型。
4. `timestamp`：服务端生成时间。
5. `payload`：业务负载。

## 6.2 事件类型

为了兼容现有注册页基础并控制改造风险，本轮仍保留按语义细分的事件类型，而不是在第一阶段强行合并成超级通用事件：

1. `snapshot`
2. `log_appended`
3. `task_status_changed`
4. `task_step_updated`
5. `batch_progress_updated`
6. `run_status_changed`
7. `run_progress_updated`
8. `stream_closed`
9. `snapshot_required`（stream 控制 envelope）

说明：

1. 注册工作台继续沿用 `task_status_changed` / `task_step_updated` / `batch_progress_updated`，减少一次性迁移风险。
2. 定时任务新增 `run_status_changed` / `run_progress_updated`。
3. 前端统一 store 负责把这些事件归一到公共状态树中。
4. 若后续需要继续抽象，可在下一阶段再收口成 `status_changed` / `progress_updated` 这种更通用命名。

## 6.3 统一日志条目结构

无论日志来自注册工作台还是定时任务，进入统一 store 之前都必须被标准化为同一种日志条目结构：

```json
{
  "seq": 12,
  "stream": "run:123",
  "timestamp": "2026-03-26T10:00:00+08:00",
  "display_time": "10:00:00",
  "level": "INFO",
  "message": "cleanup runner start (plan_id=3)",
  "raw": "2026-03-26 10:00:00.123 [INFO] cleanup runner start (plan_id=3)",
  "source": "scheduler"
}
```

字段约定：

1. `seq`：继承当前事件的序号，用于日志去重与顺序恢复。
2. `stream`：当前日志所属 stream。
3. `timestamp`：标准 ISO 时间，用于排序与恢复。
4. `display_time`：前端直接显示的时间列，默认格式 `HH:mm:ss`。
5. `level`：统一使用 `INFO / WARN / ERROR`。
6. `message`：纯正文，不包含时间戳与级别前缀。
7. `raw`：原始文本行，用于复制、兼容显示、问题排查。
8. `source`：可选来源标记，例如 `registration` / `scheduler`。

标准化规则：

1. **定时任务日志**
   - `append_run_log(...)` 已经掌握 `logged_at` 与 `level`，因此事件 payload 直接输出结构化条目。
   - 同时继续保留格式化后的 `raw` 文本写入数据库，兼容现有 chunk 历史接口。
2. **注册工作台日志**
   - 若当前回调链路只提供字符串，则在追加 stream 事件时立即标准化。
   - 若字符串本身不含显式时间与级别，则：
     - `timestamp` 使用事件生成时间；
     - `level` 按现有 `getLogType(...)` 规则映射到 `INFO / WARN / ERROR`，无法明确识别时默认 `INFO`；
     - `message` 使用原始字符串；
     - `raw` 保留原始字符串。
3. **历史尾部窗口**
   - `logs_tail` 不再定义为纯字符串数组，而是定义为“结构化日志条目数组”。
   - 对于历史定时任务日志，如果数据库中只有纯文本行，则在 snapshot / chunk 映射阶段按相同规则解析 / 回填结构化字段。

这意味着统一控制台永远消费结构化日志条目，而不是依赖每个页面自行从纯文本中二次猜测时间与级别。

## 6.4 snapshot 结构

### task snapshot

至少包含：

1. `task`：任务状态与关键字段。
2. `current_step`：当前步骤摘要。
3. `steps`：当前步骤列表。
4. `task_progress`：单任务总步骤进度、当前耗时等。
5. `logs_tail`：最近日志窗口（结构化日志条目数组）。

### batch snapshot

至少包含：

1. `batch`：批量任务状态。
2. `logs_tail`：最近日志窗口（结构化日志条目数组）。

### run snapshot

至少包含：

1. `run`：运行详情核心字段
   - `id`
   - `plan_id`
   - `plan_name`
   - `task_type`
   - `status`
   - `started_at`
   - `finished_at`
   - `stop_requested_at`
   - `is_running`
   - `can_stop`
   - `last_log_at`
   - `log_version`
   - `error_message`
2. `run_progress`：可选执行进度摘要。
3. `logs_tail`：最近日志窗口（结构化日志条目数组）。

## 6.5 `log_appended` payload 约定

`log_appended` 的 `payload` 至少包含：

```json
{
  "entry": {
    "seq": 12,
    "stream": "run:123",
    "timestamp": "2026-03-26T10:00:00+08:00",
    "display_time": "10:00:00",
    "level": "INFO",
    "message": "cleanup runner start (plan_id=3)",
    "raw": "2026-03-26 10:00:00.123 [INFO] cleanup runner start (plan_id=3)",
    "source": "scheduler"
  }
}
```

补充约定：

1. `entry.seq` 与外层 `event.seq` 保持一致，方便组件只依赖日志条目本身去重。
2. 前端控制台渲染只读取 `entry.display_time / entry.level / entry.message / entry.raw`。
3. `raw` 始终作为复制与兜底展示的唯一原文来源。

## 6.6 消息分类与解析规则

统一 realtime client 按以下顺序解析消息：

1. **stream envelope**
   - 条件：消息对象同时包含 `kind` 与 `stream` 字段。
   - 包括：
     - `snapshot`
     - `log_appended`
     - `task_status_changed`
     - `task_step_updated`
     - `batch_progress_updated`
     - `run_status_changed`
     - `run_progress_updated`
     - `stream_closed`
     - `snapshot_required`
2. **连接控制消息**
   - 条件：消息对象包含 `type` 字段。
   - 包括：
     - `{"type":"ping"}`
     - `{"type":"pong"}`
     - `{"type":"cancel"}`（客户端上行）
3. **未知消息**
   - 不参与状态更新；
   - 记录 console warning；
   - 不得导致连接直接崩溃。

这意味着：

1. `snapshot_required` 虽然承担“控制”作用，但它仍属于 stream envelope，因为它必须带 `stream` 语义并参与当前 stream 的重同步流程。
2. `ping/pong/cancel` 才属于纯连接级控制消息。

## 6.7 seq 与 replay 语义

1. `seq` 只在单 stream 内递增，不追求全局有序。
2. 客户端只消费 `seq > lastSeq` 的事件。
3. 若 `after_seq` 已超出缓冲区可覆盖范围，服务端返回 / 推送 `snapshot_required`。
4. 客户端收到 `snapshot_required` 后拉取最新 snapshot，并保留连接继续接收后续 live event。
5. replay 期间产生的新事件进入 pending 队列，等 replay 完成后按 `seq` 顺序 flush，避免丢消息。
6. `logs_tail` 默认取最近 `10` 条，沿用当前系统窗口大小。
7. 前端统一控制台默认保留最近 `500` 条日志条目作为 ring buffer，上限策略为“超出后从头部裁剪最旧条目”。

---

## 7. 后端设计

## 7.1 实时流中枢边界

当前仓库中 `TaskManager` 已经具备大量 stream 基础能力：

1. `append_stream_event(...)`
2. `get_stream_events_after(...)`
3. WebSocket 状态管理
4. replay / pending flush
5. task / batch snapshot 构建

本轮不另起全新基础设施，而是做“**有边界的收口式重构**”：

1. 将现有 stream 能力继续作为统一实时流中枢的核心。
2. 在命名和职责上把“任务语义”与“流语义”拆清楚。
3. 为 scheduler run 增加完整的第三类 stream 支持。

可以接受的实现方式包括：

1. 继续保留 `TaskManager` 类，但把通用 stream 逻辑抽成独立 helper / mixin / module。
2. 或者在 `TaskManager` 中新增 run stream 相关能力，并将共用逻辑整理为更清晰的方法边界。

本轮要求的是**职责清晰**，而不是必须完成一个彻底重命名的大重构。

## 7.2 新增 run stream 支持

后端新增：

1. `run_stream_id(run_id)`
2. `build_run_stream_snapshot(run_id)`
3. `run_stream_exists(run_id)`
4. `broadcast_run_stream_event(run_id, event)`
5. `send_run_stream_event(...)`
6. `finish_run_websocket_replay(...)`
7. `register_run_websocket(...)`
8. `unregister_run_websocket(...)`

这样定时任务运行日志就与 task / batch 一样支持：

1. snapshot
2. events after seq
3. WebSocket replay
4. live push
5. stream closed

## 7.3 定时任务日志写入链路

`append_run_log(...)` 由“仅落库”升级为：

1. 先把格式化后的日志行写入数据库。
2. 基于 `logged_at + level + message + raw` 构造结构化日志条目。
3. 成功后向 `run:{run_id}` stream 追加 `log_appended` 事件。
4. 如果事件循环可用，则立即广播给当前连接的 WebSocket 客户端。

这样数据库仍是事实来源，但 UI 的实时性不再依赖轮询数据库。

## 7.4 定时任务状态与收尾事件

调度引擎 / runner 需要补齐以下事件：

1. 运行开始时：`run_status_changed(status=running)`
2. 停止请求时：`run_status_changed(status=stopping)`
3. 运行成功时：
   - `run_status_changed(status=success)`
   - `stream_closed(final_status=success)`
4. 运行失败时：
   - `run_status_changed(status=failed)`
   - `stream_closed(final_status=failed)`
5. 用户取消时：
   - `run_status_changed(status=cancelled)`
   - `stream_closed(final_status=cancelled)`

如调度执行过程中已有清晰的阶段 / 汇总信息，可择机补充 `run_progress_updated`；但该事件不是本轮上线阻塞项。

运行状态枚举以当前系统可感知集合为准，统一按以下取值规划：

1. `running`
2. `stopping`
3. `success`
4. `failed`
5. `cancelled`

其中 `success / failed / cancelled` 为终态，`stream_closed.final_status` 也必须落在这三个终态集合内。

## 7.5 HTTP 接口

建议新增统一 realtime stream 路由族：

1. `GET /api/realtime-streams/task/{task_uuid}/snapshot`
2. `GET /api/realtime-streams/task/{task_uuid}/events?after_seq=...`
3. `GET /api/realtime-streams/batch/{batch_id}/snapshot`
4. `GET /api/realtime-streams/batch/{batch_id}/events?after_seq=...`
5. `GET /api/realtime-streams/run/{run_id}/snapshot`
6. `GET /api/realtime-streams/run/{run_id}/events?after_seq=...`

兼容策略：

1. 旧的 `registration/streams/*` 路由先保留，可内部转到新实现。
2. 旧的 `/scheduled-runs/{run_id}/logs` chunk 接口继续保留，用于加载完整历史日志。
3. `GET .../events?after_seq=...` 统一返回：

```json
{
  "stream": "run:123",
  "events": [ ... ]
}
```

且首轮不增加分页参数，默认返回“缓冲区内所有 `seq > after_seq` 的事件”；真正的数量边界由服务端缓冲区大小控制。

## 7.6 WebSocket 路由

保留并统一以下路由：

1. `WS /api/ws/task/{task_uuid}`
2. `WS /api/ws/batch/{batch_id}`
3. `WS /api/ws/run/{run_id}`

三者协议完全一致，且首轮实现采用 **URL query 携带 `after_seq`** 的方式，不引入“连接成功后再发订阅命令”的第二套握手：

1. 客户端连接形式固定为：
   - `/api/ws/task/{task_uuid}?after_seq=123`
   - `/api/ws/batch/{batch_id}?after_seq=456`
   - `/api/ws/run/{run_id}?after_seq=789`
2. 服务端 `accept` 后立即读取 URL query 中的 `after_seq`。
3. 若 `after_seq` 可覆盖，则先 replay `seq > after_seq` 的事件，再切换到 live 模式。
4. 若 `after_seq` 已过期，则服务端发送：

```json
{
  "stream": "run:123",
  "kind": "snapshot_required",
  "payload": { "reason": "after_seq_expired" }
}
```

5. 发送 `snapshot_required` 时 **连接保持不断开**；客户端必须：
   - 立刻拉取最新 snapshot；
   - 用 snapshot 重建当前窗口；
   - 保留当前 WebSocket 继续接收后续 live event。
6. 在客户端进入 `snapshot_required` 重同步期间：
   - 现有连接继续接收 live event；
   - 所有新到达且 `seq > currentCursor` 的 stream envelope 先进入 `resync_pending_queue`；
   - snapshot 拉取完成后，以 `snapshot.seq` 为新的 authoritative cursor；
   - 再将 `resync_pending_queue` 中 `seq > snapshot.seq` 的事件按序重放并清空队列。
   - 这样可以避免“拉 snapshot 的同时又收到了新日志”导致的覆盖或丢失。
6. 心跳仍使用现有控制消息：
   - 客户端发 `{"type":"ping"}`
   - 服务端回 `{"type":"pong"}`
7. 取消类动作仍复用现有控制消息，不额外引入新的订阅协议。
8. 终态时广播 `stream_closed`，客户端据此停止重连与等待状态。

## 7.7 snapshot 边界

snapshot 只包含“当前可展示窗口”，不承载全部历史：

1. 注册工作台：返回当前状态、步骤与 `logs_tail` 即可。
2. 定时任务：返回运行状态摘要 + `logs_tail`。
3. 完整历史日志继续由 `/scheduled-runs/{run_id}/logs` chunk 接口提供。

这样可以避免：

1. snapshot 体积过大。
2. 把大量历史日志强塞进 WebSocket / snapshot 流程。

---

## 8. 前端设计

## 8.1 模块拆分

本轮前端统一拆成三层：

### 8.1.1 realtime log client

职责：

1. 建立 WebSocket 连接。
2. 维护心跳。
3. 使用当前 store 中的 cursor 通过 URL query `?after_seq=...` 进行断线重连。
4. 收到 `snapshot_required` 后自动拉 snapshot，并在不关闭现有连接的前提下重建当前视图窗口。
5. WebSocket 失败时降级到 events HTTP 补偿轮询。
6. 对外只抛出标准化事件，不直接操作 DOM。
7. 当处于 `snapshot_required` 重同步阶段时，必须将新到达 live event 暂存到本地重同步队列，待 snapshot 应用后再按 `seq` 合并。

### 8.1.2 realtime log store

职责：

1. 接收所有 stream event。
2. 维护统一状态树：
   - `connection`
   - `cursors`
   - `logs`
   - `task`
   - `taskProgress`
   - `steps`
   - `batch`
   - `run`
   - `runProgress`
3. 做 `seq` 去重。
4. 管理 ring buffer 上限。
5. 管理搜索、过滤、自动滚动、换行等 UI 所需视图状态。

### 8.1.3 realtime log console

职责：

1. 只消费 store 的结构化状态。
2. 渲染高密度日志行。
3. 提供搜索、级别过滤、复制、清空视图、换行、自动滚动等交互。
4. 不直接感知 WebSocket 或 HTTP。

## 8.2 单一数据流原则

本轮必须明确禁止以下旧模式继续扩散：

1. WebSocket 到消息后直接 append DOM。
2. HTTP fallback 也维护另一套独立日志数组。
3. snapshot 与 live event 走不同渲染逻辑。

统一原则是：

```text
所有消息先进入 store
        ↓
store 统一更新视图状态
        ↓
console 根据 store 渲染 DOM
```

这条原则是“彻底修复仍不实时”的关键验收项。

## 8.3 历史日志与实时增量拼接策略

### 注册工作台

注册工作台以实时过程反馈为主：

1. 首次进入时拉 snapshot。
2. 恢复最近日志窗口。
3. 后续通过 WebSocket / events 增量补偿继续更新。

本轮不要求为注册工作台额外新增完整历史日志接口。

### 定时任务

定时任务日志查看以“历史 + 实时尾流”组合模式呈现：

1. 打开日志弹窗时，先通过现有 chunk 接口加载历史日志。
2. 再拉取 snapshot 获取当前状态与最近尾部窗口。
3. 然后建立 WebSocket，接收后续增量。
4. 断线后按 `after_seq` 做 replay 补偿；若游标过期，则重新拉 snapshot 并继续 live。

为避免“chunk 历史无 seq、snapshot/live 有 seq”造成重复，统一采用以下拼接规则：

1. 历史 chunk 日志进入 store 时标记为 `history_entries`，使用本地 `history_key` 标识，不参与 stream cursor 计算。
2. snapshot 返回的 `logs_tail` 视为“当前尾部 authoritative window”。
3. 首次打开日志弹窗时，前端将历史日志拆成两段：
   - `history_prefix`：去除尾部重叠窗口后的历史前缀；
   - `live_window`：以 snapshot `logs_tail` 为准的尾部窗口。
4. 重叠判定方式以结构化条目的 `raw + timestamp + level + message` 为比较键，优先从历史尾部向后匹配 snapshot 尾部，删除重叠后再拼接。
5. 后续 `log_appended` 只追加到 `live_window`，并由 `seq` 去重。
6. 控制台最终渲染顺序为：`history_prefix + live_window`。

这样即使历史 chunk 与 snapshot 尾部存在重叠，也不会因为两条链路的标识方式不同而造成重复展示。

## 8.4 日志控制台布局

统一控制台默认采用 **紧凑列式布局**：

```text
10:21:33  INFO   开始注册任务
10:21:34  WARN   当前代理池为空，回退静态代理
10:21:36  ERROR  获取验证码失败
```

布局要求：

1. 时间列固定宽度。
2. 级别列固定宽度。
3. 消息列占剩余空间。
4. 行高紧凑，提升信息密度。
5. 自动换行关闭时保持单行横向滚动。

## 8.5 控制台统一能力

注册工作台与定时任务日志控制台统一支持：

1. 搜索
2. 级别过滤
3. 自动滚动
4. 自动换行
5. 复制当前可见日志
6. 清空当前视图
7. 连接状态提示
8. 空状态提示
9. 错误状态提示

差异只体现在控制台上方的页面级摘要区域：

1. 注册工作台：步骤进度 / 当前耗时 / 批量统计。
2. 定时任务：run id / 计划名 / 状态 / 最后日志时间 / 停止按钮。

## 8.6 清空视图语义

“清空”只清空前端当前视图，不删除服务端历史日志。

原因：

1. 保持排障可恢复性。
2. 避免用户误以为日志被真正删除。
3. 与当前定时任务日志控制台已有行为保持一致。

---

## 9. 日志样式与主题策略

## 9.1 样式变量

为避免颜色写死在组件内部，统一引入语义化 CSS 变量：

1. `--log-console-bg`
2. `--log-console-border`
3. `--log-console-muted`
4. `--log-info-fg`
5. `--log-warn-fg`
6. `--log-error-fg`
7. `--log-info-bg`（可选，用于 hover / tag 辅助）
8. `--log-warn-bg`（可选）
9. `--log-error-bg`（可选）

## 9.2 主题映射要求

### 亮色主题

使用偏深色调：

1. INFO：深蓝 / 深青系。
2. WARN：深橙 / 棕橙系。
3. ERROR：深红系。

### 暗色主题

使用偏亮色调：

1. INFO：亮蓝系。
2. WARN：亮黄橙系。
3. ERROR：亮红 / 珊瑚红系。

## 9.3 组件类名约束

统一日志行应使用稳定语义类名，例如：

1. `.realtime-log-line`
2. `.realtime-log-time`
3. `.realtime-log-level`
4. `.realtime-log-level-info`
5. `.realtime-log-level-warn`
6. `.realtime-log-level-error`
7. `.realtime-log-message`

这样样式测试与后续局部换肤都更容易维护。

---

## 10. 迁移步骤

## 10.1 第一步：补齐后端 run stream

1. 增加 `run_stream_id(...)` 及其 snapshot / events / websocket 路由。
2. 将 `append_run_log(...)` 接入统一 stream 广播。
3. 在调度引擎和 runner 收尾路径补齐 `run_status_changed` 与 `stream_closed`。

## 10.2 第二步：抽出统一前端实时日志基础模块

1. 从注册页与定时任务页中抽出共用 realtime client。
2. 抽出共用 log store。
3. 抽出共用 log console 组件与样式。
4. 先以“并行接入”的方式替代，不立即删除旧逻辑。

## 10.3 第三步：优先切换定时任务日志页面

优先级先给定时任务，原因如下：

1. 其现状仍完全依赖轮询，收益最直接。
2. 页面边界更清晰，便于观察统一控制台效果。
3. 可先验证 run stream 的整体正确性。

## 10.4 第四步：切换注册工作台日志链路

重点处理：

1. 清理 `addLog(...)` / `appendLogLine(...)` 的 DOM 直写链路。
2. 统一 WebSocket、fallback polling、snapshot 渲染路径。
3. 将日志显示切换到统一控制台组件。

## 10.5 第五步：删除废弃路径

在新链路验证通过后，删除：

1. 重复的日志 DOM 直写逻辑。
2. 注册工作台不再需要的旧日志轮询分支。
3. 定时任务页面不再需要的“实时依赖 offset 轮询”主逻辑。

保留项：

1. `/scheduled-runs/{run_id}/logs` 历史 chunk 接口。
2. 必要的兼容路由别名。

---

## 11. 测试要求

## 11.1 后端测试

至少补充以下验证：

1. `run:{run_id}` stream 的 snapshot / events 路由可用。
2. `append_run_log(...)` 在写库后会追加并广播 `log_appended` 事件。
3. `run_status_changed` 与 `stream_closed` 在终态路径正确触发。
4. replay 期间的新事件不会丢失，pending flush 顺序正确。
5. `after_seq` 过期时会返回 / 推送 `snapshot_required`。
6. 旧 registration stream 接口仍能工作。
7. `/scheduled-runs/{run_id}/logs` 仍可用于历史日志 chunk 加载。

## 11.2 前端测试

### 注册工作台

1. 单任务实时日志会通过统一 store 更新并渲染。
2. 批量任务实时日志会通过统一 store 更新并渲染。
3. snapshot 后不会重复追加日志。
4. 断线重连 / replay 后不会丢日志、不会重复日志。

### 定时任务

1. 打开日志弹窗时先展示历史日志。
2. WebSocket 到达新日志时，控制台立即更新。
3. 搜索 / 过滤 / 复制 / 换行 / 自动滚动在实时追加后仍正常。
4. modal 关闭后应停止对应订阅和 fallback 轮询。

### 统一控制台

1. 使用紧凑列式 DOM 结构。
2. `INFO / WARN / ERROR` 使用稳定语义类名。
3. 空状态、错误状态、连接状态渲染正确。

## 11.3 样式测试

不对具体颜色值做硬编码断言，但至少断言：

1. 存在语义变量：
   - `--log-info-fg`
   - `--log-warn-fg`
   - `--log-error-fg`
2. 存在语义类名：
   - `.realtime-log-level-info`
   - `.realtime-log-level-warn`
   - `.realtime-log-level-error`
3. 控制台样式支持 wrap / nowrap 两种模式。

---

## 12. 风险与控制

## 12.1 风险：历史日志与实时增量重复

控制：

1. 所有实时事件依赖 `seq` 去重。
2. 历史 chunk 与 live event 在 store 中分层合并，不直接做原始文本重复 append。
3. snapshot 语义始终是“重建当前窗口”，而不是“对现有窗口继续追加”。

## 12.2 风险：定时任务日志量过大导致前端性能下降

控制：

1. 控制台使用 ring buffer 或显示窗口上限。
2. 搜索、过滤、复制仅基于当前视图窗口。
3. 完整历史仍通过 chunk 接口按需加载。

## 12.3 风险：注册页改造时牵连现有状态展示逻辑

控制：

1. 先抽共享基础模块，再接入页面。
2. 单任务步骤卡与批量统计卡先保留现有业务展示方式。
3. 最后一步再删除旧日志链路，避免一次性重写过多逻辑。

## 12.4 风险：实时流职责继续堆积在单一文件中

控制：

1. 本轮允许在 `TaskManager` 基础上扩展，但必须整理方法边界。
2. 共用 stream 逻辑应向独立 helper / module 下沉。
3. 不再接受把 run-specific 逻辑散乱拼进现有 task-only 命名的方法中。

---

## 13. 验收标准

满足以下条件即可视为本轮完成：

1. 注册工作台日志在任务运行过程中能够真实实时展示。
2. 定时任务日志不再依赖 offset 轮询作为主实时链路。
3. 注册工作台与定时任务共用一套实时日志基础组件。
4. WebSocket 断线后可以通过 `after_seq` 或 snapshot 补偿恢复。
5. 日志控制台采用统一紧凑列式布局。
6. INFO / WARN / ERROR 文本色可随亮色 / 暗色主题自动调整。
7. 旧历史日志查看能力不受破坏。
8. 页面关闭或流终态后，客户端能正确结束订阅与等待状态。
