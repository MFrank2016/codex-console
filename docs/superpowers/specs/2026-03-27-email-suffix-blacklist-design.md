# 邮箱后缀黑名单设计

- 日期：2026-03-27
- 状态：Draft / Approved-for-spec
- 目标读者：项目负责人、实施开发者、维护者
- 相关仓库：`/root/code-server/workspace/codex-console`

## 1. 背景

当前注册流程在邮箱创建成功后，会直接沿用该邮箱继续执行 OpenAI 注册链路。实际运行中出现了一类稳定失败：

```json
{
  "error": {
    "message": "Sorry, we cannot create your account with the given information.",
    "type": "invalid_request_error",
    "param": null,
    "code": "registration_disallowed"
  }
}
```

这类失败通常意味着**当前邮箱后缀本身存在高风险或已被限制**。如果系统仍持续复用相同后缀，会导致：

1. 单任务反复浪费注册链路时间。
2. 批量任务持续消耗并发和代理资源。
3. 运维侧无法集中查看、人工管理、修正黑名单。

因此需要在系统中新增一套**邮箱后缀黑名单能力**，并将其接入注册任务与设置页管理。

## 2. 目标与非目标

### 2.1 目标

本轮设计需要满足以下目标：

1. 当注册链路返回 `registration_disallowed` 时，自动将**当前邮箱后缀**加入黑名单。
2. 每次获取邮箱后，先检查邮箱后缀是否命中黑名单；若命中则直接放弃该邮箱并重新获取。
3. 自动拉黑后，**当前任务不立即失败**，而是在同一任务内重新启动一轮新的注册尝试。
4. 黑名单仅对**自动生成 / 临时邮箱服务**生效，不影响固定邮箱服务。
5. 提供设置页管理能力，支持黑名单后缀的增删改查与启停。
6. 黑名单具备最基本的审计能力：来源、原因、命中次数、最后命中时间。
7. 改动尽量复用现有 `settings` 页与注册任务架构，不引入额外框架。

### 2.2 非目标

本轮不追求：

1. 对完整邮箱地址做黑名单管理。
2. 支持通配符、正则、父域名自动匹配等复杂规则。
3. 为不同邮箱服务维护独立黑名单分片。
4. 增加批量导入、批量删除等高级管理能力。
5. 改造现有所有注册错误类型的分类体系；本轮只围绕 `registration_disallowed` 落地。

## 3. 范围与作用边界

### 3.1 生效邮箱服务

仅以下邮箱服务启用后缀黑名单检查：

- `tempmail`
- `temp_mail`
- `duck_mail`
- `freemail`
- `moe_mail`

### 3.2 不生效邮箱服务

以下邮箱服务不参与黑名单拦截：

- `outlook`
- `imap_mail`

原因：这两类服务通常对应人工维护账号或固定域名邮箱，误拉黑风险更高，不应由自动机制直接干预。

### 3.3 匹配规则

黑名单只对**邮箱后缀精确匹配**，不做模糊扩展。

规范化规则：

1. 去除首尾空格。
2. 去除前导 `@`。
3. 转为小写。

示例：

- `@BadMail.COM` → `badmail.com`
- `User@BadMail.COM` 提取后缀后 → `badmail.com`

## 4. 总体方案

推荐采用“**独立黑名单表 + 注册任务双层拦截 + 设置页管理卡片**”方案。

### 4.1 核心思想

1. 新增一张专用表 `email_suffix_blacklist`，而不是复用 `settings` 中的大 JSON。
2. 在注册流程里增加两层拦截：
   - **邮箱创建后立刻检查**
   - **建号失败命中 `registration_disallowed` 时自动拉黑**
3. 在任务级调度层完成“自动拉黑后整轮重试”，避免在脏会话中直接换邮箱继续跑。
4. 在设置页“注册配置”区域提供可视化管理。

### 4.2 为什么使用独立表

相比将黑名单存成 `settings` 表中的 JSON 字段，独立表有明显优势：

1. 更适合做 CRUD、筛选、排序和统计。
2. 后续追加 `source`、`hit_count`、`last_hit_at` 不会让结构失控。
3. 避免多人或并发写入时整包 JSON 互相覆盖。
4. 能直接被后端查询与日志联动复用。

## 5. 数据模型设计

### 5.1 新增 `email_suffix_blacklist`

建议字段如下：

- `id`
- `suffix`
- `enabled`
- `source`
- `reason`
- `hit_count`
- `last_hit_at`
- `created_at`
- `updated_at`

