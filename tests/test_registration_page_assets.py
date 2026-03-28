from pathlib import Path
import re

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app
from tests_runtime.app_js_harness import run_app_js_scenario


def test_registration_workbench_page_requires_auth_and_renders_workspace_shell_hooks():
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
        assert 'data-page-key="registration_workbench"' in response.text
        assert 'id="registration-form"' in response.text
        assert 'id="task-step-waterfall"' not in response.text
        assert "/static/js/registration_stream.js?v=" in response.text
        assert response.text.index("/static/js/registration_stream.js?v=") < response.text.index("/static/js/app.js?v=")
        assert 'href="/registration-workbench"' in response.text
        assert 'href="/logout"' in response.text
        assert re.search(r'class="[^"]*\btheme-toggle\b[^"]*"', response.text)
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


def test_registration_template_contains_unlimited_mode_and_domain_stats_container():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert '<option value="unlimited">无限注册</option>' in template
    assert 'id="batch-consecutive-failures"' in template
    assert 'id="batch-domain-stats"' in template


def test_registration_template_contains_pipeline_selector_without_task_step_waterfall():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="pipeline-key"' in template
    assert 'value="current_pipeline"' in template
    assert 'value="codexgen_pipeline"' in template
    assert 'id="task-step-waterfall"' not in template


def test_registration_template_loads_registration_stream_before_app_js():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    stream_src = "/static/js/registration_stream.js?v="
    app_src = "/static/js/app.js?v="
    assert stream_src in template
    assert app_src in template
    assert template.index(stream_src) < template.index(app_src)


def test_registration_template_contains_stream_status_panel_hook():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-stream-status"' in template


def test_registration_template_contains_log_auto_scroll_toggle():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-log-auto-scroll"' in template
    assert "自动滚动" in template


def test_registration_template_contains_runtime_timer_fields():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="single-progress-elapsed"' in template
    assert 'id="batch-progress-elapsed"' in template
    assert 'id="batch-progress-avg-elapsed"' in template
    assert "任务耗时" in template
    assert "总耗时" in template
    assert "平均耗时" in template


def test_registration_template_contains_realtime_feedback_panels():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-config-panel"' in template
    assert 'id="registration-single-progress"' in template
    assert 'id="registration-batch-summary"' in template
    assert 'id="registration-stream-status"' in template
    assert "/static/css/registration_workbench.css" in template


def test_registration_template_uses_workbench_layout_classes():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert "registration-workbench-layout" in template
    assert "registration-workbench-main" in template
    assert "registration-workbench-side" in template


def test_registration_template_contains_workbench_tabs_and_views():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-workbench-tabs"' in template
    assert 'data-workbench-view="config"' in template
    assert 'data-workbench-view="running"' in template
    assert 'data-workbench-view="recent"' in template
    assert 'data-workbench-panel="config"' in template
    assert 'data-workbench-panel="running"' in template
    assert 'data-workbench-panel="recent"' in template


def test_registration_template_recent_accounts_uses_shared_table_shell():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert "recent-accounts-table table-shell" in template or "table-shell recent-accounts-table" in template


def test_registration_template_contains_use_proxy_controls_in_config_panel():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="use-proxy"' in template
    assert 'id="proxy"' in template


def test_registration_template_contains_recent_tasks_panel_and_failure_filter_hooks():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert 'id="recent-registration-tasks-table"' in template
    assert 'id="refresh-tasks-btn"' in template
    assert 'id="failure-filter-proxy-ip"' in template
    assert 'id="failure-filter-email-service-id"' in template


def test_registration_workbench_email_service_dropdown_hides_single_outlook_option():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    script = Path("static/js/app.js").read_text(encoding="utf-8")

    assert '<option value="outlook">Outlook</option>' not in template
    assert "option.value = `outlook:${service.id}`;" not in script
    assert "batchOption.value = 'outlook_batch:all';" in script


def test_registration_workbench_stylesheet_stretches_console_log_for_taller_log_panel():
    stylesheet = Path("static/css/registration_workbench.css").read_text(encoding="utf-8")
    assert ".feedback-panel-log .console-log" in stylesheet
    assert "height: 420px" in stylesheet


def test_registration_running_view_removes_tips_sidebar_and_keeps_log_full_width():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    stylesheet = Path("static/css/registration_workbench.css").read_text(encoding="utf-8")

    assert "运行提示" not in template
    assert "registration-running-side" not in template
    assert ".registration-workbench-layout--running" in stylesheet
    assert "registration-log-console--immersive" in stylesheet
    assert "height: 560px" in stylesheet


