# 注册失败记录与失败分析面板设计

- 日期：2026-03-28
- 状态：Draft / Approved-for-spec
- 目标读者：项目负责人、实施开发者、维护者
- 相关仓库：`/root/code-server/workspace/codex-console`

## 1. 背景

当前系统已经具备注册工作台、实时日志、任务状态跟踪、批量注册与多流水线能力，但对于失败案例的留存与分析仍主要依赖：

1. `registration_tasks.error_message` 的最终错误文本。
2. 任务日志中的过程输出。
3. 人工从日志中回看某一次失败时使用的邮箱、代理、用户资料。

这种方式存在几个明显问题：

- 只能较稳定地拿到**最终失败任务**，拿不到“中途失败但后续重试成功”的失败尝试。
- 失败关键信息分散在不同日志与运行态里，不方便做结构化筛选。
- 无法快速回答这类高频问题：
  - 最近哪类邮箱后缀最容易失败？
  - 哪个代理出口 IP 的失败最多？
  - `current_pipeline` 和 `codexgen_pipeline` 的失败画像有什么差异？
  - 哪些姓名/生日组合或邮箱服务更容易触发特定错误？

因此需要引入一套**失败尝试结构化记录能力**，并在注册工作台中增加**失败分析面板**，用于后续查看与分析。

## 2. 目标与非目标

### 2.1 目标

本轮设计需要满足以下目标：

1. 每一次注册失败尝试都要结构化落库，而不只是最终失败任务。
2. 失败记录至少保留以下信息：
   - 邮箱
   - 出生日期
   - 姓名
   - 代理 IP
   - 错误详情
   - 失败时间
3. 同时记录与分析相关的上下文：
   - `task_uuid`
   - `batch_id`
   - `pipeline_key`
   - 注册模式
   - 邮箱后缀
   - 邮箱服务类型
4. 失败记录对以下注册模式统一生效：
   - 单次注册
   - 批量注册
   - 无限注册
   - Outlook 批量
   - `current_pipeline`
   - `codexgen_pipeline`
5. 在注册工作台中新增失败分析面板，支持：
   - 失败摘要卡片
   - 失败记录筛选
   - 失败明细表格
6. 第一版以“结构化记录 + 摘要 + 筛选表格”为主，不追求复杂图表。

### 2.2 非目标

本轮不追求：

1. 引入图表系统（如 ECharts）做失败可视化大盘。
2. 做错误聚类、自动根因推荐、代理质量评分等高级分析。
3. 做独立失败分析新页面；失败分析面板放在注册工作台内即可。
4. 为失败记录增加批量删除、导出 Excel、归档压缩等后台运维能力。
5. 在本轮内重构整个注册日志系统；失败记录只补充结构化分析视角。

## 3. 范围与总体方案

推荐采用“**独立失败记录表 + 任务收口统一记录 + 注册工作台内失败分析面板**”方案。

### 3.1 核心思想

1. 新增独立的失败尝试记录表，而不是把失败分析字段塞进 `registration_tasks.result`。
2. 每一次失败尝试都记录一条结构化记录，即使该任务后续重试成功也保留失败样本。
3. 记录动作统一放在注册任务执行收口链路中，避免散落到不同 step 或前端日志解析中。
4. 注册工作台内新增失败分析区域，直接消费结构化失败记录与聚合摘要。

### 3.2 为什么使用独立表

相比把失败信息塞进 `registration_tasks` 或仅依赖日志，独立表更适合：

1. 精确记录“每一次失败尝试”。
2. 按邮箱后缀、错误码、代理 IP、流水线、时间范围做筛选和聚合。
3. 保留中间失败样本，不受任务最终成功/失败状态覆盖。
4. 为后续失败分析、统计和可能的图表扩展提供干净的数据源。

## 4. 数据模型设计

### 4.1 新增 `registration_failure_records`

建议字段如下：

- `id`
- `task_uuid`
- `batch_id`
- `pipeline_key`
- `registration_mode`
- `email`
- `email_suffix`
- `email_service_type`
- `display_name`
- `birthdate`
- `proxy`
- `proxy_ip`
- `error_code`
- `error_detail`
- `failed_at`
- `created_at`
- `extra_json`

