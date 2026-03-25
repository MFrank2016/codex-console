from __future__ import annotations

import random
import re
import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..core.dynamic_proxy import (
    build_dynamic_proxy_request,
    fetch_dynamic_proxy_candidates,
    probe_proxy_candidate,
)
from .proxy_batch_pool import ProxyBatchPool

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedProxyCandidate:
    proxy_url: str
    source: str
    egress_ip: str | None = None
    proxy_key: str | None = None
    proxy_id: int | None = None


class ProxyDispatchService:
    def __init__(
        self,
        *,
        settings_provider: Callable[[], Any] | None = None,
        dynamic_candidates_provider: Callable[..., list[str]] | None = None,
        proxy_list_provider: Callable[[int], list[str]] | None = None,
        static_proxy_provider: Callable[[], str | None] | None = None,
    ):
        self.settings_provider = settings_provider or self._default_settings_provider
        self.dynamic_candidates_provider = dynamic_candidates_provider or self._default_dynamic_candidates_provider
        self.proxy_list_provider = proxy_list_provider or self._default_proxy_list_provider
        self.static_proxy_provider = static_proxy_provider or self._default_static_proxy_provider

    def resolve_single_candidates(
        self,
        task_group: str,
        explicit_proxy: str | None,
        overrides: dict[str, Any] | None,
    ) -> list[ResolvedProxyCandidate]:
        if explicit_proxy:
            return [ResolvedProxyCandidate(proxy_url=explicit_proxy, source="explicit")]

        effective = self._build_effective_config(task_group, overrides)
        dynamic_request_count = self._coerce_positive_int(
            effective.get("dynamic_request_count"),
            fallback=1,
        )
        proxy_list_candidate_limit = self._coerce_positive_int(
            effective.get("proxy_list_candidate_limit"),
            fallback=5,
        )

        candidates: list[ResolvedProxyCandidate] = []

        try:
            dynamic_provider_kwargs = {
                "task_group": task_group,
                "request_count": dynamic_request_count,
            }
            if effective.get("probe_url"):
                dynamic_provider_kwargs["probe_url"] = effective.get("probe_url")
            dynamic_candidates = self.dynamic_candidates_provider(
                **dynamic_provider_kwargs,
            )
        except Exception:
            logger.exception("Failed to resolve dynamic proxy candidates for task group %s", task_group)
            dynamic_candidates = []
        for item in dynamic_candidates or []:
            candidate = self._normalize_single_candidate(item, source="dynamic_pool")
            if candidate is not None:
                candidates.append(candidate)

        proxy_list = list(self.proxy_list_provider(proxy_list_candidate_limit) or [])
        if proxy_list and len(proxy_list) > proxy_list_candidate_limit:
            proxy_list = random.sample(proxy_list, k=proxy_list_candidate_limit)
        for item in proxy_list:
            candidate = self._normalize_single_candidate(item, source="proxy_list")
            if candidate is not None:
                candidates.append(candidate)

        static_proxy = self.static_proxy_provider()
        if static_proxy:
            candidates.append(ResolvedProxyCandidate(proxy_url=str(static_proxy), source="static"))

        return candidates

    def resolve_single_proxy(
        self,
        task_group: str,
        explicit_proxy: str | None,
        overrides: dict[str, Any] | None,
    ) -> ResolvedProxyCandidate | None:
        candidates = self.resolve_single_candidates(task_group, explicit_proxy, overrides)
        return candidates[0] if candidates else None

    def resolve_proxy_candidates(
        self,
        task_group: str,
        explicit_proxy: str | None,
        overrides: dict[str, Any] | None,
    ) -> list[ResolvedProxyCandidate]:
        return self.resolve_single_candidates(task_group, explicit_proxy, overrides)

    def is_proxy_related_failure(self, error: Exception | str) -> bool:
        text = str(error).lower()

        status_markers = ("403", "407", "429", "502", "503")
        if any(marker in text for marker in status_markers):
            return True

        keyword_patterns = (
            r"\btimeout\b",
            r"timed\s*out",
            r"connection",
            r"connect",
            r"proxy\s*auth",
            r"proxy\s*authentication",
            r"tls",
            r"handshake",
            r"dns",
            r"socket",
            r"captcha",
            r"blocked",
            r"access\s*denied",
            r"forbidden",
        )
        return any(re.search(pattern, text) for pattern in keyword_patterns)

    def prepare_batch_proxy_pool(
        self,
        *,
        batch_id: str,
        task_group: str,
        concurrency: int,
        overrides: dict[str, Any],
    ) -> ProxyBatchPool:
        effective = self._build_effective_config(task_group, overrides)
        concurrency_value = self._coerce_positive_int(concurrency, fallback=1)
        batch_prefetch_multiplier = self._coerce_positive_int(
            effective.get("batch_prefetch_multiplier"),
            fallback=3,
        )
        batch_prefetch_max = self._coerce_positive_int(
            effective.get("batch_prefetch_max"),
            fallback=100,
        )

        request_count = self._coerce_positive_int(
            effective.get("dynamic_request_count"),
            fallback=min(concurrency_value * batch_prefetch_multiplier, batch_prefetch_max),
        )
        required_candidates = self._coerce_positive_int(
            effective.get("required_candidate_count"),
            fallback=concurrency_value,
        )
        strategy = str(effective.get("allocation_strategy") or "random").strip().lower()

        dynamic_provider_kwargs = {
            "task_group": task_group,
            "request_count": request_count,
        }
        if effective.get("probe_url"):
            dynamic_provider_kwargs["probe_url"] = effective.get("probe_url")
        raw_candidates = self.dynamic_candidates_provider(**dynamic_provider_kwargs)
        candidates = [
            candidate
            for candidate in (
                self._normalize_batch_candidate(item)
                for item in (raw_candidates or [])
            )
            if candidate is not None
        ]

        if len(candidates) < required_candidates:
            raise RuntimeError(
                "insufficient proxy candidates for batch pool: "
                f"required={required_candidates}, available={len(candidates)}"
            )

        return ProxyBatchPool(
            batch_id=batch_id,
            strategy=strategy,
            candidates=candidates,
        )

    @staticmethod
    def lease_batch_proxy(pool: ProxyBatchPool) -> ResolvedProxyCandidate:
        return pool.lease()

    @staticmethod
    def report_proxy_result(pool: ProxyBatchPool, candidate: ResolvedProxyCandidate, *, success: bool) -> None:
        pool.complete(candidate, success=success)

    def _build_effective_config(self, task_group: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
        settings = self.settings_provider()
        task_defaults = getattr(settings, "proxy_dynamic_task_defaults", {}) or {}
        default_group_config = task_defaults.get(task_group, {}) or {}
        return {
            **default_group_config,
            **(overrides or {}),
        }

    @staticmethod
    def _coerce_positive_int(raw_value: Any, *, fallback: int) -> int:
        try:
            value = int(raw_value)
            return value if value > 0 else fallback
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _normalize_batch_candidate(raw_candidate: Any) -> ResolvedProxyCandidate | None:
        if isinstance(raw_candidate, ResolvedProxyCandidate):
            return raw_candidate

        if isinstance(raw_candidate, str):
            text = raw_candidate.strip()
            if not text:
                return None
            return ResolvedProxyCandidate(
                proxy_url=text,
                source="dynamic_pool",
            )

        if isinstance(raw_candidate, dict):
            proxy_url = str(raw_candidate.get("proxy_url") or "").strip()
            if not proxy_url:
                return None
            egress_ip = raw_candidate.get("egress_ip")
            proxy_key = raw_candidate.get("proxy_key")
            return ResolvedProxyCandidate(
                proxy_url=proxy_url,
                source="dynamic_pool",
                egress_ip=str(egress_ip) if egress_ip else None,
                proxy_key=str(proxy_key) if proxy_key else None,
            )

        return None

    @staticmethod
    def _normalize_single_candidate(raw_candidate: Any, *, source: str) -> ResolvedProxyCandidate | None:
        if isinstance(raw_candidate, ResolvedProxyCandidate):
            return raw_candidate

        if isinstance(raw_candidate, str):
            text = raw_candidate.strip()
            if not text:
                return None
            return ResolvedProxyCandidate(proxy_url=text, source=source)

        if isinstance(raw_candidate, dict):
            proxy_url = str(raw_candidate.get("proxy_url") or "").strip()
            if not proxy_url:
                return None
            egress_ip = raw_candidate.get("egress_ip")
            proxy_key = raw_candidate.get("proxy_key")
            proxy_id = raw_candidate.get("proxy_id")
            return ResolvedProxyCandidate(
                proxy_url=proxy_url,
                source=str(raw_candidate.get("source") or source),
                egress_ip=str(egress_ip) if egress_ip else None,
                proxy_key=str(proxy_key) if proxy_key else None,
                proxy_id=int(proxy_id) if proxy_id not in (None, "") else None,
            )

        return None

    @staticmethod
    def _default_settings_provider():
        from ..config.settings import get_settings

        return get_settings()

    def _default_dynamic_candidates_provider(
        self,
        *,
        task_group: str,
        request_count: int,
        probe_url: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        settings = self.settings_provider()
        request_url = getattr(settings, "proxy_dynamic_request_url", "")
        if not getattr(settings, "proxy_dynamic_enabled", False) or not request_url:
            return []

        api_key_secret = getattr(settings, "proxy_dynamic_api_key", None)
        api_key = api_key_secret.get_secret_value() if api_key_secret else ""
        request = build_dynamic_proxy_request(
            request_method=getattr(settings, "proxy_dynamic_request_method", "GET"),
            request_url=request_url,
            request_headers_template=getattr(settings, "proxy_dynamic_request_headers_template", {}) or {},
            request_body_template=getattr(settings, "proxy_dynamic_request_body_template", {}) or {},
            request_count_param_name=getattr(settings, "proxy_dynamic_request_count_param_name", "count"),
            count=request_count,
            request_body_mode=getattr(settings, "proxy_dynamic_request_body_mode", "auto"),
            request_timeout_seconds=getattr(settings, "proxy_dynamic_request_timeout_seconds", 10),
            api_key=api_key,
            api_key_header=getattr(settings, "proxy_dynamic_api_key_header", "X-API-Key"),
        )
        candidates = fetch_dynamic_proxy_candidates(
            request,
            response_root_field=getattr(settings, "proxy_dynamic_response_root_field", ""),
            response_item_mode=getattr(settings, "proxy_dynamic_response_item_mode", "string_list"),
            response_field_mapping=getattr(settings, "proxy_dynamic_response_field_mapping", {}) or {},
        )

        effective_probe_url = (
            probe_url
            or (getattr(settings, "proxy_dynamic_task_defaults", {}) or {}).get(task_group, {}).get("probe_url")
            or "https://api.ipify.org?format=json"
        )
        resolved: list[dict[str, Any]] = []
        for candidate in candidates:
            probe = probe_proxy_candidate(
                candidate,
                probe_url=effective_probe_url,
                timeout_seconds=request.timeout_seconds,
            )
            if probe.ok:
                resolved.append(
                    {
                        "proxy_url": candidate.proxy_url,
                        "egress_ip": probe.egress_ip,
                        "proxy_key": candidate.proxy_url,
                    }
                )
        return resolved

    @staticmethod
    def _default_proxy_list_provider(_limit: int) -> list[str]:
        return []

    def _default_static_proxy_provider(self) -> str | None:
        settings = self.settings_provider()
        return getattr(settings, "proxy_url", None)