def test_app_js_switches_registration_workbench_views():
    result = run_app_js_scenario("switch_workbench_view")
    assert result == {
        "active_view_initial": "config",
        "active_view_after_click": "running",
        "config_hidden_after_click": True,
        "running_hidden_after_click": False,
        "recent_hidden_after_click": True,
    }


def test_registration_workbench_template_uses_task_elapsed_label_without_overall_elapsed_copy():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert "整体耗时" not in template
    assert 'id="single-progress-elapsed"' in template
    assert "任务耗时" in template


def test_registration_workbench_stylesheet_uses_theme_neutral_log_panel_surface():
    stylesheet = Path("static/css/registration_workbench.css").read_text(encoding="utf-8")
    assert "background: var(--surface);" in stylesheet
    assert "background: #0f172a;" not in stylesheet


def test_app_js_posts_count_zero_for_unlimited_mode():
    result = run_app_js_scenario("unlimited_mode_request")
    assert result["batch_count_display"] == "none"
    assert result["request_payload"]["count"] == 0
    assert result["saved_active_task"]["mode"] == "unlimited"


def test_app_js_posts_selected_pipeline_key_for_batch_request():
    result = run_app_js_scenario("pipeline_batch_request")
    assert result["request_payload"]["pipeline_key"] == "codexgen_pipeline"


def test_app_js_single_registration_only_shows_single_panel_in_running_view():
    result = run_app_js_scenario("single_running_presentation")
    assert result == {
        "active_view": "running",
        "single_panel_hidden": False,
        "batch_panel_hidden": True,
        "log_panel_immersive": True,
    }


def test_app_js_batch_registration_only_shows_batch_panel_in_running_view():
    result = run_app_js_scenario("batch_running_presentation")
    assert result == {
        "active_view": "running",
        "single_panel_hidden": True,
        "batch_panel_hidden": False,
        "log_panel_immersive": True,
    }


def test_app_js_keeps_batch_submission_after_reset_when_ui_mode_still_batch():
    result = run_app_js_scenario("batch_mode_persists_after_reset")
    assert result["reg_mode_value"] == "batch"
    assert result["request_path"] == "/registration/batch"


def test_app_js_builds_use_proxy_request_matrix_from_config_controls():
    result = run_app_js_scenario("single_use_proxy_request_matrix")
    assert result["disabled_request"]["use_proxy"] is False
    assert result["disabled_request"]["proxy"] is None
    assert result["enabled_request"]["use_proxy"] is True
    assert result["enabled_request"]["proxy"] == "http://manual-static:8000"


def test_app_js_single_task_flow_fetches_task_detail_without_rendering_step_waterfall():
    result = run_app_js_scenario("single_task_step_refresh")
    assert "/registration/tasks/task-single-01" in result["api_get_paths"]
    assert result["waterfall_html"] == ""
    assert result["waterfall_display"] in {"", "none"}


def test_app_js_keeps_codexgen_single_task_step_waterfall_absent():
    result = run_app_js_scenario("codexgen_single_task_hides_steps")
    assert result["waterfall_html"] == ""
    assert result["waterfall_display"] in {"", "none"}


def test_app_js_renders_single_task_progress_summary_instead_of_waterfall_primary_view():
    result = run_app_js_scenario("single_task_progress_summary")
    assert result["progress_step_text"] == "第 2 / 5 步"
    assert result["progress_current_step"] == "submit_login_email"
    assert result["progress_bar_width"] == "40%"
    assert result["progress_elapsed_text"] == "00:00:12"


def test_app_js_renders_single_task_runtime_timer_from_started_at():
    result = run_app_js_scenario("single_task_runtime_timer")
    assert result["progress_elapsed_text"] == "01:01:01"
    assert result["progress_elapsed_after_tick"] == "01:01:02"


def test_app_js_treats_naive_utc_started_at_as_utc_for_runtime_timer():
    result = run_app_js_scenario("single_task_runtime_timer_naive_utc")
    assert result["progress_elapsed_text"] == "01:01:01"
    assert result["progress_elapsed_after_tick"] == "01:01:02"


def test_app_js_load_recent_registration_tasks_renders_proxy_ip_and_email_service_id():
    result = run_app_js_scenario("load_recent_registration_tasks")
    assert "/registration/tasks?page=1&page_size=10" in result["api_get_paths"]
    assert "8.8.8.8" in result["table_html"]
    assert "42" in result["table_html"]


def test_app_js_load_registration_failures_includes_proxy_ip_and_email_service_id_filters():
    result = run_app_js_scenario("load_registration_failures")
    assert any("proxy_ip=8.8.8.8" in path for path in result["api_get_paths"])
    assert any("email_service_id=42" in path for path in result["api_get_paths"])