字段语义：

1. `suffix`
   - 唯一索引
   - 存储规范化后的后缀，如 `badmail.com`

2. `enabled`
   - 是否生效

3. `source`
   - `manual`
   - `auto_registration_disallowed`

4. `reason`
   - 备注或触发原因

5. `hit_count`
   - 自动命中累计次数

6. `last_hit_at`
   - 最近一次自动命中时间

### 5.2 数据约束

建议约束：

1. `suffix` 非空且唯一。
2. `hit_count` 默认 `0`。
3. `enabled` 默认 `true`。
4. `source` 默认 `manual`。

## 6. 后端领域能力设计

### 6.1 规范化工具

新增两个共享函数：

1. `normalize_email_suffix(value: str) -> str`
2. `extract_email_suffix(email: str) -> str | None`

职责：

- 输入清洗
- 后缀提取
- 降低前后端重复逻辑

### 6.2 CRUD 能力

除了基础 CRUD，还需要两个业务能力：

1. `is_email_suffix_blacklisted(db, suffix) -> bool`
   - 仅检查 `enabled = true` 的记录

2. `upsert_auto_blacklist_suffix(db, suffix, *, reason, source)`
   - 若不存在则创建
   - 若已存在则更新
   - 自动命中时强制将 `enabled` 置为 `true`
   - `hit_count += 1`
   - 更新 `last_hit_at`

之所以自动命中时强制恢复启用，是为了避免用户此前手动禁用后，同一后缀再次持续触发 `registration_disallowed` 却无法真正拦截。

## 7. 注册链路接入设计

### 7.1 第一层：邮箱创建后的即时拦截

当邮箱服务返回邮箱后：

1. 提取邮箱后缀。
2. 判断当前邮箱服务是否属于黑名单生效范围。
3. 若命中黑名单：
   - 记录日志
   - 丢弃该邮箱
   - 重新获取新邮箱
4. 若未命中：
   - 继续执行注册流程

该阶段只影响邮箱获取，不会污染后续会话。

### 7.2 邮箱重取上限

为了防止邮箱池全是坏后缀导致死循环，邮箱获取阶段增加固定上限：

- **最多连续重取 10 次**

超过后直接失败，错误信息示例：

- `连续获取到黑名单邮箱后缀，已停止本次任务`

### 7.3 第二层：`registration_disallowed` 自动拉黑

在建号阶段，如果 OpenAI 返回结构化错误且满足：

- `error.code == "registration_disallowed"`

则执行：

1. 提取当前邮箱后缀。
2. 调用 `upsert_auto_blacklist_suffix(...)` 自动拉黑。
3. 记录任务日志，说明当前后缀已加入黑名单。
4. 抛出一个可识别的“后缀被禁止”型错误给任务调度层。

### 7.4 任务级整轮重试

自动拉黑后，不在当前会话内继续换邮箱，而是由 `run_registration_job` 所在的任务层重新发起**完整新一轮注册尝试**：

1. 新建邮箱
2. 新建会话
3. 重新 OAuth
4. 重走流水线

这样做的原因是：命中 `registration_disallowed` 时已经处于较深的注册阶段，直接复用旧会话换邮箱，容易引入状态污染和难以诊断的问题。

### 7.5 整轮重试次数

整轮重试不新增单独配置，直接复用现有：

- `registration.max_retries`

职责划分如下：

1. **邮箱重取上限 10 次**
   - 用于防止坏邮箱池卡死

2. **`registration.max_retries`**
   - 用于控制自动拉黑后的整轮重新注册次数

## 8. 错误识别与日志设计

### 8.1 识别优先级

优先根据结构化 JSON 识别：

1. `error.code == "registration_disallowed"`

仅当响应无法解析为 JSON 时，才允许后续追加字符串兜底判断。

### 8.2 日志要求

新增以下关键日志：

1. 获取邮箱后发现黑名单：
   - `邮箱后缀 badmail.com 已在黑名单中，重新获取邮箱`

2. 自动拉黑成功：
   - `检测到 registration_disallowed，已将邮箱后缀 badmail.com 加入黑名单`

3. 当前任务整轮重试：
   - `当前任务将使用新邮箱重新尝试注册`

4. 超过邮箱重取上限：
   - `连续获取到黑名单邮箱后缀，已停止本次任务`

## 9. 设置页与 API 设计

### 9.1 页面位置

