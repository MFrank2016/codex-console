from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config.settings import get_settings
from ..core.account_survival_dispatcher import (
    AccountSurvivalDispatcher,
    DatabaseAccountSurvivalRepository,
)
from ..database.init_db import initialize_database
from ..web.task_manager import task_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """统一应用启动/关闭流程。"""
    settings = get_settings()

    try:
        initialize_database()
    except Exception as exc:  # pragma: no cover - 启动阶段兜底日志
        logger.warning(f"数据库初始化: {exc}")

    task_manager.set_loop(asyncio.get_running_loop())
    app.state.scheduler_engine.start()

    if getattr(app.state, "account_survival_dispatcher", None) is None:
        app.state.account_survival_dispatcher = AccountSurvivalDispatcher(
            repo=DatabaseAccountSurvivalRepository(),
        )
    app.state.account_survival_dispatcher.start()

    logger.info("=" * 50)
    logger.info(f"{settings.app_name} v{settings.app_version} 启动中，程序正在伸懒腰...")
    logger.info(f"调试模式: {settings.debug}")
    logger.info(f"数据库连接已接好线: {settings.database_url}")
    logger.info("=" * 50)

    try:
        yield
    finally:
        dispatcher = getattr(app.state, "account_survival_dispatcher", None)
        if dispatcher is not None:
            dispatcher.stop()
        app.state.scheduler_engine.stop()
        logger.info("应用关闭，今天先收摊啦")
