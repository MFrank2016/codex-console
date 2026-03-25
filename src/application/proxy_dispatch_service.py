from __future__ import annotations

import random
import re
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .proxy_batch_pool import ProxyBatchPool

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ResolvedProxyCandidate:
    proxy_url: str
    source: str
    egress_ip: str | None = None
    proxy_key: str | None = None


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
            dynamic_candidates = self.dynamic_candidates_provider(
                task_group=task_group,
                request_count=dynamic_request_count,
            )
        except Exception:
            logger.exception("Failed to resolve dynamic proxy candidates for task group %s", task_group)
            dynamic_candidates = []
        for proxy_url in dynamic_candidates or []:
            if proxy_url:
                candidates.append(ResolvedProxyCandidate(proxy_url=str(proxy_url), source="dynamic_pool"))

        proxy_list = list(self.proxy_list_provider(proxy_list_candidate_limit) or [])
        if proxy_list and len(proxy_list) > proxy_list_candidate_limit:
            proxy_list = random.sample(proxy_list, k=proxy_list_candidate_limit)
        for proxy_url in proxy_list:
            if proxy_url:
                candidates.append(ResolvedProxyCandidate(proxy_url=str(proxy_url), source="proxy_list"))

        static_proxy = self.static_proxy_provider()
        if static_proxy:
            candidates.append(ResolvedProxyCandidate(proxy_url=str(static_proxy), source="static"))

        return candidates

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

        request_count = self._coerce_positive_int(
            effective.get("dynamic_request_count"),
            fallback=max(self._coerce_positive_int(concurrency, fallback=1) * 3, 1),
        )
        required_candidates = self._coerce_positive_int(
            effective.get("required_candidate_count"),
            fallback=self._coerce_positive_int(concurrency, fallback=1),
        )
        strategy = str(effective.get("allocation_strategy") or "random").strip().lower()

        raw_candidates = self.dynamic_candidates_provider(
            task_group=task_group,
            request_count=request_count,
        )
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
    def _default_settings_provider():
        from ..config.settings import get_settings

        return get_settings()

    @staticmethod
    def _default_dynamic_candidates_provider(**_: Any) -> list[str]:
        return []

    @staticmethod
    def _default_proxy_list_provider(_limit: int) -> list[str]:
        return []

    def _default_static_proxy_provider(self) -> str | None:
        settings = self.settings_provider()
        return getattr(settings, "proxy_url", None)
