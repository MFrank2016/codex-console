from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app


def test_run_center_page_requires_auth_and_renders_template_hooks():
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.get("/run-center", follow_redirects=False)
        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["location"] == "/login?next=/run-center"

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/run-center"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/run-center")
        assert response.status_code == 200
        assert 'data-page-key="run_center"' in response.text
        assert 'id="run-center-page"' in response.text
        assert "/static/css/run_center.css?v=" in response.text
        assert "/static/js/run_center.js?v=" in response.text


def test_run_center_template_contains_summary_list_log_hooks_and_assets():
    template = Path("templates/run_center.html").read_text(encoding="utf-8")
    assert '{% extends "_workspace_base.html" %}' in template
    assert 'id="run-center-page"' in template
    assert 'id="run-center-summary-panel"' in template
    assert 'id="run-center-list-panel"' in template
    assert 'id="run-center-log-panel"' in template
    assert "/static/css/run_center.css?v=" in template
    assert "/static/js/run_center.js?v=" in template