### 4.2 字段含义

1. `task_uuid`
   - 关联当前失败尝试所属任务。

2. `batch_id`
   - 批量、无限、Outlook 批量时用于聚合同批次失败。

3. `pipeline_key`
   - 区分 `current_pipeline` / `codexgen_pipeline`。

4. `registration_mode`
   - 记录当次运行模式：`single / batch / unlimited / outlook_batch`。

5. `email`
   - 本次失败尝试使用的邮箱。

6. `email_suffix`
   - 便于按邮箱后缀聚合分析。

7. `email_service_type`
   - 如 `tempmail / outlook / moe_mail / duck_mail`。

8. `display_name`
   - 本次注册尝试使用的姓名。

9. `birthdate`
   - 本次注册尝试使用的出生日期。

10. `proxy`
    - 当次任务实际使用的代理地址。

11. `proxy_ip`
    - 代理出口 IP；如果拿不到，允许为空。

12. `error_code`
    - 尽量结构化，如：
      - `registration_disallowed`
      - `create_email_failed`
      - `proxy_error`
      - `oauth_failed`
      - `unknown`

13. `error_detail`
    - 原始错误详情、异常消息或 API 返回摘要。

14. `failed_at`
    - 实际失败时间。

15. `extra_json`
    - 用于扩展额外上下文，如失败 step、user info 原始结构、动态代理探测信息等。

### 4.3 约束建议

1. `failed_at` 非空。
2. `error_detail` 非空。
3. `email_suffix` 可空（当邮箱缺失时允许为空）。
4. `proxy_ip` 可空。
5. `task_uuid` 建索引。
6. `batch_id` 建索引。
7. `pipeline_key` 建索引。
8. `registration_mode` 建索引。
9. `email_suffix` 建索引。
10. `failed_at` 建索引。

## 5. 失败记录链路设计

### 5.1 记录粒度

按已确认边界，本轮设计采用：

- **每一次失败尝试都落一条记录**

这意味着：

1. 单次注册失败，记录 1 条。
2. 批量任务里的单个任务失败，记录 1 条。
3. 无限注册中的每次失败，记录 1 条。
4. Outlook 批量中的每次失败，记录 1 条。
5. 中间失败但最终重试成功，也保留之前的失败记录。

### 5.2 统一记录入口

推荐把失败记录入口统一放在：

- `run_registration_job()` 所在的任务执行收口链路

原因：

1. 该入口同时覆盖当前流水线与 `codexgen_pipeline`。
2. 当前已在这里完成失败重试、自动拉黑和结果收口。
3. 在这里记录“每次失败尝试”最容易保证口径统一。

### 5.3 记录时机

建议在以下情形写入失败记录：

1. `RegistrationDisallowedSuffixError` 触发时：
   - 先写一条失败记录
   - 再进入自动拉黑与下一轮整轮重试

2. 一般失败返回 `RegistrationJobResult(success=False, ...)` 时：
   - 写一条失败记录

3. 运行期抛出未捕获异常时：
   - 写一条失败记录
   - 再进入失败收口逻辑

### 5.4 用户资料来源

为了稳定记录“姓名”和“出生日期”，建议把注册尝试使用的用户资料显式挂在运行态上。

推荐在 `RegistrationEngine` / pipeline runtime 中保存：

- `display_name`
- `birthdate`
- 原始 user info

而不是依赖日志反解析。

### 5.5 代理 IP 来源

建议按以下优先级填充 `proxy_ip`：

1. 动态代理探测 / 预检结果里的出口 IP
2. 已分配代理的探测缓存结果
3. 若拿不到则留空

第一版不强求必须完整拿到 `proxy_ip`，但数据模型预留该字段。

## 6. 失败分析面板设计

### 6.1 放置位置

失败分析面板放在：

- **注册工作台内**

不新开独立页面。

### 6.2 页面结构

第一版建议采用：

1. **失败摘要卡片区**
   - 总失败次数
   - 今日失败次数
   - Top 失败邮箱后缀
   - Top 错误类型
   - Top 代理 IP

2. **筛选区**
   - 流水线
   - 注册模式
   - 邮箱服务
   - 邮箱后缀关键词
   - 错误关键词
   - 开始时间
   - 结束时间

