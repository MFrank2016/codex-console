"""
Web UI 启动入口
"""

import logging
import os
import sys
from pathlib import Path

import uvicorn

# 添加项目根目录到 Python 路径
# PyInstaller 打包后 __file__ 在临时解压目录，需要用 sys.executable 所在目录作为数据目录
if getattr(sys, 'frozen', False):
    project_root = Path(sys.executable).parent
    _src_root = Path(sys._MEIPASS)
else:
    project_root = Path(__file__).parent
    _src_root = project_root
sys.path.insert(0, str(_src_root))

from src.boot.settings import BootSettings, set_boot_settings
from src.core.utils import setup_logging
from src.database.init_db import initialize_database
from src.config.settings import get_settings


def _load_dotenv():
    """加载 .env 文件（可执行文件同目录或项目根目录）"""
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def build_boot_settings_from_args(args, *, env: dict[str, str] | None = None) -> BootSettings:
    return BootSettings.from_sources(env=env or os.environ, cli=vars(args))


def setup_application(boot_settings: BootSettings):
    """设置应用程序"""
    _load_dotenv()

    data_dir = project_root / "data"
    logs_dir = project_root / "logs"
    data_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    os.environ.setdefault("APP_DATA_DIR", str(data_dir))
    os.environ.setdefault("APP_LOGS_DIR", str(logs_dir))
    if boot_settings.database_url_override:
        os.environ["APP_DATABASE_URL"] = boot_settings.database_url_override

    try:
        initialize_database()
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        raise

    settings = get_settings(force_reload=True)

    effective_log_level = boot_settings.log_level or settings.log_level
    log_file = str(logs_dir / Path(settings.log_file).name)
    setup_logging(
        log_level=effective_log_level,
        log_file=log_file,
    )

    logger = logging.getLogger(__name__)
    logger.info("数据库初始化完成，地基已经打好")
    logger.info(f"数据目录已安顿好: {data_dir}")
    logger.info(f"日志目录也已就位: {logs_dir}")
    logger.info("应用程序设置完成，齿轮已经咔哒一声卡上了")
    return settings


def start_webui(boot_settings: BootSettings):
    """启动 Web UI"""
    settings = setup_application(boot_settings)
    set_boot_settings(boot_settings)

    from src.web.app import app  # noqa: F401

    effective_host = boot_settings.host or settings.webui_host
    effective_port = boot_settings.port or settings.webui_port
    effective_debug = boot_settings.debug or settings.debug
    effective_reload = boot_settings.reload or effective_debug
    effective_log_level = (boot_settings.log_level or ("info" if effective_debug else "warning")).lower()

    uvicorn_config = {
        "app": "src.web.app:app",
        "host": effective_host,
        "port": effective_port,
        "reload": effective_reload,
        "log_level": effective_log_level,
        "access_log": effective_debug,
        "ws": "websockets",
    }

    logger = logging.getLogger(__name__)
    logger.info(f"Web UI 已就位，请走这边: http://{effective_host}:{effective_port}")
    logger.info(f"调试模式: {effective_debug}")

    uvicorn.run(**uvicorn_config)


def main():
    import argparse

    _load_dotenv()

    parser = argparse.ArgumentParser(description="OpenAI/Codex CLI 自动注册系统 Web UI")
    parser.add_argument("--host", help="监听主机 (也可通过 WEBUI_HOST 环境变量设置)")
    parser.add_argument("--port", type=int, help="监听端口 (也可通过 WEBUI_PORT 环境变量设置)")
    parser.add_argument("--debug", action="store_true", help="启用调试模式 (也可通过 DEBUG=1 环境变量设置)")
    parser.add_argument("--reload", action="store_true", help="启用热重载")
    parser.add_argument("--log-level", help="日志级别 (也可通过 LOG_LEVEL 环境变量设置)")
    parser.add_argument("--access-password", help="Web UI 访问密钥 (也可通过 WEBUI_ACCESS_PASSWORD 环境变量设置)")
    args = parser.parse_args()

    boot_settings = build_boot_settings_from_args(args)
    set_boot_settings(boot_settings)
    start_webui(boot_settings)


if __name__ == "__main__":
    main()
