from pathlib import Path
import re
from uuid import uuid4

from fastapi.testclient import TestClient

from src.database import crud
from src.database.session import get_db
from src.config.settings import get_settings
from src.web.app import create_app
from tests_runtime.dashboard_js_harness import run_dashboard_js_scenario


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
        assert re.search(r'<header class="page-head">[\s\S]*id="workspace-theme-toggle"', response.text)
        assert re.search(
            r'<footer class="workspace-sidebar-footer">[\s\S]*href="/logout"',
            response.text,
        )
        page_head_match = re.search(
            r'<header class="page-head">(?P<body>[\s\S]*?)</header>',
            response.text,
        )
        assert page_head_match is not None
        assert 'href="/logout"' not in page_head_match.group("body")
        assert "/static/js/dashboard.js?v=" in response.text


def test_dashboard_template_contains_required_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert "dashboard-page" in template
    assert 'id="dashboard-overview-summary"' in template
    assert 'id="dashboard-overview-alerts"' in template
    assert 'id="dashboard-overview-launchpad"' in template


def test_dashboard_template_contains_overview_hub_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert "dashboard-overview-hub" in template
    assert "dashboard-overview-section" in template
    assert "启动台" in template
    assert "/static/css/dashboard_page.css" in template


def test_dashboard_stylesheet_defines_overview_hub_dark_mode_selectors():
    stylesheet = Path("static/css/dashboard_page.css").read_text(encoding="utf-8")
    assert ".dashboard-overview-summary-grid" in stylesheet
    assert ".dashboard-launchpad-grid" in stylesheet
    assert '[data-theme="dark"] .dashboard-overview-section' in stylesheet
    assert '[data-theme="dark"] .dashboard-launchpad-card' in stylesheet


def test_dashboard_script_loads_summary_endpoint_and_overview_render_helpers():
    script = Path("static/js/dashboard.js").read_text(encoding="utf-8")
    assert "/dashboard/summary" in script
    assert "renderOverviewSummary" in script
    assert "renderOverviewAlerts" in script
    assert "renderOverviewLaunchpad" in script
    assert "renderDashboardLoadingState" in script
    assert "safeHref" in script
    assert "dashboard-overview-summary" in script


def test_dashboard_js_harness_renders_overview_hub_with_safe_links():
    result = run_dashboard_js_scenario("render_overview_hub")

    summary_html = result["summary_html"]
    assert "dashboard-summary-card" in summary_html
    assert "注册任务" in summary_html

    alerts_html = result["alerts_html"]
    assert 'class="dashboard-alert-item"' in alerts_html
    assert "&lt;script&gt;" in alerts_html
    assert 'href="#"' in alerts_html
    assert 'href="https://example.com/activity"' in alerts_html
    assert "javascript:" not in alerts_html
    assert "data:" not in alerts_html

    launchpad_html = result["launchpad_html"]
    assert "dashboard-launchpad-card" in launchpad_html
    assert 'href="/registration-workbench"' in launchpad_html
    assert 'href="#"' in launchpad_html
    assert "javascript:" not in launchpad_html
    assert "data:" not in launchpad_html


def test_dashboard_js_harness_renders_loading_state_for_all_overview_sections():
    result = run_dashboard_js_scenario("render_loading_state")
    assert "加载中" in result["summary_html"]
    assert "加载中" in result["alerts_html"]
    assert "加载中" in result["launchpad_html"]


def test_dashboard_js_harness_renders_error_state_without_invalid_ul_children():
    result = run_dashboard_js_scenario("render_error")
    assert result["alerts_html"].lstrip().startswith('<li class="dashboard-empty">')
    assert "<p" not in result["alerts_html"]
    assert "Dashboard 加载失败" in result["summary_html"]
    assert "Dashboard 加载失败" in result["launchpad_html"]


def test_dashboard_js_harness_safe_href_rejects_protocol_relative_urls():
    result = run_dashboard_js_scenario("safe_href_matrix")
    assert result == {
        "relative_ok": "/registration-workbench",
        "https_ok": "https://example.com/activity",
        "protocol_relative_rejected": "#",
        "javascript_rejected": "#",
        "data_rejected": "#",
    }


def test_dashboard_js_harness_dom_content_loaded_flow_mounts_all_sections_and_fetches_summary():
    result = run_dashboard_js_scenario("dom_content_loaded_flow")

    assert result["fetch_paths"] == ["/api/dashboard/summary"]
    assert "加载中" in result["loading_summary_html"]
    assert "dashboard-summary-card" in result["summary_html"]
    assert 'class="dashboard-alert-item"' in result["alerts_html"]
    assert 'class="dashboard-launchpad-card"' in result["launchpad_html"]

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
    assert any(item.get("href") == "/run-center" for item in payload["quick_links"])

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
        assert 'id="task-step-waterfall"' not in response.text
