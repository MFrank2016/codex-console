from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from ..boot.settings import get_boot_settings
from ..config.settings import get_settings


def auth_token(password: str) -> str:
    """基于当前 Web UI 密钥生成登录 cookie 值。"""
    secret = get_settings().webui_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, password.encode("utf-8"), hashlib.sha256).hexdigest()


def effective_access_password() -> str:
    """
    统一计算当前进程实际生效的访问密码。

    启动参数/环境变量覆盖优先于数据库配置，
    页面路由与 API 路由都必须共享这套逻辑。
    """
    boot_settings = get_boot_settings()
    if boot_settings.access_password_override:
        return boot_settings.access_password_override
    return get_settings().webui_access_password.get_secret_value()


def is_authenticated(request: Request) -> bool:
    cookie = request.cookies.get("webui_auth")
    expected = auth_token(effective_access_password())
    return bool(cookie) and secrets.compare_digest(cookie, expected)


def require_authenticated(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
