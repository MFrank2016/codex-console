from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app


def test_dashboard_page_requires_auth_and_renders_dashboard_hooks():
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.get("/", follow_redirects=False)
        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["location"] == "/login?next=/"

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/")
        assert response.status_code == 200
        assert 'data-page-key="dashboard"' in response.text
        assert "/static/js/dashboard.js?v=" in response.text


def test_dashboard_template_contains_required_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="dashboard-hero"' in template
    assert 'id="dashboard-task-health"' in template
    assert 'id="dashboard-quick-links"' in template


def test_dashboard_script_loads_summary_endpoint_and_render_helpers():
    script = Path("static/js/dashboard.js").read_text(encoding="utf-8")
    assert "/dashboard/summary" in script
    assert "renderDashboardHero" in script
    assert "renderDashboardTaskHealth" in script


def test_dashboard_summary_api_returns_expected_top_level_sections():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert "registration" in payload
    assert "accounts" in payload
    assert "scheduled" in payload


def test_registration_workbench_page_requires_auth_and_renders_registration_hooks():
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.get("/registration-workbench", follow_redirects=False)
        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["location"] == "/login?next=/registration-workbench"

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/registration-workbench"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/registration-workbench")
        assert response.status_code == 200
        assert 'id="registration-form"' in response.text
        assert 'id="task-step-waterfall"' in response.text