def test_app_js_render_registration_failure_rows_marks_rate_limit_entries():
    result = run_app_js_scenario("render_registration_failure_rows")
    assert "限流" in result["table_html"]
    assert "failure-row-rate-limit" in result["table_html"]


def test_app_js_freezes_single_task_elapsed_when_task_reaches_terminal_status():
    result = run_app_js_scenario("single_task_terminal_freezes_elapsed")
    assert result["progress_elapsed_before_finalize"] == "01:01:01"
    assert result["progress_elapsed_after_finalize"] == "01:01:06"
    assert result["runtime_handle_cleared"] is True


def test_app_js_renders_unlimited_progress_without_domain_stats_until_finished():
    result = run_app_js_scenario("unlimited_progress_running")
    assert result["progress_text"] == "5/∞"
    assert result["progress_percent"] == "运行中"
    assert result["progress_bar_indeterminate"] is True
    assert result["consecutive_failures_text"] == "3/10"
    assert result["domain_stats_display"] == "none"
    assert result["domain_stats_html"] == ""
    assert result["batch_elapsed_text"] == "01:01:01"
    assert result["batch_avg_elapsed_text"] == "00:30:30"
    assert result["batch_avg_elapsed_zero_success_text"] == "—"


def test_app_js_renders_unlimited_final_domain_stats_with_rate_columns():
    result = run_app_js_scenario("unlimited_progress_finished")
    assert result["progress_text"] == "8/∞"
    assert result["progress_percent"] == "已结束"
    assert result["progress_bar_indeterminate"] is True
    assert "gmail.com" in result["domain_stats_html"]
    assert "成功率" in result["domain_stats_html"]
    assert "失败率" in result["domain_stats_html"]
    assert "75.00%" in result["domain_stats_html"]
    assert "25.00%" in result["domain_stats_html"]


def test_app_js_restore_unlimited_task_uses_batch_endpoint():
    result = run_app_js_scenario("restore_unlimited_task")
    assert result["api_get_paths"] == ["/registration/batch/batch-unlimited-01"]
    assert result["batch_progress_display"] == "block"


def test_registration_realtime_store_reduces_snapshot_and_tracks_connection_state():
    result = run_app_js_scenario("realtime_store_seq_dedup")
    assert result["current_step_key"] == "submit_login_email"
    assert result["batch_success"] == "3"
    assert result["log_count"] == 2
    assert result["rendered_log_count"] == 2
    assert result["connection_status"] == "polling"


def test_registration_realtime_store_appends_log_when_window_is_full():
    result = run_app_js_scenario("realtime_store_full_window_log_append")
    assert result["log_count"] == 500
    assert result["rendered_log_count"] == 500
    assert result["last_rendered_contains_after_full"] is True


def test_realtime_log_appended_event_updates_console_without_waiting_for_task_detail_refresh():
    result = run_app_js_scenario("single_task_log_event_immediate_append")
    assert result["rendered_log_count"] == 2
    assert result["last_rendered_contains_live_line"] is True


def test_registration_workbench_uses_shared_console_for_single_task_live_append():
    result = run_app_js_scenario("shared_console_single_task_live_append")

    assert result["console_has_shared_class"] is True
    assert result["rendered_log_count"] == 2
    assert result["last_line_level_class"] == "realtime-log-level-info"
    assert result["legacy_direct_append_path_used"] is False
    assert result["teardown_closed_ws"] is True
    assert result["teardown_stopped_fallback"] is True


def test_registration_workbench_preserves_manual_scroll_when_shared_console_receives_new_logs():
    result = run_app_js_scenario("shared_console_manual_scroll_preserved")

    assert result["auto_scroll_disabled_after_manual_scroll"] is True
    assert result["scroll_top_after_live_append"] == 120
    assert result["last_rendered_contains_live_line"] is True


def test_registration_workbench_log_auto_scroll_toggle_controls_shared_console_behavior():
    result = run_app_js_scenario("shared_console_auto_scroll_toggle_ui")

    assert result["scroll_top_after_disable_and_append"] == 120
    assert result["scroll_top_after_reenable_and_append"] == 1200
    assert result["checkbox_checked_after_reenable"] is True


def test_registration_workbench_falls_back_to_stream_polling_when_websocket_handshake_stalls():
    result = run_app_js_scenario("single_task_ws_handshake_timeout_falls_back_to_polling")

    assert result["connection_status"] == "轮询中"
    assert "/registration/streams/task/task-single-01/snapshot" in result["api_get_paths"]
    assert result["polling_interval_started"] is True


def test_app_js_builds_run_center_href_for_single_task_context():
    result = run_app_js_scenario("build_run_center_href_single_task")
    assert result["href"] == (
        "/run-center?scope=task&task_uuid=task-single-01"
        "&source=registration-workbench"
    )