将黑名单管理放在：

- **设置页 → 注册配置 tab**

不单独新建一级 tab，避免将一个注册控制项做成过重模块。

### 9.2 UI 结构

新增一个管理卡片：

- 标题：`邮箱后缀黑名单`
- 按钮：`+ 新增后缀`

列表列建议：

- 后缀
- 状态
- 来源
- 命中次数
- 最后命中时间
- 备注
- 操作

### 9.3 新增 / 编辑弹窗

字段：

- 后缀
- 是否启用
- 备注

交互规则：

1. 允许用户输入 `@badmail.com`，前后端会统一规范化。
2. 不允许输入空值。
3. 不允许输入完整邮箱地址，如 `foo@badmail.com`。

### 9.4 支持的操作

第一版支持：

- 列表查看
- 新增
- 编辑
- 启用 / 禁用
- 删除

第一版不做：

- 批量导入
- 批量删除

### 9.5 管理 API

建议挂在 `settings` 路由下：

1. `GET /settings/email-suffix-blacklist`
   - 支持 `keyword`
   - 支持 `enabled`
   - 支持 `source`

2. `POST /settings/email-suffix-blacklist`
   - 新增黑名单后缀

3. `PATCH /settings/email-suffix-blacklist/{id}`
   - 更新后缀、备注、启用状态

4. `DELETE /settings/email-suffix-blacklist/{id}`
   - 删除一条记录

接口返回结构延续当前项目列表 / 编辑接口风格，不额外引入新分页协议。

## 10. 实现落点

建议改动位置如下：

1. `src/database/models.py`
   - 新增 `EmailSuffixBlacklist`

2. `src/database/crud.py`
   - 新增黑名单 CRUD 与业务方法

3. `src/core/register.py`
   - 接入邮箱创建后的黑名单检查
   - 接入 `registration_disallowed` 识别

4. `src/core/registration_job.py`
   - 处理自动拉黑后的整轮重试

5. `src/web/routes/settings.py`
   - 增加黑名单管理接口

6. `templates/settings.html`
   - 增加黑名单管理卡片与弹窗

7. `static/js/settings.js`
   - 增加前端 CRUD 与视图交互

## 11. 测试策略

本功能必须按 TDD 落地，至少覆盖三层测试。

### 11.1 模型 / CRUD 测试

覆盖点：

1. 后缀规范化逻辑正确。
2. `@BadMail.COM` 能正确保存为 `badmail.com`。
3. 重复后缀创建会被拒绝或转为友好错误。
4. 自动拉黑时若记录已存在：
   - `enabled` 会被恢复为 `true`
   - `hit_count` 会累加
   - `last_hit_at` 会刷新

### 11.2 注册链路测试

覆盖点：

1. 临时邮箱服务获取到黑名单后缀时会重新获取邮箱。
2. 非临时邮箱服务不会被黑名单拦截。
3. 命中 `registration_disallowed` 时：
   - 当前邮箱后缀会被自动拉黑
   - 同一任务会整轮重试
4. 超过邮箱重取上限时任务正确失败。
5. 超过 `registration.max_retries` 时任务正确失败并保留清晰错误信息。

### 11.3 设置页 / 资产测试

覆盖点：

1. `settings.html` 存在黑名单卡片和弹窗 hook。
2. `settings.js` 存在列表加载、新增、编辑、启停、删除逻辑。
3. 前端会将 `@badmail.com` 清洗为 `badmail.com`。
4. 设置接口返回结构可被前端直接消费。

## 12. 风险与约束

### 12.1 自动重试可能增加任务时长

自动拉黑后继续重试会让单任务整体耗时上升，但这是为了换取更高成功率与更低人工干预成本。通过复用 `registration.max_retries` 可以控制上界。

### 12.2 坏邮箱池可能造成快速失败

如果邮箱池大量后缀已被拉黑，任务会更快触达“邮箱重取上限”。这是预期行为，能够更早暴露邮箱池质量问题。

### 12.3 当前版本只支持精确后缀匹配

若未来出现需要按父域名统一拉黑（例如 `*.badmail.com`），应在后续版本单独设计，不在本轮混入。

## 13. 结论

本设计采用“**独立黑名单表 + 注册链路双层拦截 + 设置页轻量管理**”方案，能够在不破坏现有注册主架构的前提下，解决 `registration_disallowed` 导致的重复浪费问题，并为后续邮箱池治理提供基础设施。
