from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .proxy_dispatch_service import ResolvedProxyCandidate


class ProxyBatchPool:
    def __init__(self, batch_id: str, strategy: str, candidates: list[ResolvedProxyCandidate]):
        self.batch_id = str(batch_id)
        self.strategy = str(strategy or "random").strip().lower()
        self.available = list(candidates or [])
        self.in_use: set[str] = set()
        self.consumed: set[str] = set()
        self.isolated_keys: set[str] = set()

        allowed = {"random", "exclusive", "consume_once", "strict_isolation"}
        if self.strategy not in allowed:
            raise ValueError(f"unsupported batch proxy strategy: {self.strategy}")

    def lease(self) -> ResolvedProxyCandidate:
        if not self.available:
            raise RuntimeError(f"batch proxy pool exhausted: {self.batch_id}")

        if self.strategy == "random":
            return random.choice(self.available)

        if self.strategy == "exclusive":
            for candidate in self.available:
                key = self._candidate_identity(candidate)
                if key in self.in_use:
                    continue
                self.in_use.add(key)
                return candidate
            raise RuntimeError(f"batch proxy pool exhausted: {self.batch_id}")

        if self.strategy == "consume_once":
            for candidate in self.available:
                key = self._candidate_identity(candidate)
                if key in self.in_use or key in self.consumed:
                    continue
                self.in_use.add(key)
                self.consumed.add(key)
                return candidate
            raise RuntimeError(f"batch proxy pool exhausted: {self.batch_id}")

        for candidate in self.available:
            isolation_key = self._isolation_key(candidate)
            if isolation_key in self.in_use or isolation_key in self.isolated_keys:
                continue
            self.in_use.add(isolation_key)
            return candidate
        raise RuntimeError(f"batch proxy pool exhausted: {self.batch_id}")

    def complete(self, candidate: ResolvedProxyCandidate, *, success: bool) -> None:
        if self.strategy == "random":
            return

        if self.strategy == "exclusive":
            self.in_use.discard(self._candidate_identity(candidate))
            return

        if self.strategy == "consume_once":
            self.in_use.discard(self._candidate_identity(candidate))
            return

        isolation_key = self._isolation_key(candidate)
        self.in_use.discard(isolation_key)
        self.isolated_keys.add(isolation_key)

    @staticmethod
    def _candidate_identity(candidate: ResolvedProxyCandidate) -> str:
        return str(candidate.proxy_key or candidate.proxy_url)

    @staticmethod
    def _isolation_key(candidate: ResolvedProxyCandidate) -> str:
        if candidate.egress_ip:
            return str(candidate.egress_ip)
        return str(candidate.proxy_url)