def test_app_js_builds_run_center_href_for_batch_context():
    result = run_app_js_scenario("build_run_center_href_batch")
    assert result["href"] == (
        "/run-center?scope=batch&batch_id=batch-001"
        "&source=registration-workbench"
    )


def test_app_js_uses_shared_realtime_log_client_without_legacy_dom_append_main_path():
    script = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "window.realtimeLogClient.createStreamClient" in script
    assert "appendLogLine(getLogType(message)" not in script


def test_app_js_task_realtime_fallback_prefers_stream_events_over_legacy_logs_endpoint():
    script = Path("static/js/app.js").read_text(encoding="utf-8")

    # 方案 C：主链路的轮询兜底应基于 streams/events，而不是旧的 /tasks/{uuid}/logs
    assert "/registration/streams/task/${taskUuid}/events?after_seq=${afterSeq}" in script
    assert "startTaskStreamPolling(" in script

    # 旧 logs 轮询仅保留为极小兼容兜底（store 未建立且收到 snapshot_required）
    assert "function startLogPolling(" in script
    assert script.count("startLogPolling(taskUuid);") == 1
    assert "startLogPolling(currentTask.task_uuid)" not in script


def test_app_js_snapshot_required_terminal_task_snapshot_finalizes_single_task_flow():
    result = run_app_js_scenario("single_task_snapshot_required_terminal_snapshot_should_finalize")
    assert result["start_disabled"] is False
    assert result["cancel_disabled"] is True
    assert result["ws_ready_state"] == 3  # MockWebSocket.CLOSED
    assert result["connection_status"] == "已断开"


def test_app_js_snapshot_required_terminal_batch_snapshot_finalizes_batch_flow():
    result = run_app_js_scenario("batch_snapshot_required_terminal_snapshot_should_finalize")
    assert result["start_disabled"] is False
    assert result["cancel_disabled"] is True
    assert result["ws_ready_state"] == 3  # MockWebSocket.CLOSED
    assert result["connection_status"] == "已断开"


def test_app_js_batch_websocket_error_fallback_uses_registration_batch_endpoint_for_non_outlook_batch():
    result = run_app_js_scenario("batch_ws_error_fallback_non_outlook_uses_registration_batch_endpoint")
    assert "/registration/batch/batch-001" in result["api_get_paths"]
    assert "/registration/outlook-batch/batch-001" not in result["api_get_paths"]


def test_execution_and_configuration_templates_extend_workspace_shell():
    for path in [
        "templates/accounts.html",
        "templates/scheduled_tasks.html",
        "templates/email_services.html",
        "templates/settings.html",
        "templates/payment.html",
    ]:
        template = Path(path).read_text(encoding="utf-8")
        assert '{% extends "_workspace_base.html" %}' in template


def test_payment_page_uses_centralized_workspace_shell_context():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/payment")

    assert response.status_code == 200
    assert 'data-page-key="payment"' in response.text
    assert "支付升级" in response.text
    assert 'href="/payment"' in response.text

    template = Path("templates/payment.html").read_text(encoding="utf-8")
    assert "page_key is not defined" not in template
    assert "workspace_nav is not defined" not in template


def test_accounts_template_contains_pagination_jump_controls():
    template = Path("templates/accounts.html").read_text(encoding="utf-8")
    assert 'id="page-jump-input"' in template
    assert 'id="page-jump-btn"' in template


def test_accounts_template_filter_panel_uses_shared_shell_classes():
    template = Path("templates/accounts.html").read_text(encoding="utf-8")
    assert "filter-panel" in template
    assert "filter-panel-grid" in template
    assert "filter-panel-actions" in template
    assert "pagination-panel" in template
    assert "pagination-jump" in template
    toolbar_card_tag = _get_div_by_class_tokens(template, {"card", "toolbar-card"})
    assert toolbar_card_tag is not None
    _assert_tag_class_lacks(toolbar_card_tag, "filter-panel")
    _assert_tag_class_lacks(toolbar_card_tag, "toolbar")

    toolbar_body_tag = _get_div_by_class_tokens(template, {"card-body", "filter-panel"})
    assert toolbar_body_tag is not None
    _assert_tag_class_contains(toolbar_body_tag, "card-body")
    _assert_tag_class_contains(toolbar_body_tag, "filter-panel")
    _assert_tag_class_lacks(toolbar_body_tag, "toolbar")

    cpa_input_tag = _get_tag_by_id(template, "input", "filter-primary-cpa-service-id")
    search_input_tag = _get_tag_by_id(template, "input", "search-input")
    page_jump_input_tag = _get_tag_by_id(template, "input", "page-jump-input")
    assert "style=" not in cpa_input_tag
    assert "style=" not in search_input_tag
    assert "style=" not in page_jump_input_tag


