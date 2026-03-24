from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.database import crud
from src.database.session import get_db
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
        assert 'id="workspace-theme-toggle"' in response.text
        assert 'href="/logout"' in response.text
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
    assert "registration.total_tasks" in script


def test_dashboard_summary_api_requires_auth():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/dashboard/summary")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_dashboard_summary_api_returns_expected_nested_contract_for_authenticated_user():
    app = create_app()
    with TestClient(app) as client:
        task_uuid = str(uuid4())
        with get_db() as db:
            crud.create_registration_task(
                db,
                task_uuid=task_uuid,
                pipeline_key="current_pipeline",
            )

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()
    assert "total_tasks" in payload["registration"]
    assert "running" in payload["registration"]
    assert "failed" in payload["registration"]
    assert "pending" in payload["registration"]
    assert "success_rate" in payload["registration"]
    assert isinstance(payload["registration"]["total_tasks"], int)
    assert payload["registration"]["total_tasks"] >= 1
    assert isinstance(payload["registration"]["running"], int)
    assert isinstance(payload["registration"]["failed"], int)
    assert isinstance(payload["registration"]["pending"], int)
    assert payload["registration"]["success_rate"] is None or isinstance(payload["registration"]["success_rate"], float)

    assert "total" in payload["accounts"]
    assert "active" in payload["accounts"]
    assert isinstance(payload["accounts"]["total"], int)
    assert isinstance(payload["accounts"]["active"], int)

    assert "plans_total" in payload["scheduled"]
    assert "plans_enabled" in payload["scheduled"]
    assert "runs_today" in payload["scheduled"]
    assert "runs_running" in payload["scheduled"]
    assert "runs_failed" in payload["scheduled"]
    assert isinstance(payload["scheduled"]["plans_total"], int)
    assert isinstance(payload["scheduled"]["plans_enabled"], int)
    assert isinstance(payload["scheduled"]["runs_today"], int)
    assert isinstance(payload["scheduled"]["runs_running"], int)
    assert isinstance(payload["scheduled"]["runs_failed"], int)

    assert isinstance(payload["quick_links"], list)
    assert payload["quick_links"]
    quick_link = payload["quick_links"][0]
    assert "label" in quick_link
    assert "href" in quick_link
    assert "description" in quick_link

    assert isinstance(payload["recent_activity"], list)
    assert payload["recent_activity"]
    activity = payload["recent_activity"][0]
    assert "title" in activity
    assert "status" in activity
    assert "href" in activity
    assert "timestamp" in activity
    assert "description" in activity


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
