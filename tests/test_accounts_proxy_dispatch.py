from types import SimpleNamespace

from src.web.routes import accounts as accounts_routes


def test_get_proxy_uses_unified_proxy_dispatch_service(monkeypatch):
    class FakeDispatchService:
        def resolve_single_proxy(self, task_group, explicit_proxy, overrides):
            assert task_group == "generic_single"
            assert explicit_proxy is None
            assert overrides == {}
            return SimpleNamespace(proxy_url="http://dispatch-picked:8000")

    monkeypatch.setattr(accounts_routes, "_build_proxy_dispatch_service", lambda: FakeDispatchService())

    assert accounts_routes._get_proxy() == "http://dispatch-picked:8000"
