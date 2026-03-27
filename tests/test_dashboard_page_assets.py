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
    assert 'id="dashboard-hero-primary"' in template
    assert 'id="dashboard-activity-feed"' in template
    assert 'id="dashboard-quick-actions"' in template


def test_dashboard_template_contains_new_hero_and_activity_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="dashboard-hero-primary"' in template
    assert 'id="dashboard-metric-grid"' in template
    assert 'id="dashboard-activity-feed"' in template
    assert 'id="dashboard-quick-actions"' in template
    assert "/static/css/dashboard_page.css" in template


def test_dashboard_stylesheet_defines_dark_mode_polish_selectors():
    stylesheet = Path("static/css/dashboard_page.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"] .dashboard-hero-primary' in stylesheet
    assert '[data-theme="dark"] .dashboard-metric-card' in stylesheet
    assert '[data-theme="dark"] .dashboard-quick-action--secondary' in stylesheet


def test_dashboard_script_loads_summary_endpoint_and_render_helpers():
    script = Path("static/js/dashboard.js").read_text(encoding="utf-8")
    assert "/dashboard/summary" in script
    assert "renderDashboardHero" in script
    assert "renderRecentActivity" in script
    assert "safeHref" in script
    assert "dashboard-activity-item" in script


def test_dashboard_js_harness_renders_modern_hero_metrics_and_activity_feed():
    result = run_dashboard_js_scenario("render_dashboard")

    metric_html = result["metric_html"]
    assert "dashboard-metric-card" in metric_html
    assert "dashboard-hero-copy" not in metric_html

    activity_html = result["activity_html"]
    assert 'class="dashboard-activity-item"' in activity_html
    assert "&lt;script&gt;" in activity_html
    assert 'href="#"' in activity_html
    assert 'href="https://example.com/activity"' in activity_html
    assert "javascript:" not in activity_html
    assert "data:" not in activity_html

    quick_actions_html = result["quick_actions_html"]
    assert 'href="/registration-workbench"' in quick_actions_html
    assert 'href="#"' in quick_actions_html
    assert "javascript:" not in quick_actions_html
    assert "data:" not in quick_actions_html


def test_dashboard_js_harness_renders_metric_tones_and_buttonized_quick_actions():
    result = run_dashboard_js_scenario("render_dashboard")
    assert "dashboard-metric-card--registration" in result["metric_html"]
    assert "dashboard-metric-value-badge--success-rate" in result["metric_html"]
    assert "dashboard-quick-action--primary" in result["quick_actions_html"]
    assert "dashboard-quick-action--secondary" in result["quick_actions_html"]


def test_dashboard_js_harness_rejects_invalid_metric_tone_tokens():
    result = run_dashboard_js_scenario("render_metric_card_with_invalid_tone")
    html = result["html"]
    assert 'data-evil=' not in html
    assert 'dashboard-metric-card--bad' not in html
    assert 'dashboard-metric-value-badge--bad' not in html
    assert 'class="dashboard-metric-card"' in html
    assert 'class="dashboard-metric-value-badge"' in html


def test_dashboard_js_harness_renders_error_state_without_invalid_ul_children():
    result = run_dashboard_js_scenario("render_error")
    assert result["activity_html"].lstrip().startswith('<li class="dashboard-empty">')
    assert "<p" not in result["activity_html"]


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
    assert "dashboard-metric-card" in result["metric_grid_html"]
    assert 'class="dashboard-activity-item"' in result["activity_html"]
    assert 'class="dashboard-quick-action' in result["quick_actions_html"]

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
