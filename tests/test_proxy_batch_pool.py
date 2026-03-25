from types import SimpleNamespace

import pytest

from src.application.proxy_batch_pool import ProxyBatchPool
from src.application.proxy_dispatch_service import ProxyDispatchService, ResolvedProxyCandidate


def _candidate(proxy_url: str, *, egress_ip: str | None = None, proxy_key: str | None = None) -> ResolvedProxyCandidate:
    return ResolvedProxyCandidate(
        proxy_url=proxy_url,
        source="dynamic_pool",
        egress_ip=egress_ip,
        proxy_key=proxy_key,
    )


def test_exclusive_strategy_never_duplicates_proxy_while_two_tasks_are_running():
    pool = ProxyBatchPool(
        batch_id="batch-1",
        strategy="exclusive",
        candidates=[
            _candidate("http://proxy-1:8000"),
            _candidate("http://proxy-2:8000"),
        ],
    )

    first = pool.lease()
    second = pool.lease()

    assert first.proxy_url != second.proxy_url
    with pytest.raises(RuntimeError):
        pool.lease()


def test_consume_once_strategy_never_reuses_proxy_after_release():
    pool = ProxyBatchPool(
        batch_id="batch-2",
        strategy="consume_once",
        candidates=[_candidate("http://proxy-1:8000")],
    )

    leased = pool.lease()
    pool.complete(leased, success=True)

    with pytest.raises(RuntimeError):
        pool.lease()


def test_strict_isolation_falls_back_to_proxy_identity_when_egress_ip_missing():
    pool = ProxyBatchPool(
        batch_id="batch-3",
        strategy="strict_isolation",
        candidates=[
            _candidate("http://proxy-1:8000", proxy_key="a"),
            _candidate("http://proxy-1:8000", proxy_key="b"),
        ],
    )

    leased = pool.lease()
    pool.complete(leased, success=True)

    with pytest.raises(RuntimeError):
        pool.lease()


def test_prepare_batch_proxy_pool_raises_when_available_candidates_less_than_required():
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(
            proxy_dynamic_task_defaults={
                "batch_registration": {
                    "allocation_strategy": "exclusive",
                }
            }
        ),
        dynamic_candidates_provider=lambda **_: ["http://proxy-1:8000"],
        proxy_list_provider=lambda limit: [],
        static_proxy_provider=lambda: None,
    )

    with pytest.raises(RuntimeError):
        service.prepare_batch_proxy_pool(
            batch_id="batch-4",
            task_group="batch_registration",
            concurrency=2,
            overrides={},
        )


def test_runtime_pool_exhaustion_raises_instead_of_falling_back_to_static_or_proxy_list():
    service = ProxyDispatchService(
        settings_provider=lambda: SimpleNamespace(
            proxy_dynamic_task_defaults={
                "batch_registration": {
                    "allocation_strategy": "consume_once",
                }
            }
        ),
        dynamic_candidates_provider=lambda **_: ["http://proxy-1:8000"],
        proxy_list_provider=lambda limit: ["http://local-1:8000", "http://local-2:8000"],
        static_proxy_provider=lambda: "http://static-1:8000",
    )

    pool = service.prepare_batch_proxy_pool(
        batch_id="batch-5",
        task_group="batch_registration",
        concurrency=1,
        overrides={
            "dynamic_request_count": 1,
            "proxy_list_candidate_limit": 1,
        },
    )

    first = pool.lease()
    assert first.proxy_url == "http://proxy-1:8000"
    pool.complete(first, success=True)

    with pytest.raises(RuntimeError):
        pool.lease()