def test_shared_stylesheet_defines_filter_and_pagination_panel_selectors():
    stylesheet = Path("static/css/workspace_components.css").read_text(encoding="utf-8")
    assert ".filter-panel" in stylesheet
    assert ".filter-panel-grid" in stylesheet
    assert ".filter-panel-actions" in stylesheet
    assert ".pagination-panel" in stylesheet
    assert ".pagination-jump" in stylesheet
    assert ".filter-input-cpa-service-id" in stylesheet
    assert ".filter-input-search" in stylesheet
    assert ".pagination-jump-input" in stylesheet


def test_shared_stylesheet_removes_task_step_waterfall_selectors():
    stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".task-step-waterfall" not in stylesheet
    assert ".task-step-card" not in stylesheet
    assert ".task-step-meta" not in stylesheet


def _get_div_by_class_tokens(template: str, class_tokens: set[str]) -> str | None:
    for match in re.finditer(r"<div\b[^>]*>", template):
        tag = match.group(0)
        class_match = re.search(r'class\s*=\s*"([^"]*)"', tag)
        if class_match is None:
            continue
        classes = set(class_match.group(1).split())
        if class_tokens.issubset(classes):
            return tag
    return None


def _get_tag_by_id(template: str, tag: str, element_id: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", template)
    assert match is not None, f"missing <{tag}> with id={element_id}"
    return match.group(0)


def _assert_tag_class_contains(tag_html: str, expected_class: str) -> None:
    class_match = re.search(r'class\s*=\s*"([^"]*)"', tag_html)
    assert class_match is not None, f"missing class attribute: {tag_html}"
    classes = set(class_match.group(1).split())
    assert expected_class in classes, f"class {expected_class!r} missing in {classes!r}"


def _assert_tag_class_lacks(tag_html: str, unexpected_class: str) -> None:
    class_match = re.search(r'class\s*=\s*"([^"]*)"', tag_html)
    assert class_match is not None, f"missing class attribute: {tag_html}"
    classes = set(class_match.group(1).split())
    assert unexpected_class not in classes, f"class {unexpected_class!r} unexpectedly present in {classes!r}"


def run_accounts_js_scenario(name: str) -> dict:
    import json
    import subprocess

    accounts_source = Path("static/js/accounts.js").read_text(encoding="utf-8")
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const accountsSource = {json.dumps(accounts_source)};

function createMockElement(id = '') {{
  return {{
    id,
    style: {{}},
    dataset: {{}},
    className: '',
    classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }}, toggle() {{ return false; }} }},
    disabled: false,
    checked: false,
    value: '',
    textContent: '',
    innerHTML: '',
    _listeners: {{}},
    addEventListener(type, handler) {{ this._listeners[type] = handler; }},
    dispatchEvent(type, event = {{}}) {{
      if (this._listeners[type]) {{
        return this._listeners[type](event);
      }}
      return undefined;
    }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
    insertAdjacentElement() {{}},
    blur() {{}},
    click() {{}},
    remove() {{}},
  }};
}}

const elementsById = new Map();
function getElement(id) {{
  if (!elementsById.has(id)) {{
    elementsById.set(id, createMockElement(id));
  }}
  return elementsById.get(id);
}}

