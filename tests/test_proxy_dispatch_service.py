import random
from types import SimpleNamespace

import pytest

from src.application.proxy_dispatch_service import ProxyDispatchService


def test_resolve_single_candidates_returns_explicit_proxy_only_when_present():
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: ["http://dynamic-1:8000"],
        proxy_list_provider=lambda limit: ["http://local-1:8000"],
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    candidates = service.resolve_single_candidates(
        task_group="generic_single",
        explicit_proxy="http://manual-1:8000",
        overrides={},
    )

    assert [item.proxy_url for item in candidates] == ["http://manual-1:8000"]


def test_resolve_single_candidates_orders_dynamic_then_proxy_list_then_static():
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: ["http://dynamic-1:8000", "http://dynamic-2:8000"],
        proxy_list_provider=lambda limit: ["http://local-1:8000", "http://local-2:8000"],
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    candidates = service.resolve_single_candidates("generic_single", None, {"proxy_list_candidate_limit": 2})

    assert [item.source for item in candidates] == [
        "dynamic_pool",
        "dynamic_pool",
        "proxy_list",
        "proxy_list",
        "static",
    ]


def test_resolve_single_candidates_uses_random_sample_for_proxy_list_limit(monkeypatch):
    local_candidates = [f"http://local-{i}:8000" for i in range(8)]
    sampled_candidates = [
        local_candidates[6],
        local_candidates[2],
        local_candidates[7],
        local_candidates[3],
        local_candidates[0],
    ]
    sample_calls: list[tuple[list[str], int]] = []

    def fake_sample(items, k):
        sample_calls.append((list(items), k))
        return list(sampled_candidates)

    monkeypatch.setattr(random, "sample", fake_sample)

    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: [],
        proxy_list_provider=lambda limit: list(local_candidates),
        static_proxy_provider=lambda: None,
    )

    candidates = service.resolve_single_candidates("generic_single", None, {})

    proxy_list_candidates = [item.proxy_url for item in candidates if item.source == "proxy_list"]
    assert sample_calls == [(local_candidates, 5)]
    assert proxy_list_candidates == sampled_candidates


def test_resolve_single_candidates_uses_override_proxy_list_limit_over_task_group_default(monkeypatch):
    dynamic_calls: list[dict] = []
    proxy_list_limits: list[int] = []
    sample_calls: list[int] = []

    def dynamic_provider(**kwargs):
        dynamic_calls.append(kwargs)
        return ["http://dynamic-1:8000"]

    def proxy_list_provider(limit):
        proxy_list_limits.append(limit)
        return [f"http://local-{i}:8000" for i in range(6)]

    def fake_sample(items, k):
        sample_calls.append(k)
        return list(items)[:k]

    monkeypatch.setattr(random, "sample", fake_sample)

    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(
            proxy_dynamic_task_defaults={
                "generic_single": {
                    "dynamic_request_count": 4,
                    "proxy_list_candidate_limit": 7,
                }
            }
        ),
        dynamic_candidates_provider=dynamic_provider,
        proxy_list_provider=proxy_list_provider,
        static_proxy_provider=lambda: None,
    )

    candidates = service.resolve_single_candidates(
        "generic_single",
        None,
        {
            "dynamic_request_count": 2,
            "proxy_list_candidate_limit": 2,
        },
    )

    proxy_list_candidates = [item.proxy_url for item in candidates if item.source == "proxy_list"]
    assert dynamic_calls == [{"task_group": "generic_single", "request_count": 2}]
    assert proxy_list_limits == [2]
    assert sample_calls == [2]
    assert len(proxy_list_candidates) == 2


def test_resolve_single_candidates_falls_back_when_dynamic_provider_raises():
    local_candidates = [f"http://local-{i}:8000" for i in range(8)]

    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: (_ for _ in ()).throw(RuntimeError("dynamic source down")),
        proxy_list_provider=lambda limit: list(local_candidates),
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    candidates = service.resolve_single_candidates("generic_single", None, {})

    proxy_list_candidates = [item.proxy_url for item in candidates if item.source == "proxy_list"]
    assert [item.source for item in candidates[:-1]] == ["proxy_list"] * 5
    assert len(proxy_list_candidates) == 5
    assert set(proxy_list_candidates).issubset(set(local_candidates))
    assert candidates[-1].source == "static"
    assert candidates[-1].proxy_url == "http://static-1:8000"


def test_is_proxy_related_failure_matches_network_and_block_signals():
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: [],
        proxy_list_provider=lambda limit: [],
        static_proxy_provider=lambda: None,
    )

    assert service.is_proxy_related_failure(RuntimeError("connection timeout")) is True
    assert service.is_proxy_related_failure(RuntimeError("403 blocked by upstream")) is True
    assert service.is_proxy_related_failure(RuntimeError("429 captcha required")) is True
    assert service.is_proxy_related_failure(RuntimeError("invalid password")) is False


@pytest.mark.parametrize(
    "error_text",
    [
        "proxy authentication required",
        "dns lookup failed",
        "tls handshake failed",
        "socket error",
        "407 proxy auth required",
        "502 bad gateway",
        "503 service unavailable",
        "access denied",
        "forbidden",
    ],
)
def test_is_proxy_related_failure_accepts_additional_proxy_signals(error_text):
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(proxy_dynamic_task_defaults={}),
        dynamic_candidates_provider=lambda **_: [],
        proxy_list_provider=lambda limit: [],
        static_proxy_provider=lambda: None,
    )

    assert service.is_proxy_related_failure(RuntimeError(error_text)) is True
