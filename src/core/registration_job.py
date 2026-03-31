from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ..config.constants import EmailServiceType
from ..config.settings import get_settings
from .email_suffix_blacklist import RegistrationDisallowedSuffixError, extract_email_suffix
from .registration_failure_records import build_failure_write_payload, redact_result_payload, write_registration_failure_record
from .time import utc_now_naive
from .pipeline import PipelineContext, PipelineRunner
from .pipeline.errors import PipelineStepExecutionError
from .pipeline.registry import get_pipeline
from .pipeline.steps.current import build_current_runtime
from .pipeline.steps.codexgen import build_codexgen_runtime
from .register import RegistrationEngine
from ..database import crud
from ..database.models import Account, EmailService
from ..services import EmailServiceFactory

logger = logging.getLogger(__name__)
_RUNTIME_CONTEXT_UNKNOWN = "unknown"


@dataclass
class RegistrationJobResult:
    success: bool
    account_id: int | None = None
    email: str | None = None
    error_message: str | None = None
    email_service_id: int | None = None
    result_payload: dict[str, Any] | None = None


def _normalize_email_service_config(
    service_type: EmailServiceType,
    config: dict[str, Any] | None,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    """按服务类型兼容旧字段名，避免不同服务的配置键互相污染。"""
    normalized = config.copy() if config else {}

    if "api_url" in normalized and "base_url" not in normalized:
        normalized["base_url"] = normalized.pop("api_url")

    if service_type == EmailServiceType.MOE_MAIL:
        if "domain" in normalized and "default_domain" not in normalized:
            normalized["default_domain"] = normalized.pop("domain")
    elif service_type in (EmailServiceType.TEMP_MAIL, EmailServiceType.FREEMAIL):
        if "default_domain" in normalized and "domain" not in normalized:
            normalized["domain"] = normalized.pop("default_domain")
    elif service_type == EmailServiceType.DUCK_MAIL:
        if "domain" in normalized and "default_domain" not in normalized:
            normalized["default_domain"] = normalized.pop("domain")

    if proxy_url and "proxy_url" not in normalized:
        normalized["proxy_url"] = proxy_url

    return normalized


def _resolve_email_service(
    *,
    db,
    email_service_type: str,
    email_service_id: int | None,
    proxy: str | None,
    email_service_config: dict[str, Any] | None,
) -> tuple[EmailServiceType, dict[str, Any], int | None]:
    service_type = EmailServiceType(email_service_type)
    settings = get_settings()
    resolved_service_id: int | None = None

    if email_service_id:
        db_service = (
            db.query(EmailService)
            .filter(EmailService.id == email_service_id, EmailService.enabled == True)
            .first()
        )
        if not db_service:
            raise ValueError(f"邮箱服务不存在或已禁用: {email_service_id}")

        service_type = EmailServiceType(db_service.service_type)
        config = _normalize_email_service_config(service_type, db_service.config, proxy)
        resolved_service_id = db_service.id
        return service_type, config, resolved_service_id

    if service_type == EmailServiceType.TEMPMAIL:
        config = {
            "base_url": settings.tempmail_base_url,
            "timeout": settings.tempmail_timeout,
            "max_retries": settings.tempmail_max_retries,
            "proxy_url": proxy,
        }
        return service_type, config, resolved_service_id

    if service_type == EmailServiceType.MOE_MAIL:
        db_service = (
            db.query(EmailService)
            .filter(EmailService.service_type == "moe_mail", EmailService.enabled == True)
            .order_by(EmailService.priority.asc())
            .first()
        )
        if db_service and db_service.config:
            config = _normalize_email_service_config(service_type, db_service.config, proxy)
            resolved_service_id = db_service.id
            return service_type, config, resolved_service_id

        if settings.custom_domain_base_url and settings.custom_domain_api_key:
            config = {
                "base_url": settings.custom_domain_base_url,
                "api_key": settings.custom_domain_api_key.get_secret_value() if settings.custom_domain_api_key else "",
                "proxy_url": proxy,
            }
            return service_type, config, resolved_service_id

        raise ValueError("没有可用的自定义域名邮箱服务，请先在设置中配置")

    if service_type == EmailServiceType.OUTLOOK:
        outlook_services = (
            db.query(EmailService)
            .filter(EmailService.service_type == "outlook", EmailService.enabled == True)
            .order_by(EmailService.priority.asc())
            .all()
        )
        if not outlook_services:
            raise ValueError("没有可用的 Outlook 账户，请先在设置中导入账户")

        selected_service = None
        for service in outlook_services:
            email = service.config.get("email") if service.config else None
            if not email:
                continue
            existing = db.query(Account).filter(Account.email == email).first()
            if not existing:
                selected_service = service
                break

        if selected_service and selected_service.config:
            config = _normalize_email_service_config(service_type, selected_service.config, proxy)
            resolved_service_id = selected_service.id
            return service_type, config, resolved_service_id

        raise ValueError("所有 Outlook 账户都已注册过 OpenAI 账号，请添加新的 Outlook 账户")

    if service_type == EmailServiceType.DUCK_MAIL:
        db_service = (
            db.query(EmailService)
            .filter(EmailService.service_type == "duck_mail", EmailService.enabled == True)
            .order_by(EmailService.priority.asc())
            .first()
        )
        if not (db_service and db_service.config):
            raise ValueError("没有可用的 DuckMail 邮箱服务，请先在邮箱服务页面添加服务")

        config = _normalize_email_service_config(service_type, db_service.config, proxy)
        resolved_service_id = db_service.id
        return service_type, config, resolved_service_id

    if service_type == EmailServiceType.FREEMAIL:
        db_service = (
            db.query(EmailService)
            .filter(EmailService.service_type == "freemail", EmailService.enabled == True)
            .order_by(EmailService.priority.asc())
            .first()
        )
        if not (db_service and db_service.config):
            raise ValueError("没有可用的 Freemail 邮箱服务，请先在邮箱服务页面添加服务")

        config = _normalize_email_service_config(service_type, db_service.config, proxy)
        resolved_service_id = db_service.id
        return service_type, config, resolved_service_id

    if service_type == EmailServiceType.IMAP_MAIL:
        db_service = (
            db.query(EmailService)
            .filter(EmailService.service_type == "imap_mail", EmailService.enabled == True)
            .order_by(EmailService.priority.asc())
            .first()
        )
        if not (db_service and db_service.config):
            raise ValueError("没有可用的 IMAP 邮箱服务，请先在邮箱服务中添加")

        config = _normalize_email_service_config(service_type, db_service.config, proxy)
        resolved_service_id = db_service.id
        return service_type, config, resolved_service_id

    return service_type, (email_service_config or {}), resolved_service_id


def run_registration_job(
    *,
    db,
    email_service_type: str,
    email_service_id: int | None,
    proxy: str | None,
    email_service_config: dict[str, Any] | None,
    pipeline_key: str = "current_pipeline",
    auto_upload: bool = False,
    callback_logger: Callable[[str], None] | None = None,
    task_step_callback: Callable[[dict], None] | None = None,
    task_uuid: str | None = None,
    batch_id: str | None = None,
    registration_mode: str = "single",
) -> RegistrationJobResult:
    """执行单账号注册并落库，返回统一结果供路由和定时任务复用。"""
    known_email: str | None = None
    known_service_id: int | None = email_service_id
    known_result_payload: dict[str, Any] | None = None
    max_retries = max(int(get_settings().registration_max_retries or 0), 0)
    pipeline_runtime: Any | None = None

    for attempt in range(max_retries + 1):
        attempt_no = attempt + 1
        engine: RegistrationEngine | None = None
        runtime_ref: dict[str, Any] | None = None
        attempt_result_payload: dict[str, Any] | None = None
        attempt_runtime: Any | None = None
        runtime_context_logged = False
        try:
            service_type, config, resolved_service_id = _resolve_email_service(
                db=db,
                email_service_type=email_service_type,
                email_service_id=email_service_id,
                proxy=proxy,
                email_service_config=email_service_config,
            )
            known_service_id = resolved_service_id if resolved_service_id is not None else known_service_id
            _log_runtime_context_selection(
                callback_logger,
                email_service_id=resolved_service_id if resolved_service_id is not None else email_service_id,
                proxy_url=proxy,
            )
            runtime_context_logged = True

            email_service = EmailServiceFactory.create(service_type, config)
            runtime_ref = {}
            account, result_payload = _run_pipeline_registration(
                db=db,
                pipeline_key=pipeline_key,
                email_service=email_service,
                proxy=proxy,
                callback_logger=callback_logger,
                task_step_callback=task_step_callback,
                task_uuid=task_uuid,
                resolved_service_id=resolved_service_id,
                runtime_ref=runtime_ref,
            )
            pipeline_runtime = runtime_ref.get("runtime")
            attempt_runtime = pipeline_runtime
            result_payload = redact_result_payload(result_payload or {})
            attempt_result_payload = result_payload
            known_email = (result_payload or {}).get("email") or known_email
            known_result_payload = result_payload
            if not account:
                _write_failure_attempt(
                    db=db,
                    task_uuid=task_uuid,
                    attempt_no=attempt_no,
                    batch_id=batch_id,
                    pipeline_key=pipeline_key,
                    registration_mode=registration_mode,
                    email_service_type=email_service_type,
                    email_service_id=resolved_service_id,
                    email=(result_payload or {}).get("email"),
                    proxy=proxy,
                    error_message=(result_payload or {}).get("error_message") or "注册失败",
                    result_payload=result_payload,
                    engine=pipeline_runtime,
                    exc=None,
                )
                _update_registration_task_failure(
                    db,
                    task_uuid=task_uuid,
                    error_message=(result_payload or {}).get("error_message") or "注册失败",
                    email=(result_payload or {}).get("email"),
                    result_payload=result_payload,
                    email_service_id=resolved_service_id,
                )
                return RegistrationJobResult(
                    success=False,
                    email=(result_payload or {}).get("email"),
                    error_message=(result_payload or {}).get("error_message") or "注册失败",
                    email_service_id=resolved_service_id,
                    result_payload=result_payload,
                )
            _update_registration_task_success(
                db,
                task_uuid=task_uuid,
                email=account.email,
                result_payload=result_payload,
                email_service_id=resolved_service_id,
            )

            if auto_upload:
                logger.info("auto_upload is enabled but handled by caller")

            return RegistrationJobResult(
                success=True,
                account_id=account.id,
                email=account.email,
                email_service_id=resolved_service_id,
                result_payload=result_payload,
            )
        except RegistrationDisallowedSuffixError as exc:
            if engine is not None:
                engine.flush_task_logs()
            if pipeline_runtime is None and runtime_ref is not None:
                pipeline_runtime = runtime_ref.get("runtime")
            db.rollback()
            known_email = exc.email or known_email
            error_message = str(exc.detail or exc) or "注册异常"
            suffix = exc.suffix or extract_email_suffix(exc.email or "")
            _write_failure_attempt(
                db=db,
                task_uuid=task_uuid,
                attempt_no=attempt_no,
                batch_id=batch_id,
                pipeline_key=pipeline_key,
                registration_mode=registration_mode,
                email_service_type=email_service_type,
                email_service_id=known_service_id,
                email=known_email,
                proxy=proxy,
                error_message=error_message,
                result_payload=known_result_payload,
                engine=pipeline_runtime or engine,
                exc=exc,
            )

            if suffix:
                crud.upsert_auto_blacklist_suffix(
                    db,
                    suffix,
                    reason=error_message,
                )
                if callback_logger:
                    callback_logger(f"已将邮箱后缀加入黑名单: {suffix}")

            if attempt < max_retries:
                if task_uuid:
                    crud.update_registration_task(
                        db,
                        task_uuid,
                        status="running",
                        pipeline_status="running",
                        error_message=None,
                        completed_at=None,
                    )
                if callback_logger:
                    callback_logger("当前任务将使用新邮箱重新尝试注册")
                continue

            _update_registration_task_failure(
                db,
                task_uuid=task_uuid,
                error_message=error_message,
                email=known_email,
                result_payload=known_result_payload,
                email_service_id=known_service_id,
            )
            return RegistrationJobResult(
                success=False,
                email=known_email,
                email_service_id=known_service_id,
                error_message=error_message,
                result_payload=known_result_payload,
            )
        except PipelineStepExecutionError as exc:
            logger.exception(
                "run_registration_job pipeline step failed: task_uuid=%s attempt_no=%s pipeline_key=%s step_key=%s error=%s",
                task_uuid,
                attempt_no,
                pipeline_key,
                exc.context.step_key,
                exc,
            )
            if pipeline_runtime is None and runtime_ref is not None:
                pipeline_runtime = runtime_ref.get("runtime")
            db.rollback()
            structured_payload = {
                "success": False,
                "email": known_email,
                "error_message": str(exc),
                "metadata": {
                    "failure_stage": exc.context.failure_stage,
                    "step_key": exc.context.step_key,
                    "retryable": exc.context.retryable,
                    "attempt_count": exc.context.attempt_count,
                },
            }
            attempt_result_payload = structured_payload
            known_result_payload = structured_payload
            _write_failure_attempt(
                db=db,
                task_uuid=task_uuid,
                attempt_no=attempt_no,
                batch_id=batch_id,
                pipeline_key=pipeline_key,
                registration_mode=registration_mode,
                email_service_type=email_service_type,
                email_service_id=known_service_id,
                email=known_email,
                proxy=proxy,
                error_message=str(exc) or "注册异常",
                result_payload=structured_payload,
                engine=pipeline_runtime or engine,
                failure_stage=exc.context.failure_stage,
                step_key=exc.context.step_key,
                retryable=exc.context.retryable,
                exc=exc,
            )
            _update_registration_task_failure(
                db,
                task_uuid=task_uuid,
                error_message=str(exc) or "注册异常",
                email=known_email,
                result_payload=structured_payload,
                email_service_id=known_service_id,
            )
            return RegistrationJobResult(
                success=False,
                email=known_email,
                email_service_id=known_service_id,
                error_message=str(exc) or "注册异常",
                result_payload=structured_payload,
            )
        except Exception as exc:
            logger.exception(
                "run_registration_job failed: task_uuid=%s attempt_no=%s pipeline_key=%s registration_mode=%s error=%s",
                task_uuid,
                attempt_no,
                pipeline_key,
                registration_mode,
                exc,
            )
            if engine is not None:
                engine.flush_task_logs()
            if pipeline_runtime is None and runtime_ref is not None:
                pipeline_runtime = runtime_ref.get("runtime")
            db.rollback()
            _write_failure_attempt(
                db=db,
                task_uuid=task_uuid,
                attempt_no=attempt_no,
                batch_id=batch_id,
                pipeline_key=pipeline_key,
                registration_mode=registration_mode,
                email_service_type=email_service_type,
                email_service_id=known_service_id,
                email=known_email,
                proxy=proxy,
                error_message=str(exc) or "注册异常",
                result_payload=known_result_payload,
                engine=pipeline_runtime or engine,
                exc=exc,
            )
            _update_registration_task_failure(
                db,
                task_uuid=task_uuid,
                error_message=str(exc) or "注册异常",
                email=known_email,
                result_payload=known_result_payload,
                email_service_id=known_service_id,
            )
            return RegistrationJobResult(
                success=False,
                email=known_email,
                email_service_id=known_service_id,
                error_message=str(exc) or "注册异常",
                result_payload=known_result_payload,
            )
        finally:
            if runtime_context_logged:
                _log_runtime_context_proxy_ip(
                    callback_logger,
                    proxy_ip=_extract_runtime_proxy_ip(
                        result_payload=attempt_result_payload,
                        runtime=attempt_runtime,
                    ),
                )


def _write_failure_attempt(
    *,
    db,
    task_uuid: str | None,
    attempt_no: int,
    batch_id: str | None,
    pipeline_key: str,
    registration_mode: str,
    email_service_type: str | None,
    email_service_id: int | None,
    email: str | None,
    proxy: str | None,
    error_message: str | None,
    result_payload: dict[str, Any] | None,
    engine: Any | None,
    failure_stage: str | None = None,
    step_key: str | None = None,
    retryable: bool = False,
    exc: Exception | None,
) -> None:
    payload = build_failure_write_payload(
        task_uuid=task_uuid,
        attempt_no=attempt_no,
        batch_id=batch_id,
        pipeline_key=pipeline_key,
        registration_mode=registration_mode,
        email_service_type=email_service_type,
        email_service_id=email_service_id,
        email=email,
        proxy=proxy,
        error_message=error_message,
        result_payload=result_payload,
        engine=engine,
        failure_stage=failure_stage,
        step_key=step_key,
        retryable=retryable,
        exc=exc,
        failed_at=utc_now_naive(),
    )
    if payload is None:
        return
    write_registration_failure_record(db, payload)


def _run_pipeline_registration(
    *,
    db,
    pipeline_key: str,
    email_service,
    proxy: str | None,
    callback_logger: Callable[[str], None] | None,
    task_step_callback: Callable[[dict], None] | None,
    task_uuid: str | None,
    resolved_service_id: int | None,
    runtime_ref: dict[str, Any] | None = None,
) -> tuple[Account | None, dict[str, Any] | None]:
    pipeline = get_pipeline(pipeline_key)
    if not pipeline:
        raise RuntimeError(f"pipeline not found: {pipeline_key}")

    runtime = _build_pipeline_runtime(
        pipeline_key=pipeline_key,
        email_service=email_service,
        proxy=proxy,
        callback_logger=callback_logger,
        task_uuid=task_uuid,
    )
    if runtime_ref is not None:
        runtime_ref["runtime"] = runtime
    effective_task_uuid = task_uuid or f"pipeline-{uuid.uuid4()}"
    ctx = PipelineContext(
        task_uuid=effective_task_uuid,
        pipeline_key=pipeline_key,
        proxy_url=proxy,
        metadata={"registration_engine": runtime},
        task_step_callback=task_step_callback,
    )

    PipelineRunner(db).run(pipeline, ctx)
    result_payload = _build_pipeline_result_payload(ctx)
    account = _persist_pipeline_account(
        db=db,
        result_payload=result_payload,
        email_service=email_service,
        email_service_id=resolved_service_id,
        proxy=proxy,
    )
    return account, result_payload


def _build_pipeline_runtime(
    *,
    pipeline_key: str,
    email_service,
    proxy: str | None,
    callback_logger: Callable[[str], None] | None,
    task_uuid: str | None,
):
    if pipeline_key == "current_pipeline":
        return build_current_runtime(
            email_service=email_service,
            proxy_url=proxy,
            callback_logger=callback_logger,
            task_uuid=task_uuid,
            engine_cls=RegistrationEngine,
        )
    if pipeline_key == "codexgen_pipeline":
        return build_codexgen_runtime(
            email_service=email_service,
            proxy_url=proxy,
            callback_logger=callback_logger,
            task_uuid=task_uuid,
        )
    raise RuntimeError(f"pipeline runtime not found: {pipeline_key}")


def _build_pipeline_result_payload(ctx: PipelineContext) -> dict[str, Any]:
    metadata = _sanitize_metadata(ctx.metadata or {})
    runtime = (ctx.metadata or {}).get("registration_engine")
    if runtime is not None:
        proxy_ip = str(getattr(runtime, "proxy_ip", "") or "").strip()
        if proxy_ip and "proxy_ip" not in metadata:
            metadata["proxy_ip"] = proxy_ip
        user_profile = getattr(runtime, "generated_user_profile", None)
        if user_profile and "user_profile" not in metadata:
            metadata["user_profile"] = _to_jsonable(user_profile)
    return {
        "success": True,
        "email": ctx.email,
        "password": ctx.password or "",
        "account_id": metadata.get("account_id", ""),
        "workspace_id": metadata.get("workspace_id", ""),
        "access_token": metadata.get("access_token", ""),
        "refresh_token": metadata.get("refresh_token", ""),
        "id_token": metadata.get("id_token", ""),
        "session_token": metadata.get("session_token", ""),
        "error_message": "",
        "logs": [],
        "token_source": metadata.get("token_source", ""),
        "metadata": metadata,
        "source": "login" if metadata.get("is_existing_account") else "register",
    }


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if key == "registration_engine":
            continue
        sanitized[key] = _to_jsonable(value)
    return sanitized


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    return str(value)


def _extract_runtime_proxy_ip(
    *,
    result_payload: dict[str, Any] | None,
    runtime: Any | None,
) -> str | None:
    metadata = (result_payload or {}).get("metadata")
    if isinstance(metadata, dict):
        proxy_ip = str(metadata.get("proxy_ip") or "").strip()
        if proxy_ip:
            return proxy_ip

    proxy_ip = str(getattr(runtime, "proxy_ip", "") or "").strip()
    return proxy_ip or None


def _log_runtime_context_selection(
    callback_logger: Callable[[str], None] | None,
    *,
    email_service_id: int | None,
    proxy_url: str | None,
) -> None:
    if callback_logger is None:
        return

    callback_logger(
        "[运行上下文] "
        f"email_service_id={email_service_id if email_service_id is not None else 'none'} "
        f"proxy_url={str(proxy_url or 'direct')}"
    )


def _log_runtime_context_proxy_ip(
    callback_logger: Callable[[str], None] | None,
    *,
    proxy_ip: str | None,
) -> None:
    if callback_logger is None:
        return

    callback_logger(f"[运行上下文] proxy_ip={proxy_ip or _RUNTIME_CONTEXT_UNKNOWN}")


def _update_registration_task_success(
    db,
    *,
    task_uuid: str | None,
    email: str | None,
    result_payload: dict[str, Any] | None,
    email_service_id: int | None,
) -> None:
    if not task_uuid:
        return

    update_fields: dict[str, Any] = {
        "status": "completed",
        "completed_at": utc_now_naive(),
        "result": result_payload,
        "error_message": None,
    }
    if email:
        update_fields["email_address"] = email
    if email_service_id is not None:
        update_fields["email_service_id"] = email_service_id

    crud.update_registration_task(db, task_uuid, **update_fields)


def _update_registration_task_failure(
    db,
    *,
    task_uuid: str | None,
    error_message: str,
    email: str | None,
    result_payload: dict[str, Any] | None,
    email_service_id: int | None,
) -> None:
    if not task_uuid:
        return

    update_fields: dict[str, Any] = {
        "status": "failed",
        "completed_at": utc_now_naive(),
        "error_message": error_message,
    }
    if result_payload is not None:
        update_fields["result"] = result_payload
    if email:
        update_fields["email_address"] = email
    if email_service_id is not None:
        update_fields["email_service_id"] = email_service_id

    crud.update_registration_task(db, task_uuid, **update_fields)


def _persist_pipeline_account(
    *,
    db,
    result_payload: dict[str, Any],
    email_service,
    email_service_id: int | None,
    proxy: str | None,
) -> Account | None:
    email = str(result_payload.get("email") or "").strip()
    if not email:
        return None

    settings = get_settings()
    existing = db.query(Account).filter(Account.email == email).first()
    if existing:
        return existing

    account = crud.create_account(
        db,
        email=email,
        password=result_payload.get("password") or "",
        client_id=settings.openai_client_id,
        session_token=result_payload.get("session_token") or None,
        email_service=email_service.service_type.value,
        email_service_id=str(email_service_id) if email_service_id is not None else None,
        account_id=result_payload.get("account_id") or None,
        workspace_id=result_payload.get("workspace_id") or None,
        access_token=result_payload.get("access_token") or None,
        refresh_token=result_payload.get("refresh_token") or None,
        id_token=result_payload.get("id_token") or None,
        proxy_used=proxy,
        extra_data=result_payload.get("metadata") or {},
        source=result_payload.get("source") or "register",
    )
    return account