const domListeners = {{}};
const body = createMockElement('body');
body.appendChild = () => {{}};
const document = {{
  activeElement: null,
  getElementById(id) {{ return getElement(id); }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  addEventListener(type, handler) {{ domListeners[type] = handler; }},
  createElement() {{ return createMockElement(); }},
  body,
}};

const context = {{
  console,
  URLSearchParams,
  document,
  window: {{
    location: {{ protocol: 'http:', host: 'localhost' }},
    URL: {{
      createObjectURL() {{ return 'blob:test'; }},
      revokeObjectURL() {{}},
    }},
  }},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  setTimeout,
  clearTimeout,
  theme: {{ toggle() {{}} }},
  debounce: (fn) => fn,
  delegate() {{}},
  escapeHtml(value) {{ return String(value); }},
  copyToClipboard() {{}},
  format: {{
    number(value) {{ return String(value ?? 0); }},
    date(value) {{ return value ? String(value) : '-'; }},
  }},
  __apiPosts: [],
  __fetchCalls: [],
  api: {{
    async get(path) {{
      if (path.includes('/accounts?')) return {{ total: 0, accounts: [] }};
      if (path === '/accounts/stats/summary') return {{ total: 0, by_status: {{ active: 0, expired: 0, failed: 0 }} }};
      return {{}};
    }},
    async post(path, payload) {{
      context.__apiPosts.push([String(path), payload ?? null]);
      if (path === '/accounts/batch-delete') {{
        return {{ deleted_count: 2 }};
      }}
      if (path === '/payment/accounts/batch-check-subscription') {{
        return {{ success_count: (payload?.ids || []).length, failed_count: 0 }};
      }}
      return {{ success: true }};
    }},
    async patch() {{ return {{ success: true }}; }},
    async delete() {{ return {{ success: true }}; }},
  }},
  __toasts: [],
  toast: {{
    info(message) {{ context.__toasts.push(['info', String(message)]); }},
    success(message) {{ context.__toasts.push(['success', String(message)]); }},
    warning(message) {{ context.__toasts.push(['warning', String(message)]); }},
    error(message) {{ context.__toasts.push(['error', String(message)]); }},
  }},
  confirm: async () => true,
  fetch: async (url, options = {{}}) => {{
    context.__fetchCalls.push([
      String(url),
      options?.body ? JSON.parse(options.body) : null,
    ]);
    return {{
      ok: true,
      json: async () => ({{}}),
      blob: async () => ({{}}),
      headers: {{
        get(name) {{
          return name === 'Content-Disposition' ? 'attachment; filename=test.json' : null;
        }},
      }},
    }};
  }},
}};
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(
  accountsSource + `
;globalThis.__accountsTestExports = {{
    initEventListeners,
    updatePagination,
    updateBatchButtons,
    buildBatchPayload,
    exportAccounts,
    elements,
    setState(state) {{
      if ('currentPage' in state) currentPage = state.currentPage;
      if ('pageSize' in state) pageSize = state.pageSize;
      if ('totalAccounts' in state) totalAccounts = state.totalAccounts;
      if ('isLoading' in state) isLoading = state.isLoading;
    }},
    setCurrentFilters(state) {{
      currentFilters = {{ ...currentFilters, ...state }};
    }},
    setSelectionState(state) {{
      if ('selectedAccounts' in state) selectedAccounts = new Set(state.selectedAccounts);
      if ('selectAllPages' in state) selectAllPages = state.selectAllPages;
    }},
    getState() {{ return {{ currentPage, pageSize, totalAccounts, isLoading }}; }},
    replaceLoadAccounts(fn) {{ loadAccounts = fn; }},
    replaceLoadStats(fn) {{ loadStats = fn; }},
    getToasts() {{ return [...globalThis.__toasts]; }},
    getApiPosts() {{ return JSON.parse(JSON.stringify(globalThis.__apiPosts)); }},
    getFetchCalls() {{ return JSON.parse(JSON.stringify(globalThis.__fetchCalls)); }},
  }};`,
  context,
);

const exported = context.__accountsTestExports;

async function trigger(type, element, event = {{}}) {{
  if (element._listeners[type]) {{
    return await element._listeners[type](event);
  }}
}}

async function runScenario() {{
  const input = exported.elements.pageJumpInput;
  const button = exported.elements.pageJumpBtn;

  switch (scenarioName) {{
    case 'jump_wiring_click_and_enter': {{
      let loadCalls = 0;
      let enterPrevented = false;
      exported.replaceLoadAccounts(() => {{ loadCalls += 1; }});
      exported.setState({{ currentPage: 1, pageSize: 20, totalAccounts: 100, isLoading: false }});
      exported.initEventListeners();

      input.value = '3';
      await trigger('click', button);

      input.value = '4';
      await trigger('keydown', input, {{ key: 'Enter', preventDefault() {{ enterPrevented = true; }} }});

      return {{
        hasClickListener: Boolean(button._listeners.click),
        hasKeydownListener: Boolean(input._listeners.keydown),
        loadCalls,
        enterPrevented,
        currentPage: exported.getState().currentPage,
      }};
    }}
    case 'jump_clamps_and_avoids_duplicate_reload': {{
      let loadCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadCalls += 1; }});
      exported.setState({{ currentPage: 2, pageSize: 20, totalAccounts: 95, isLoading: false }});
      exported.initEventListeners();

      input.value = '999';
      await trigger('click', button);

      input.value = '5';
      await trigger('click', button);

      return {{
        currentPage: exported.getState().currentPage,
        loadCalls,
        toasts: exported.getToasts(),
      }};
    }}
    case 'jump_rejects_decimal': {{
      let loadCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadCalls += 1; }});
      exported.setState({{ currentPage: 3, pageSize: 20, totalAccounts: 95, isLoading: false }});
      exported.initEventListeners();

      input.value = '1.9';
      await trigger('click', button);

      return {{
        currentPage: exported.getState().currentPage,
        loadCalls,
        toasts: exported.getToasts(),
      }};
    }}
    case 'jump_rejects_scientific_notation': {{
      let loadCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadCalls += 1; }});
      exported.setState({{ currentPage: 3, pageSize: 20, totalAccounts: 95, isLoading: false }});
      exported.initEventListeners();

      input.value = '1e2';
      await trigger('click', button);

      return {{
        currentPage: exported.getState().currentPage,
        loadCalls,
        toasts: exported.getToasts(),
      }};
    }}
    case 'update_pagination_disables_controls_when_empty': {{
      exported.setState({{ currentPage: 1, pageSize: 20, totalAccounts: 0, isLoading: false }});
      document.activeElement = createMockElement('other');
      exported.updatePagination();
      return {{
        prevDisabled: exported.elements.prevPage.disabled,
        nextDisabled: exported.elements.nextPage.disabled,
        jumpInputDisabled: exported.elements.pageJumpInput.disabled,
        jumpBtnDisabled: exported.elements.pageJumpBtn.disabled,
      }};
    }}
    case 'update_pagination_focus_and_max': {{
      exported.setState({{ currentPage: 4, pageSize: 20, totalAccounts: 95, isLoading: false }});
      input.value = '42';
      document.activeElement = input;
      exported.updatePagination();
      const focusedValue = input.value;
      const maxAfterFocused = input.max;

      document.activeElement = createMockElement('other');
      exported.updatePagination();
      const blurredValue = input.value;

      return {{
        focusedValue,
        blurredValue,
        maxAfterFocused,
      }};
    }}
    case 'refresh_button_click_triggers_stats_and_list_reload': {{
      let loadAccountsCalls = 0;
      let loadStatsCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadAccountsCalls += 1; }});
      exported.replaceLoadStats(() => {{ loadStatsCalls += 1; }});
      exported.initEventListeners();

      await trigger('click', exported.elements.refreshBtn);

      return {{
        hasClickListener: Boolean(exported.elements.refreshBtn._listeners.click),
        loadAccountsCalls,
        loadStatsCalls,
        toasts: exported.getToasts(),
      }};
    }}
    case 'batch_check_subscription_posts_selected_ids_and_reload': {{
      let loadAccountsCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadAccountsCalls += 1; }});
      exported.setSelectionState({{ selectedAccounts: [11, 12], selectAllPages: false }});
      exported.initEventListeners();

      await trigger('click', exported.elements.batchCheckSubBtn);

      return {{
        hasClickListener: Boolean(exported.elements.batchCheckSubBtn._listeners.click),
        apiPosts: exported.getApiPosts(),
        loadAccountsCalls,
        buttonDisabled: exported.elements.batchCheckSubBtn.disabled,
        buttonText: exported.elements.batchCheckSubBtn.textContent,
        toasts: exported.getToasts(),
      }};
    }}
    case 'batch_delete_select_all_uses_primary_cpa_filter_and_resets_buttons': {{
      let loadAccountsCalls = 0;
      let loadStatsCalls = 0;
      exported.replaceLoadAccounts(() => {{ loadAccountsCalls += 1; }});
      exported.replaceLoadStats(() => {{ loadStatsCalls += 1; }});
      exported.setState({{ totalAccounts: 23 }});
      exported.setCurrentFilters({{
        status: 'active',
        email_service: 'tempmail',
        search: 'needle',
        primary_cpa_service_id: '7',
      }});
      exported.setSelectionState({{ selectedAccounts: [11, 12], selectAllPages: true }});
      exported.updateBatchButtons();
      exported.initEventListeners();

      await trigger('click', exported.elements.batchDeleteBtn);

      return {{
        apiPosts: exported.getApiPosts(),
        loadAccountsCalls,
        loadStatsCalls,
        buttonDisabled: exported.elements.batchDeleteBtn.disabled,
        buttonText: exported.elements.batchDeleteBtn.textContent,
        toasts: exported.getToasts(),
      }};
    }}
    case 'export_accounts_select_all_uses_primary_cpa_filter': {{
      exported.setState({{ totalAccounts: 23 }});
      exported.setCurrentFilters({{
        status: 'active',
        email_service: 'tempmail',
        search: 'needle',
        primary_cpa_service_id: '7',
      }});
      exported.setSelectionState({{ selectedAccounts: [11, 12], selectAllPages: true }});
      exported.updateBatchButtons();

      await exported.exportAccounts('json');

      return {{
        fetchCalls: exported.getFetchCalls(),
        toasts: exported.getToasts(),
      }};
    }}
    default:
      throw new Error(`Unknown scenario: ${{scenarioName}}`);
  }}
}}

