# codex-console

基于 [cnlimiter/codex-manager](https://github.com/cnlimiter/codex-manager) 持续修复和维护的增强版本。

这个版本的目标很直接: 把近期 OpenAI 注册链路里那些“昨天还能跑，今天突然翻车”的坑补上，让注册、登录、拿 token、打包运行都更稳一点。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

## QQ群

- 交流群: https://qm.qq.com/q/ZTCKxawxeo

## 致谢

首先感谢上游项目作者 [cnlimiter](https://github.com/cnlimiter) 提供的优秀基础工程。

本仓库是在原项目思路和结构之上进行兼容性修复、流程调整和体验优化，适合作为一个“当前可用的修复维护版”继续使用。

## 这个分支修了什么

为适配当前注册链路，这个分支重点补了下面几个问题:

1. 新增 Sentinel POW 求解逻辑  
   OpenAI 现在会强制校验 Sentinel POW，原先直接传空值已经不行了，这里补上了实际求解流程。

2. 注册和登录拆成两段  
   现在注册完成后通常不会直接返回可用 token，而是跳转到绑定手机或后续页面。  
   本分支改成“先注册成功，再单独走一次登录流程拿 token”，避免卡死在旧逻辑里。

3. 去掉重复发送验证码  
   登录流程里服务端本身会自动发送验证码邮件，旧逻辑再手动发一次，容易让新旧验证码打架。  
   现在改成直接等待系统自动发来的那封验证码邮件。

4. 修复重新登录流程的页面判断问题  
   针对重新登录时页面流转变化，调整了登录入口和密码提交逻辑，减少卡在错误页面的情况。

5. 优化终端和 Web UI 提示文案  
   保留可读性的前提下，把一些提示改得更友好一点，出错时至少不至于像在挨骂。

## 核心能力

- Web UI 管理注册任务和账号数据
- 支持批量注册、日志实时查看、基础任务管理
- 支持 `current_pipeline` / `codexgen_pipeline` 双流水线切换与成对实验
- 支持实验批次级别的步骤耗时对比与存活汇总看板
- 支持普通批量注册历史统计记录、详情复盘与 A/B 对比报表
- 支持账号存活自动巡检与手动复查（`healthy` / `warning` / `dead`）
- 支持多种邮箱服务接码
- 支持 SQLite 和远程 PostgreSQL
- 支持打包为 Windows/Linux/macOS 可执行文件
- 更适配当前 OpenAI 注册与登录链路

## 定时任务

- 支持 CPA 清理、CPA 补号、老账号刷新
- 计划触发支持 Cron 和固定频率
- Cron 时区固定为 Asia/Shanghai
- 补号任务支持连续失败自动禁用

## 环境要求

- Python 3.10+
- `uv`（推荐）或 `pip`

## 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

## 环境变量配置

可选。复制 `.env.example` 为 `.env` 后按需修改:

```bash
cp .env.example .env
```

常用变量如下:

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `APP_HOST` | 监听主机 | `0.0.0.0` |
| `APP_PORT` | 监听端口 | `8000` |
| `APP_ACCESS_PASSWORD` | Web UI 访问密钥 | `admin123` |
| `APP_DATABASE_URL` | 数据库连接字符串 | `data/database.db` |

优先级:

`命令行参数 > 环境变量(.env) > 数据库设置 > 默认值`

补充说明:

- 命令行参数和环境变量只覆盖**当前进程**，不会自动写回 settings 数据库。
- 如果你希望长期保存配置，请通过 Web UI 设置页面或明确的管理入口修改。

## 启动 Web UI

```bash
# 默认启动（监听 0.0.0.0:8000，本机可通过 http://127.0.0.1:8000 访问）
python webui.py

# 指定地址和端口
python webui.py --host 0.0.0.0 --port 8080

# 调试模式（热重载）
python webui.py --debug

# 设置 Web UI 访问密钥
python webui.py --access-password mypassword

# 组合参数
python webui.py --host 0.0.0.0 --port 8080 --access-password mypassword
```

说明:

- 推荐通过 `python webui.py` 作为统一启动入口，它会负责 `.env` 加载、数据库初始化、日志初始化等启动前准备工作。
- 不建议在生产环境直接用 `uvicorn src.web.app:app` 替代上述入口，否则可能绕过项目自己的启动装配逻辑。
- `--access-password` 的优先级高于数据库中的密钥设置
- 该参数只对本次启动生效
- 打包后的 exe 也支持这个参数

例如:

```bash
codex-console.exe --access-password mypassword
```

启动后访问:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## Docker 部署

### 使用 docker-compose

```bash
docker compose up -d
```

你可以在 `docker-compose.yml` 中修改环境变量，比如端口和访问密码。

### 使用 docker run

```bash
docker run -d \
  -p 1455:1455 \
  -e WEBUI_HOST=0.0.0.0 \
  -e WEBUI_PORT=1455 \
  -e WEBUI_ACCESS_PASSWORD=your_secure_password \
  -v $(pwd)/data:/app/data \
  --name codex-console \
  ghcr.io/<yourname>/codex-console:latest
```

说明:

- `WEBUI_HOST`: 监听主机，默认 `0.0.0.0`
- `WEBUI_PORT`: 监听端口，默认 `1455`
- `WEBUI_ACCESS_PASSWORD`: Web UI 访问密码
- `DEBUG`: 设为 `1` 或 `true` 可开启调试模式
- `LOG_LEVEL`: 日志级别，例如 `info`、`debug`

注意:

`-v $(pwd)/data:/app/data` 很重要，这会把数据库和账号数据持久化到宿主机。否则容器一重启，数据也可能跟着表演消失术。

补充说明:

- 当前 `Dockerfile` 默认入口就是 `python webui.py`，这也是推荐保留的容器启动方式。
- 如果你只是本地体验或单机临时使用，直接用仓库自带的 `docker-compose.yml` 就够了。

## 使用远程 PostgreSQL

```bash
export APP_DATABASE_URL="postgresql://user:password@host:5432/dbname"
python webui.py
```

也支持 `DATABASE_URL`，但优先级低于 `APP_DATABASE_URL`。

部署建议:

- SQLite 适合本地、单用户、低并发场景。
- 如果需要持续并发注册、批量任务或长期运行，推荐优先使用 PostgreSQL 作为默认部署目标。

安全说明:

- 当前仓库仍包含账号密码、第三方服务密钥等敏感字段的历史兼容存储方式。
- 后续会继续推进字段级保护、脱敏展示和密钥管理硬化；在此之前请谨慎保管数据库、日志和备份文件。

## 生产环境部署建议

如果你准备长期运行、持续批量任务或对外提供公网访问，推荐采用下面这套组合:

- `Docker Compose`
- `PostgreSQL`
- `Nginx / Caddy` 反向代理
- `HTTPS`

推荐原因:

- 项目已经内置 `Dockerfile`，落地和迁移都比较直接
- PostgreSQL 更适合长期运行和并发任务场景
- 反向代理更方便统一处理 HTTPS、域名、WebSocket 和访问控制
- 容器内继续使用 `python webui.py`，可以保留项目自己的启动初始化逻辑

### 推荐的 docker-compose 生产示例

仓库已提供 `docker-compose.prod.yml`，你可以直接使用，或按自己的环境再复制出一份定制版本:

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: codex-console-db
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      TZ: ${TZ:-Asia/Shanghai}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  webui:
    build:
      context: .
    image: codex-console:prod
    container_name: codex-console
    depends_on:
      db:
        condition: service_healthy
    environment:
      WEBUI_HOST: 0.0.0.0
      WEBUI_PORT: 1455
      WEBUI_ACCESS_PASSWORD: ${WEBUI_ACCESS_PASSWORD}
      APP_DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      LOG_LEVEL: info
      DEBUG: "0"
      TZ: ${TZ:-Asia/Shanghai}
    ports:
      - "127.0.0.1:1455:1455"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped

volumes:
  postgres_data:
```

上面这个端口映射刻意用了:

```yaml
ports:
  - "127.0.0.1:1455:1455"
```

这样 Web UI 只监听宿主机本地回环地址，适合交给 Nginx / Caddy 做前置反代，不建议把应用端口直接裸露到公网。

### 推荐的 .env.prod 示例

仓库已提供 `.env.prod.example`，建议先复制:

```bash
cp .env.prod.example .env.prod
```

再按实际环境修改:

```env
POSTGRES_DB=codex_console
POSTGRES_USER=codex
POSTGRES_PASSWORD=请替换成强密码
WEBUI_ACCESS_PASSWORD=请替换成强密码
TZ=Asia/Shanghai
```

### 启动命令

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

查看服务状态:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

查看 Web UI 日志:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f webui
```

### 生产环境注意事项

1. 关闭调试模式  
   保持 `DEBUG=0`，不要在生产环境开启 `--debug` 或热重载。

2. 修改访问密码  
   `WEBUI_ACCESS_PASSWORD` 不要继续使用默认值。

3. 修改默认密钥  
   项目默认的 `webui_secret_key` 只是开发占位值。首次启动并登录后，建议尽快在设置页中修改。

4. 使用公网域名时加 HTTPS  
   不建议直接将应用端口暴露到公网，应通过 Nginx / Caddy 终止 TLS 并转发到本机 `1455`。

5. WebSocket 需要反向代理支持  
   项目使用了 `/ws/task/...` 和 `/ws/batch/...`，反向代理时记得保留 Upgrade / Connection 头。

6. OAuth 回调地址要改成公网地址  
   如果你在生产环境使用 OpenAI OAuth 回调，默认的 `http://localhost:1455/auth/callback` 不够用，需要改成你的公网 HTTPS 地址，例如:

   ```text
   https://your-domain.com/auth/callback
   ```

7. 做好备份  
   至少定期备份下面这些数据:
   - PostgreSQL 数据卷 `postgres_data`
   - `data/`
   - `logs/`

### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:1455;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

上线前再为域名配置 TLS 证书即可。

## 打包为可执行文件

```bash
# Windows
build.bat

# Linux/macOS
bash build.sh
```

Windows 打包完成后，默认会在 `dist/` 目录生成类似下面的文件:

```text
dist/codex-console-windows-X64.exe
```

如果打包失败，优先检查:

- Python 是否已加入 PATH
- 依赖是否安装完整
- 杀毒软件是否拦截了 PyInstaller 产物
- 终端里是否有更具体的报错日志

## 项目定位

这个仓库更适合作为:

- 原项目的修复增强版
- 当前注册链路的兼容维护版
- 自己二次开发的基础版本

如果你准备公开发布，建议在仓库描述里明确写上:

`Forked and fixed from cnlimiter/codex-manager`

这样既方便别人理解来源，也对上游作者更尊重。

## 仓库命名

当前仓库名:

`codex-console`

## 免责声明

本项目仅供学习、研究和技术交流使用，请遵守相关平台和服务条款，不要用于违规、滥用或非法用途。

因使用本项目产生的任何风险和后果，由使用者自行承担。
