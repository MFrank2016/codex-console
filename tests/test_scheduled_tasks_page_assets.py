from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app


def test_scheduled_tasks_page_requires_auth_and_renders_script():
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.get("/scheduled-tasks", follow_redirects=False)
        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["location"] == "/login?next=/scheduled-tasks"

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/scheduled-tasks"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/scheduled-tasks")
        assert response.status_code == 200
        assert 'id="scheduled-plans-table"' in response.text
        assert "/static/js/scheduled_tasks.js?v=" in response.text


def test_scheduled_tasks_template_extends_workspace_shell_and_keeps_plan_management_hooks():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert '{% extends "_workspace_base.html" %}' in template
    assert "page-head" in template
    assert "workspace-panel" in template
    assert 'id="create-plan-btn"' in template
    assert 'id="refresh-plans-btn"' in template
    assert 'id="scheduled-plans-table"' in template
    assert 'id="scheduled-plans-table-body"' in template
    assert 'id="plan-form-modal"' in template
    assert 'id="plan-form"' in template
    assert 'id="plan-trigger-type"' in template
    assert 'id="plan-config-mode-table"' in template
    assert 'id="plan-config-mode-json"' in template
    assert 'id="plan-config-entries-body"' in template
    assert 'id="plan-config-add-entry-btn"' in template
    assert 'id="plan-modal"' in template
    assert 'id="scheduled-tasks-support-context"' in template


def test_scheduled_tasks_template_no_longer_carries_primary_run_center_shell():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="scheduled-runs-card"' not in template
    assert 'id="scheduled-runs-table"' not in template
    assert 'id="scheduled-runs-table-body"' not in template
    assert 'id="scheduled-run-filter-task-type"' not in template
    assert 'id="scheduled-run-filter-status"' not in template
    assert 'id="scheduled-run-filter-started-from"' not in template
    assert 'id="scheduled-run-filter-started-to"' not in template
    assert 'id="scheduled-run-pagination-summary"' not in template
    assert 'id="scheduled-run-prev-page"' not in template
    assert 'id="scheduled-run-next-page"' not in template
    assert 'id="scheduled-run-page-jump-input"' not in template
    assert 'id="run-detail-modal"' not in template
    assert 'id="run-log-modal"' not in template
    assert 'id="run-log-stop-btn"' not in template


def test_scheduled_tasks_script_stays_focused_on_plan_management_and_support_context():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function escapeHtml(" in script
    assert script.count("escapeHtml(") >= 2
    assert "function loadPlans(" in script
    assert "function openCreatePlanModal(" in script
    assert "function openEditPlanModal(" in script
    assert "function submitPlanForm(" in script
    assert "function togglePlanEnabled(" in script
    assert "function runPlanNow(" in script
    assert "function renderScheduledTasksSupportContext(" in script
    assert 'window.loadPlans = loadPlans' in script
    assert "loadScheduledRuns(" not in script
    assert "openScheduledRunLog(" not in script
    assert "openScheduledRunDetail(" not in script
    assert "buildScheduledRunQuery(" not in script
    assert "/scheduled-runs" not in script


def test_scheduled_tasks_script_surfaces_cpa_service_load_failures_to_users():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "CPA 服务列表加载失败" in script
    assert "toast.error(" in script or "toast.warning(" in script
    assert "loadCpaServices(true)" in script


def test_scheduled_tasks_script_provides_safe_default_cleanup_config():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "TASK_CONFIG_SCHEMAS" in script
    assert "max_probe_count" in script
    assert "max_cleanup_count" in script
    assert "probe_workers" in script
    assert "delete_workers" in script
    assert "refresh_after_days" in script


def test_scheduled_tasks_script_describes_refill_pipeline_default_value():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "pipeline_key" in script
    assert "默认使用 codexgen_pipeline，可切换为 current_pipeline" in script


def test_scheduled_tasks_script_contains_config_editor_mode_and_serialization_hooks():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function renderConfigEntries(" in script
    assert "function buildConfigPayloadFromEntries(" in script
    assert "function syncRawJsonFromConfigEntries(" in script
    assert "function syncConfigEntriesFromRawJson(" in script
    assert "function switchConfigEditorMode(" in script
    assert "config_meta" in script
