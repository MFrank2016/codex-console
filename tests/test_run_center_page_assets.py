from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app
from tests_runtime.run_center_js_harness import run_run_center_js_scenario


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
        assert "/static/js/run_center_shared.js?v=" in response.text
        assert "/static/js/run_center.js?v=" in response.text


def test_run_center_template_contains_run_filters_table_log_controls_and_assets():
    template = Path("templates/run_center.html").read_text(encoding="utf-8")
    assert '{% extends "_workspace_base.html" %}' in template
    assert 'id="run-center-page"' in template
    assert 'id="run-center-summary-panel"' in template
    assert 'id="run-center-list-panel"' in template
    assert 'id="run-center-log-panel"' in template
    assert 'id="run-center-control-scope"' in template
    assert 'id="run-center-context-link"' in template
    assert 'id="run-center-open-context-btn"' in template
    assert 'id="run-center-retry-btn"' in template
    assert 'id="scheduled-run-filter-task-type"' in template
    assert 'id="scheduled-run-filter-status"' in template
    assert 'id="scheduled-run-filter-started-from"' in template
    assert 'id="scheduled-run-filter-started-to"' in template
    assert 'id="scheduled-run-filter-apply-btn"' in template
    assert 'id="scheduled-run-filter-reset-btn"' in template
    assert 'id="scheduled-runs-table"' in template
    assert 'id="scheduled-runs-table-body"' in template
    assert 'id="scheduled-run-pagination-summary"' in template
    assert 'id="scheduled-run-prev-page"' in template
    assert 'id="scheduled-run-next-page"' in template
    assert 'id="scheduled-run-page-jump-input"' in template
    assert 'id="scheduled-run-page-jump-btn"' in template
    assert 'id="run-log-modal"' in template
    assert 'id="run-log-status-bar"' in template
    assert 'id="run-log-refresh-btn"' in template
    assert 'id="run-log-stop-btn"' in template
    assert "/static/css/run_center.css?v=" in template
    assert "/static/js/run_center_shared.js?v=" in template
    assert "/static/js/run_center.js?v=" in template
    assert template.index("/static/js/run_center_shared.js?v=") < template.index("/static/js/run_center.js?v=")


def test_run_center_js_bootstraps_scheduled_scope_and_prefills_plan_filter():
    result = run_run_center_js_scenario("scheduled_scope_bootstrap")
    assert result["page_ready"] == "true"
    assert result["control_scope"] == "scheduled"
    assert result["context_href"] == "/scheduled-tasks?scope=scheduled&plan_id=52&source=scheduled-tasks"
    assert result["api_get_paths"] == ["/scheduled-runs?plan_id=52&page=1&page_size=20"]
    assert result["pagination_summary"] == "第 1 / 3 页 · 共 52 条"


def test_run_center_js_retries_task_scope_back_to_registration_workbench():
    result = run_run_center_js_scenario("task_scope_retry_handoff")
    assert result["page_ready"] == "true"
    assert result["control_scope"] == "task"
    assert result["assigned_href"] == (
        "/registration-workbench?retry=1&scope=task"
        "&task_uuid=task-single-01&source=registration-workbench"
    )


def test_run_center_js_escapes_run_rows_before_injecting_html():
    result = run_run_center_js_scenario("safe_row_rendering")
    assert "<script>" not in result["table_html"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result["table_html"]
    assert "&lt;b&gt;boom&lt;/b&gt;" in result["table_html"]


def test_run_center_js_applies_filters_and_updates_pagination_controls():
    result = run_run_center_js_scenario("filter_and_pagination")
    assert result["api_get_paths"] == [
        "/scheduled-runs?plan_id=52&page=1&page_size=20",
        (
            "/scheduled-runs?plan_id=52&task_type=cpa_refill&status=running"
            "&started_from=2026-03-27T08%3A00&started_to=2026-03-27T12%3A00"
            "&page=1&page_size=20"
        ),
        (
            "/scheduled-runs?plan_id=52&task_type=cpa_refill&status=running"
            "&started_from=2026-03-27T08%3A00&started_to=2026-03-27T12%3A00"
            "&page=2&page_size=20"
        ),
    ]
    assert result["pagination_summary"] == "第 2 / 3 页 · 共 52 条"
    assert result["prev_disabled"] is False
    assert result["next_disabled"] is False
    assert result["jump_value"] == "2"


def test_run_center_js_opens_log_modal_and_can_stop_run():
    result = run_run_center_js_scenario("log_modal_and_stop")
    assert "/scheduled-runs/201" in result["api_get_paths"]
    assert "/scheduled-runs/201/logs?offset=0" in result["api_get_paths"]
    assert result["api_post_paths"] == ["/scheduled-runs/201/stop"]
    assert "Run #201" in result["log_status_html"]
    assert "nightly refill" in result["log_status_html"]
    assert "line one" in result["log_console_html"]
    assert result["stop_button_hidden"] is False


def test_run_center_js_renders_retry_action_when_run_list_load_fails():
    result = run_run_center_js_scenario("runs_load_failure")
    assert result["table_html"]
    assert "运行记录加载失败" in result["table_html"]
    assert "重新加载运行记录" in result["table_html"]