runScenario().then((result) => {{
  process.stdout.write(JSON.stringify(result));
}}).catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_accounts_script_wires_jump_input_to_button_click_and_enter_behavior():
    result = run_accounts_js_scenario("jump_wiring_click_and_enter")
    assert result["hasClickListener"] is True
    assert result["hasKeydownListener"] is True
    assert result["enterPrevented"] is True
    assert result["loadCalls"] == 2
    assert result["currentPage"] == 4


def test_accounts_script_clamps_jump_range_and_avoids_duplicate_reload():
    result = run_accounts_js_scenario("jump_clamps_and_avoids_duplicate_reload")
    assert result["currentPage"] == 5
    assert result["loadCalls"] == 1
    assert any("页码超出范围" in message for _, message in result["toasts"])


def test_accounts_script_rejects_decimal_jump_input_without_coercion():
    result = run_accounts_js_scenario("jump_rejects_decimal")
    assert result["currentPage"] == 3
    assert result["loadCalls"] == 0
    assert any("请输入有效页码" in message for _, message in result["toasts"])


def test_accounts_script_rejects_scientific_notation_jump_input_without_coercion():
    result = run_accounts_js_scenario("jump_rejects_scientific_notation")
    assert result["currentPage"] == 3
    assert result["loadCalls"] == 0
    assert any("请输入有效页码" in message for _, message in result["toasts"])