3. **失败记录表格区**
   - 失败时间
   - 流水线
   - 模式
   - 邮箱
   - 后缀
   - 姓名
   - 出生日期
   - 代理
   - 代理 IP
   - 错误码
   - 错误详情

### 6.3 第一版交互

第一版只做以下交互：

- 刷新
- 筛选
- 查看完整错误详情

先不做：

- 图表
- 导出
- 批量删除
- 复杂 drill-down

## 7. API 设计

### 7.1 失败摘要接口

新增：

- `GET /api/registration/failures/summary`

返回：

- `total_failed_attempts`
- `today_failed_attempts`
- `top_email_suffixes`
- `top_error_codes`
- `top_proxy_ips`

支持与列表一致的筛选参数，保证摘要与列表口径一致。

### 7.2 失败记录列表接口

新增：

- `GET /api/registration/failures`

支持参数：

- `pipeline_key`
- `registration_mode`
- `email_service_type`
- `email_suffix`
- `error_keyword`
- `started_from`
- `started_to`
- `page`
- `page_size`

返回：

- `total`
- `items`

### 7.3 失败详情接口

第一版不单独新增详情接口。

理由：

- 列表里直接返回完整 `error_detail`
- 前端可直接用弹层/展开查看
- 保持最小实现

## 8. 失败记录写入与错误分类建议

### 8.1 错误码策略

第一版采用“能结构化就结构化，不能结构化就降级”的策略。

建议优先识别：

- `registration_disallowed`
- `proxy_error`
- `create_email_failed`
- `oauth_failed`
- `validation_failed`
- `unknown`

### 8.2 写入内容建议

写失败记录时，至少保留：

- 当前邮箱
- 当前邮箱后缀
- 当前姓名
- 当前出生日期
- 当前代理与代理 IP
- 错误码
- 错误详情
- 当前任务 / 批次 / 流水线 / 模式
- 失败时间

### 8.3 与现有任务状态的关系

失败记录表是**分析视角**，不替代：

- `registration_tasks.status`
- `registration_tasks.error_message`
- 实时日志

它是额外补充的结构化样本库。

## 9. 测试策略

### 9.1 模型 / CRUD 测试

覆盖：

1. 创建失败记录
2. 列表筛选
3. 时间范围筛选
4. 邮箱后缀 / 错误码 / 流水线筛选
5. 摘要聚合正确

### 9.2 注册链路测试

覆盖：

1. 单次失败会落记录
2. `registration_disallowed` 在 retry 前也会落记录
3. 中间失败后成功，仍保留那条失败尝试
4. `current_pipeline` / `codexgen_pipeline` 都能落记录

### 9.3 路由测试

覆盖：

1. `GET /api/registration/failures`
2. `GET /api/registration/failures/summary`
3. 参数过滤
4. 分页
5. 聚合返回结构

### 9.4 前端资产测试

覆盖：

1. 注册工作台模板里存在失败分析面板 hook
2. `app.js` 能请求 summary/list
3. 表格渲染和筛选行为正确

## 10. 实现顺序建议

推荐按以下顺序落地：

1. 数据模型 + CRUD
2. 任务失败记录写入
3. 后端 summary/list API
4. 注册工作台失败分析面板
5. 前端筛选与表格渲染

## 11. 风险与约束

### 11.1 失败记录增长速度

由于“每一次失败尝试都记录”，失败表增长可能较快。第一版接受该成本，后续如有需要再补归档/清理策略。

### 11.2 代理 IP 可能为空

第一版允许 `proxy_ip` 为空，避免因为拿不到出口 IP 而阻塞失败记录写入。

### 11.3 中间失败样本与最终任务状态不一致

这是预期行为。

例如：

- 某任务第一次失败、第二次成功
- 任务最终状态是成功
- 但失败记录表里仍有 1 条失败样本

这正是分析面板需要保留的信息。

## 12. 结论

本设计采用“**独立失败尝试记录表 + 统一任务收口写入 + 注册工作台内失败分析面板**”方案，能够在不重构现有实时日志与任务状态体系的前提下，为注册失败提供结构化留痕和后续分析能力。
