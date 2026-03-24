from datetime import timedelta

from fastapi.testclient import TestClient

from src.core.time import utc_now
from src.web.app import create_app
from src.web.task_manager import task_manager


def test_utc_now_returns_timezone_aware_utc_datetime():
    value = utc_now()

    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_create_app_uses_lifespan_startup_and_shutdown_hooks(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr('src.boot.lifespan.initialize_database', lambda: calls.append('initialize_database'))
    monkeypatch.setattr('src.boot.lifespan.AccountSurvivalDispatcher.start', lambda self: calls.append('dispatcher_start'))
    monkeypatch.setattr('src.boot.lifespan.AccountSurvivalDispatcher.stop', lambda self: calls.append('dispatcher_stop'))

    app = create_app()
    engine = app.state.scheduler_engine

    assert engine._started is False

    with TestClient(app):
        assert engine._started is True
        assert task_manager.get_loop() is not None
        assert app.state.account_survival_dispatcher is not None
        assert calls[:2] == ['initialize_database', 'dispatcher_start']

    assert engine._started is False
    assert calls[-1] == 'dispatcher_stop'