def test_accounts_script_disables_prev_next_and_jump_when_list_is_empty():
    result = run_accounts_js_scenario("update_pagination_disables_controls_when_empty")
    assert result["prevDisabled"] is True
    assert result["nextDisabled"] is True
    assert result["jumpInputDisabled"] is True
    assert result["jumpBtnDisabled"] is True


def test_accounts_script_update_pagination_does_not_override_focused_input_and_sets_max():
    result = run_accounts_js_scenario("update_pagination_focus_and_max")
    assert result["focusedValue"] == "42"
    assert result["blurredValue"] == "4"
    assert result["maxAfterFocused"] == "5"


def test_accounts_script_refresh_button_reloads_stats_and_list():
    result = run_accounts_js_scenario("refresh_button_click_triggers_stats_and_list_reload")
    assert result["hasClickListener"] is True
    assert result["loadAccountsCalls"] == 1
    assert result["loadStatsCalls"] == 1
    assert ["info", "已刷新"] in result["toasts"]


def test_accounts_script_batch_check_subscription_posts_selected_ids_and_reloads():
    result = run_accounts_js_scenario("batch_check_subscription_posts_selected_ids_and_reload")
    assert result["hasClickListener"] is True
    assert result["apiPosts"] == [[
        "/payment/accounts/batch-check-subscription",
        {"ids": [11, 12]},
    ]]
    assert result["loadAccountsCalls"] == 1
    assert result["buttonDisabled"] is False
    assert result["buttonText"] == "🔍 检测 (2)"
    assert ["success", "成功: 2"] in result["toasts"]


def test_accounts_script_batch_delete_select_all_uses_primary_cpa_filter_and_resets_buttons():
    result = run_accounts_js_scenario("batch_delete_select_all_uses_primary_cpa_filter_and_resets_buttons")
    assert result["apiPosts"] == [[
        "/accounts/batch-delete",
        {
            "ids": [],
            "select_all": True,
            "status_filter": "active",
            "email_service_filter": "tempmail",
            "search_filter": "needle",
            "primary_cpa_service_id_filter": "7",
        },
    ]]
    assert result["loadAccountsCalls"] == 1
    assert result["loadStatsCalls"] == 1
    assert result["buttonDisabled"] is True
    assert result["buttonText"] == "🗑️ 批量删除"
    assert ["success", "成功删除 2 个账号"] in result["toasts"]


def test_accounts_script_export_accounts_select_all_uses_primary_cpa_filter():
    result = run_accounts_js_scenario("export_accounts_select_all_uses_primary_cpa_filter")
    assert result["fetchCalls"] == [[
        "/api/accounts/export/json",
        {
            "ids": [],
            "select_all": True,
            "status_filter": "active",
            "email_service_filter": "tempmail",
            "search_filter": "needle",
            "primary_cpa_service_id_filter": "7",
        },
    ]]
    assert ["info", "正在导出 23 个账号..."] in result["toasts"]
    assert ["success", "导出成功"] in result["toasts"]


def test_web_app_registers_registration_workbench_page_route():
    app_source = Path("src/web/app.py").read_text(encoding="utf-8")
    assert '@app.get("/registration-workbench", response_class=HTMLResponse)' in app_source
    assert 'templates.TemplateResponse(' in app_source
    assert '"index.html"' in app_source
