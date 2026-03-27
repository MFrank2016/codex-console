from fastapi.testclient import TestClient
from pathlib import Path
import json
import re
import subprocess
import tempfile

from src.config.settings import get_settings
from src.web.app import create_app


def _get_tag_by_id(template: str, tag: str, element_id: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", template)
    assert match is not None, f"missing <{tag}> with id={element_id}"
    return match.group(0)


def _assert_tag_class_contains(tag_html: str, expected_class: str) -> None:
    class_match = re.search(r'class\s*=\s*"([^"]*)"', tag_html)
    assert class_match is not None, f"missing class attribute: {tag_html}"
    classes = set(class_match.group(1).split())
    assert expected_class in classes, f"class {expected_class!r} missing in {classes!r}"


def _find_div_start_by_class_tokens(template: str, class_tokens: set[str], start: int = 0) -> tuple[int, int] | None:
    for match in re.finditer(r"<div\b[^>]*>", template[start:]):
        absolute_start = start + match.start()
        absolute_end = start + match.end()
        tag = match.group(0)
        class_match = re.search(r'class\s*=\s*"([^"]*)"', tag)
        if class_match is None:
            continue
        classes = set(class_match.group(1).split())
        if class_tokens.issubset(classes):
            return absolute_start, absolute_end
    return None


def _extract_css_block(stylesheet: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet, re.S)
    assert match is not None, f"missing CSS block for {selector}"
    return match.group(1)


def _extract_css_blocks_for_selector(stylesheet: str, selector: str) -> list[str]:
    selector_blocks: list[str] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", stylesheet, re.S):
        selectors = [token.strip() for token in match.group(1).split(",")]
        if selector in selectors:
            selector_blocks.append(match.group(2))
    assert selector_blocks, f"missing CSS blocks for {selector}"
    return selector_blocks


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
        assert '/static/js/scheduled_tasks.js?v={{ static_version }}' not in response.text
        assert "/static/js/scheduled_tasks.js?v=" in response.text


def test_scheduled_tasks_script_defines_escape_html_helper():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function escapeHtml(" in script
    # 至少要在定义之外被调用一次，否则无法覆盖页面渲染分支
    assert script.count("escapeHtml(") >= 2


def test_scheduled_tasks_template_extends_workspace_shell_and_exposes_page_layout_classes():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert '{% extends "_workspace_base.html" %}' in template
    assert "page-head" in template
    assert "workspace-panel" in template


def test_scheduled_tasks_template_contains_plan_management_hooks():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="create-plan-btn"' in template
    assert 'id="plan-form-modal"' in template
    assert 'id="plan-form"' in template
    assert 'id="plan-trigger-type"' in template
    assert 'id="plan-config-mode-table"' in template
    assert 'id="plan-config-mode-json"' in template
    assert 'id="plan-config-entries-body"' in template
    assert 'id="plan-config-add-entry-btn"' in template


def test_scheduled_tasks_template_contains_run_center_hooks():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="scheduled-runs-table"' in template
    assert 'id="scheduled-runs-table-body"' in template
    assert 'id="scheduled-run-filter-task-type"' in template
    assert 'id="scheduled-run-filter-status"' in template
    assert 'id="scheduled-run-filter-started-from"' in template
    assert 'id="scheduled-run-filter-started-to"' in template
    assert 'id="scheduled-run-filter-apply-btn"' in template
    assert 'id="scheduled-run-filter-reset-btn"' in template
    assert 'id="run-log-status-bar"' in template
    assert 'id="run-log-refresh-btn"' in template
    assert 'id="run-log-auto-scroll"' in template
    assert 'id="run-log-stop-actions"' in template
    assert 'id="run-log-stop-btn"' in template
    assert 'id="run-detail-modal"' in template
    assert 'id="run-detail-modal-body"' in template
    assert 'id="run-log-search-input"' in template
    assert 'id="run-log-level-filter"' in template
    assert 'id="run-log-copy-btn"' in template
    assert 'id="run-log-clear-btn"' in template
    assert 'id="run-log-wrap-input"' in template
    assert 'id="run-log-modal"' in template
    assert 'class="modal-content scheduled-run-log-modal-content"' in template
    assert "scheduled-run-log-modal-content" in template
    run_detail_modal_match = re.search(
        r'<div id="run-detail-modal" class="modal">\s*(<div\b[^>]*>)',
        template,
        re.S,
    )
    assert run_detail_modal_match is not None
    assert "max-width: 960px;" in run_detail_modal_match.group(1)
    run_log_modal_match = re.search(r'<div id="run-log-modal" class="modal">\s*(<div\b[^>]*>)', template, re.S)
    assert run_log_modal_match is not None
    run_log_modal_content_tag = run_log_modal_match.group(1)
    assert "max-width: 960px" not in run_log_modal_content_tag
    class_match = re.search(r'class\s*=\s*"([^"]+)"', run_log_modal_content_tag)
    assert class_match is not None
    assert "scheduled-run-log-modal-content" in class_match.group(1).split()


def test_scheduled_tasks_run_center_filter_panel_uses_shared_shell_classes():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert "filter-panel" in template
    assert "filter-panel-grid" in template
    assert "filter-panel-actions" in template
    assert "pagination-panel" in template
    assert "pagination-jump" in template
    _assert_tag_class_contains(_get_tag_by_id(template, "select", "scheduled-run-filter-task-type"), "form-select")
    _assert_tag_class_contains(_get_tag_by_id(template, "select", "scheduled-run-filter-status"), "form-select")
    _assert_tag_class_contains(_get_tag_by_id(template, "input", "scheduled-run-filter-started-from"), "form-input")
    _assert_tag_class_contains(_get_tag_by_id(template, "input", "scheduled-run-filter-started-to"), "form-input")
    _assert_tag_class_contains(_get_tag_by_id(template, "input", "scheduled-run-page-jump-input"), "form-input")
    _assert_tag_class_contains(_get_tag_by_id(template, "input", "scheduled-run-page-jump-input"), "pagination-jump-input")

    header_span = _find_div_start_by_class_tokens(template, {"card-header", "filter-panel"})
    assert header_span is not None
    _, header_open_end = header_span

    grid_span = _find_div_start_by_class_tokens(template, {"filter-panel-grid"}, start=header_open_end)
    assert grid_span is not None
    grid_start, grid_open_end = grid_span

    actions_span = _find_div_start_by_class_tokens(template, {"filter-panel-actions"}, start=header_open_end)
    assert actions_span is not None
    actions_start, _ = actions_span

    assert grid_start < actions_start
    grid_first_close = template.find("</div>", grid_open_end)
    assert grid_first_close != -1
    assert grid_first_close < actions_start


def test_scheduled_tasks_template_contains_run_center_pagination_hooks():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="scheduled-run-prev-page"' in template
    assert 'id="scheduled-run-next-page"' in template
    assert 'id="scheduled-run-page-jump-input"' in template
    assert 'id="scheduled-run-page-jump-btn"' in template
    assert 'id="scheduled-run-pagination-summary"' in template


def test_scheduled_tasks_template_keeps_pagination_markup_minimal_without_inline_layout_styles():
    template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    assert 'id="scheduled-run-pagination-summary" style=' not in template
    jump_input_match = re.search(r"<input[^>]*id=\"scheduled-run-page-jump-input\"[^>]*>", template)
    assert jump_input_match is not None
    assert "style=" not in jump_input_match.group(0)
    assert 'placeholder="页码"' in jump_input_match.group(0)


def run_scheduled_tasks_pagination_scenario(name: str) -> dict:
    script_source = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scriptSource = {json.dumps(script_source)};

function createMockElement(id = '') {{
  let html = '';
  let text = '';
  const classes = new Set();
  return {{
    id,
    dataset: {{}},
    style: {{}},
    disabled: false,
    value: '',
    checked: false,
    innerHTML: '',
    textContent: '',
    _listeners: {{}},
    setAttribute() {{}},
    removeAttribute() {{}},
    addEventListener(type, handler) {{ this._listeners[type] = handler; }},
    dispatchEvent(type, event = {{}}) {{
      if (this._listeners[type]) return this._listeners[type](event);
      return undefined;
    }},
    scrollIntoView() {{}},
    reset() {{}},
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
      toggle(name) {{
        if (classes.has(name)) {{
          classes.delete(name);
          return false;
        }}
        classes.add(name);
        return true;
      }},
    }},
    get innerHTML() {{ return html; }},
    set innerHTML(next) {{ html = String(next ?? ''); }},
    get textContent() {{ return text; }},
    set textContent(next) {{ text = String(next ?? ''); }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
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
const document = {{
  getElementById(id) {{ return getElement(id); }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  addEventListener(type, handler) {{ domListeners[type] = handler; }},
  createElement() {{
    let value = '';
    return {{
      set textContent(next) {{ value = String(next ?? ''); }},
      get textContent() {{ return value; }},
      get innerHTML() {{ return value; }},
      set innerHTML(next) {{ value = String(next ?? ''); }},
    }};
  }},
}};

const runRequests = [];
const warnings = [];
const totalRuns = scenarioName === 'empty_state_controls_disabled' ? 0 : 95;
const context = {{
  console,
  URLSearchParams,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  document,
  window: {{}},
  theme: {{ toggle() {{}} }},
  format: {{ date(value) {{ return String(value ?? '-'); }} }},
  toast: {{
    warning(message) {{ warnings.push(String(message)); }},
    error() {{}},
    success() {{}},
  }},
  api: {{
    async get(path) {{
      if (path === '/scheduled-plans') return {{ items: [] }};
      if (path === '/cpa-services') return [];
      if (path.startsWith('/scheduled-runs?')) {{
        runRequests.push(path);
        const query = path.includes('?') ? path.slice(path.indexOf('?') + 1) : '';
        const params = new URLSearchParams(query);
        const page = Number.parseInt(params.get('page') || '1', 10);
        const pageSize = Number.parseInt(params.get('page_size') || '20', 10);
        return {{
          items: [],
          total: totalRuns,
          page,
          page_size: pageSize,
        }};
      }}
      if (path.startsWith('/scheduled-runs/')) return {{}};
      throw new Error('unexpected api path: ' + path);
    }},
    async post() {{ return {{}}; }},
    async put() {{ return {{}}; }},
  }},
}};
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(scriptSource, context);

function trigger(type, element, event = {{}}) {{
  const handler = element && element._listeners ? element._listeners[type] : null;
  if (!handler) return;
  handler(event);
}}

async function flush() {{
  await new Promise((resolve) => setTimeout(resolve, 0));
}}

async function runScenario() {{
  if (typeof domListeners.DOMContentLoaded !== 'function') {{
    throw new Error('DOMContentLoaded listener missing');
  }}

  domListeners.DOMContentLoaded();
  await flush();
  await flush();

  const jumpInput = getElement('scheduled-run-page-jump-input');
  const jumpBtn = getElement('scheduled-run-page-jump-btn');
  const prevBtn = getElement('scheduled-run-prev-page');
  const nextBtn = getElement('scheduled-run-next-page');

  switch (scenarioName) {{
    case 'jump_button_click': {{
      jumpInput.value = '3';
      trigger('click', jumpBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{ runRequests, warnings }};
    }}
    case 'jump_enter_key': {{
      jumpInput.value = '4';
      let enterPrevented = false;
      trigger('keydown', jumpInput, {{ key: 'Enter', preventDefault() {{ enterPrevented = true; }} }});
      await flush();
      await flush();
      return {{ runRequests, warnings, enterPrevented }};
    }}
    case 'jump_invalid_input': {{
      jumpInput.value = 'abc';
      trigger('click', jumpBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{ runRequests, warnings }};
    }}
    case 'jump_out_of_range_clamp': {{
      jumpInput.value = '999';
      trigger('click', jumpBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{ runRequests, warnings }};
    }}
    case 'prev_next_wiring': {{
      jumpInput.value = '3';
      trigger('click', jumpBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      trigger('click', prevBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      trigger('click', nextBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{ runRequests, warnings }};
    }}
    case 'focused_input_preserves_user_text': {{
      jumpInput.value = '444';
      document.activeElement = jumpInput;
      trigger('click', nextBtn, {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{ runRequests, warnings, jumpInputValue: jumpInput.value }};
    }}
    case 'empty_state_controls_disabled': {{
      return {{
        runRequests,
        warnings,
        prevDisabled: prevBtn.disabled,
        nextDisabled: nextBtn.disabled,
        jumpInputDisabled: jumpInput.disabled,
        jumpBtnDisabled: jumpBtn.disabled,
      }};
    }}
    default:
      throw new Error('unknown scenario: ' + scenarioName);
  }}
}}

runScenario()
  .then((result) => {{
    process.stdout.write(JSON.stringify(result));
  }})
  .catch((error) => {{
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout or "{}")


def test_scheduled_tasks_pagination_jump_button_click_updates_requested_page():
    result = run_scheduled_tasks_pagination_scenario("jump_button_click")
    assert result["runRequests"][-1].endswith("page=3&page_size=20")


def test_scheduled_tasks_pagination_enter_key_updates_requested_page():
    result = run_scheduled_tasks_pagination_scenario("jump_enter_key")
    assert result["enterPrevented"] is True
    assert result["runRequests"][-1].endswith("page=4&page_size=20")


def test_scheduled_tasks_pagination_invalid_input_warns_without_extra_request():
    result = run_scheduled_tasks_pagination_scenario("jump_invalid_input")
    assert len(result["runRequests"]) == 1
    assert result["runRequests"][0].endswith("page=1&page_size=20")
    assert result["warnings"]


def test_scheduled_tasks_pagination_out_of_range_input_clamps_and_warns():
    result = run_scheduled_tasks_pagination_scenario("jump_out_of_range_clamp")
    assert result["runRequests"][-1].endswith("page=5&page_size=20")
    assert result["warnings"]


def test_scheduled_tasks_pagination_prev_next_buttons_change_requested_page():
    result = run_scheduled_tasks_pagination_scenario("prev_next_wiring")
    assert any(request.endswith("page=2&page_size=20") for request in result["runRequests"])
    assert result["runRequests"][-1].endswith("page=3&page_size=20")


def test_scheduled_tasks_pagination_keeps_jump_input_when_focused():
    result = run_scheduled_tasks_pagination_scenario("focused_input_preserves_user_text")
    assert result["runRequests"][-1].endswith("page=2&page_size=20")
    assert result["jumpInputValue"] == "444"


def test_scheduled_tasks_pagination_disables_prev_next_and_jump_when_list_is_empty():
    result = run_scheduled_tasks_pagination_scenario("empty_state_controls_disabled")
    assert len(result["runRequests"]) == 1
    assert result["prevDisabled"] is True
    assert result["nextDisabled"] is True
    assert result["jumpInputDisabled"] is True
    assert result["jumpBtnDisabled"] is True


def test_shared_list_templates_opt_into_table_shell_styling():
    scheduled_template = Path("templates/scheduled_tasks.html").read_text(encoding="utf-8")
    accounts_template = Path("templates/accounts.html").read_text(encoding="utf-8")
    email_template = Path("templates/email_services.html").read_text(encoding="utf-8")

    assert scheduled_template.count("table-shell") >= 2
    assert "table-shell" in accounts_template
    assert email_template.count("table-shell") >= 2


def test_shared_style_sheet_contains_card_list_system_hooks():
    stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".table-shell" in stylesheet
    assert ".table-actions" in stylesheet
    assert ".scheduled-run-summary" in stylesheet
    assert ".scheduled-run-detail-head" in stylesheet
    assert ".scheduled-run-log-panel" in stylesheet
    assert ".scheduled-run-log-modal-content" in stylesheet
    assert ".scheduled-run-console-shell" in stylesheet
    assert ".scheduled-run-console-status" in stylesheet
    assert ".scheduled-run-console-toolbar" in stylesheet
    assert ".scheduled-run-log-line" in stylesheet
    assert ".scheduled-run-log-level-badge" in stylesheet
    assert ".scheduled-run-log-timestamp" in stylesheet
    assert ".scheduled-run-log-message" in stylesheet
    assert ".scheduled-run-log-level-error" in stylesheet

    shell_block = _extract_css_block(stylesheet, ".scheduled-run-console-shell")
    row_block = _extract_css_block(stylesheet, ".scheduled-run-log-line")
    badge_block = _extract_css_block(stylesheet, ".scheduled-run-log-level-badge")
    assert "line-height: 1.24;" in shell_block
    assert "padding: 6px 8px;" in shell_block
    assert "gap: 6px;" in row_block
    assert "line-height: 1.25;" in badge_block

    status_spacing_blocks = [
        block
        for block in _extract_css_blocks_for_selector(stylesheet, ".scheduled-run-console-status")
        if "padding:" in block or "margin-bottom:" in block
    ]
    toolbar_spacing_blocks = [
        block
        for block in _extract_css_blocks_for_selector(stylesheet, ".scheduled-run-console-toolbar")
        if "padding:" in block or "margin-bottom:" in block
    ]
    assert len(status_spacing_blocks) == 1
    assert len(toolbar_spacing_blocks) == 1
    assert "padding: 6px 8px;" in status_spacing_blocks[0]
    assert "margin-bottom: 6px;" in status_spacing_blocks[0]
    assert "padding: 6px 8px;" in toolbar_spacing_blocks[0]
    assert "margin-bottom: 6px;" in toolbar_spacing_blocks[0]


def test_scheduled_tasks_script_contains_create_edit_enable_disable_hooks():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function openCreatePlanModal(" in script
    assert "function openEditPlanModal(" in script
    assert "function submitPlanForm(" in script
    assert "function togglePlanEnabled(" in script
    assert "/scheduled-plans/${planId}/enable" in script
    assert "/scheduled-plans/${planId}/disable" in script


def test_scheduled_tasks_script_surfaces_cpa_service_load_failures_to_users():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "CPA 服务列表加载失败" in script
    assert "toast.error(" in script
    assert "loadCpaServices(true)" in script


def test_scheduled_tasks_script_provides_safe_default_cleanup_config():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "TASK_CONFIG_SCHEMAS" in script
    assert "max_probe_count" in script
    assert "max_cleanup_count" in script
    assert "probe_workers" in script
    assert "delete_workers" in script
    assert "refresh_after_days" in script


def test_scheduled_tasks_script_contains_config_editor_mode_and_serialization_hooks():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function renderConfigEntries(" in script
    assert "function buildConfigPayloadFromEntries(" in script
    assert "function syncRawJsonFromConfigEntries(" in script
    assert "function syncConfigEntriesFromRawJson(" in script
    assert "function switchConfigEditorMode(" in script
    assert "config_meta" in script


def test_scheduled_tasks_script_renders_key_description_value_description_columns():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "键说明" in script
    assert "值说明" in script
    assert "value_type" in script


def test_scheduled_tasks_script_contains_button_busy_guard_logic():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "data-busy" in script
    assert "disabled = true" in script
    assert "disabled = false" in script


def test_scheduled_tasks_script_renders_plan_row_action_markers():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert 'data-action="detail"' in script
    assert 'data-action="logs"' in script
    assert 'data-action="edit"' in script
    assert 'data-action="toggle"' in script
    assert 'data-action="run-now"' in script
    assert 'data-plan-id="${plan.id}"' in script
    assert 'data-should-enable="${shouldEnable}"' in script
    assert 'onclick="handlePlanAction(this)"' in script


def test_scheduled_tasks_script_routes_actions_through_busy_guard_handlers():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "async function withButtonBusy(" in script
    assert "async function handlePlanAction(button)" in script
    assert "async function handleRunLogAction(button)" in script
    assert "return withButtonBusy(button, async () => {" in script
    assert "onclick=\"handleRunLogAction(this)\"" in script
    assert "withButtonBusy(event.currentTarget, () => loadPlans())" in script


def test_scheduled_tasks_script_contains_run_center_live_log_and_stop_hooks():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "function buildScheduledRunQuery(" in script
    assert "async function loadScheduledRuns(" in script
    assert "function renderScheduledRuns(" in script
    assert "function openScheduledRunDetail(" in script
    assert "function openScheduledRunLog(" in script
    assert "function startScheduledRunLogPolling(" in script
    assert "function stopScheduledRunLogPolling(" in script
    assert "function appendScheduledRunLogChunk(" in script
    assert ("setInterval(" in script or "setTimeout(" in script) and "scheduled-runs" in script
    assert 'data-action="filter-plan-runs"' in script
    assert 'data-action="view-run-detail"' in script
    assert 'data-action="view-run-log"' in script
    assert 'data-action="stop-run"' in script
    assert "async function stopScheduledRun(" in script
    assert '"stopping"' in script or "'stopping'" in script


def test_scheduled_tasks_script_contains_run_center_pagination_jump_hooks():
    script = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    assert "scheduled-run-page-jump-input" in script
    assert "scheduled-run-page-jump-btn" in script
    assert "scheduled-run-prev-page" in script
    assert "scheduled-run-next-page" in script
    assert "keydown" in script and "Enter" in script
    assert "params.set('page_size'" in script
    assert "toast.warning(" in script


def test_scheduled_tasks_render_summaries_as_concise_business_metrics():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const runsBody = makeElement();

global.window = {};
global.document = {
  getElementById: (id) => (id === 'scheduled-runs-table-body' ? runsBody : null),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = { get: async () => ({}), post: async () => ({}), put: async () => ({}) };
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

window.renderScheduledRuns([
  {
    id: 1,
    plan_id: 101,
    plan_name: 'cleanup',
    task_type: 'cpa_cleanup',
    trigger_source: 'manual',
    status: 'success',
    started_at: null,
    finished_at: null,
    summary: { probe_items_selected: 5000, invalid_items_found: 20, remote_deleted: 18, remaining_valid_count: 982 },
  },
  {
    id: 2,
    plan_id: 102,
    plan_name: 'refill',
    task_type: 'cpa_refill',
    trigger_source: 'manual',
    status: 'success',
    started_at: null,
    finished_at: null,
    summary: { uploaded_success: 6 },
  },
  {
    id: 3,
    plan_id: 103,
    plan_name: 'refresh',
    task_type: 'account_refresh',
    trigger_source: 'manual',
    status: 'success',
    started_at: null,
    finished_at: null,
    summary: { processed: 30, refreshed_success: 28, uploaded_success: 27 },
  },
]);

const html = runsBody.innerHTML;
if (!html.includes('扫描 5000 · 清理 18 · 剩余 982')) throw new Error('missing cleanup concise summary: ' + html);
if (!html.includes('补号 6')) throw new Error('missing refill concise summary: ' + html);
if (!html.includes('处理 30 · 刷新 28 · 上传 27')) throw new Error('missing refresh concise summary: ' + html);
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_failed_or_cancelled_runs_append_short_reason_to_summary():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const runsBody = makeElement();

global.window = {};
global.document = {
  getElementById: (id) => (id === 'scheduled-runs-table-body' ? runsBody : null),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = { get: async () => ({}), post: async () => ({}), put: async () => ({}) };
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

window.renderScheduledRuns([
  {
    id: 1,
    plan_id: 101,
    plan_name: 'cleanup',
    task_type: 'cpa_cleanup',
    trigger_source: 'manual',
    status: 'failed',
    started_at: null,
    finished_at: null,
    error_message: '接口超时',
    summary: { probe_items_selected: 5000, invalid_items_found: 12, remote_deleted: 4, remaining_valid_count: 996 },
  },
  {
    id: 2,
    plan_id: 102,
    plan_name: 'refill',
    task_type: 'cpa_refill',
    trigger_source: 'manual',
    status: 'cancelled',
    started_at: null,
    finished_at: null,
    error_message: null,
    summary: { uploaded_success: 3 },
  },
]);

const html = runsBody.innerHTML;
if (!html.includes('扫描 5000 · 清理 4 · 剩余 996 · 原因：接口超时')) {
  throw new Error('missing failed cleanup reason summary: ' + html);
}
if (!html.includes('补号 3 · 原因：用户停止')) {
  throw new Error('missing cancelled refill fallback summary: ' + html);
}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_open_run_detail_renders_detail_only_content():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  let text = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    value: '',
    checked: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    get textContent() { return text; },
    set textContent(next) { text = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const elements = new Map([
  ['run-detail-modal', makeElement()],
  ['run-detail-modal-body', makeElement()],
  ['run-log-modal', makeElement()],
  ['run-log-status-bar', makeElement()],
  ['run-log-modal-body', makeElement()],
  ['run-log-refresh-btn', makeElement()],
  ['run-log-auto-scroll', makeElement()],
  ['run-log-stop-actions', makeElement()],
  ['run-log-stop-btn', makeElement()],
  ['run-log-search-input', makeElement()],
  ['run-log-level-filter', makeElement()],
  ['run-log-copy-btn', makeElement()],
  ['run-log-clear-btn', makeElement()],
  ['run-log-wrap-input', makeElement()],
]);

global.window = {};
global.document = {
  getElementById: (id) => elements.get(id) ?? null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = {
  get: async (url) => {
    if (url === '/scheduled-runs/123') {
      return {
        id: 123,
        plan_id: 1,
        plan_name: 'nightly cleanup',
        task_type: 'cpa_cleanup',
        trigger_source: 'manual',
        started_at: '2026-03-23T10:00:00',
            finished_at: '2026-03-23T10:05:00',
            duration_seconds: 300.5,
            error_message: null,
            summary: { probe_items_selected: 5000, invalid_items_found: 18, remote_deleted: 16, remaining_valid_count: 984 },
            status: 'cancelled',
            last_log_at: '2026-03-23T10:05:00',
            is_running: false,
        stop_requested_at: '2026-03-23T10:04:00',
        stop_requested_by: 'reviewer',
        stop_reason: 'manual_stop',
        can_stop: false,
      };
    }
    if (url.startsWith('/scheduled-runs/123/logs?offset=')) {
      throw new Error('detail flow should not request logs');
    }
    throw new Error('unexpected url: ' + url);
  },
  post: async () => ({}),
  put: async () => ({}),
};
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

async function main() {
  await window.openScheduledRunDetail(123);
  const detailBodyHtml = elements.get('run-detail-modal-body').innerHTML;

  if (!elements.get('run-detail-modal').classList.contains('active')) {
    throw new Error('detail modal should be active');
  }
  if (!detailBodyHtml.includes('scheduled-run-detail-head')) throw new Error('missing detail head hook: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('scheduled-run-detail-grid')) throw new Error('missing detail grid hook: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('scheduled-run-summary')) throw new Error('missing summary hook: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('扫描 5000 · 清理 16 · 剩余 984')) throw new Error('missing concise summary: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('持续时长')) throw new Error('missing duration label: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('300.5 秒')) throw new Error('missing duration value: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('停止请求时间')) throw new Error('missing stop requested at label: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('2026-03-23T10:04:00')) throw new Error('missing stop requested at value: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('停止请求人')) throw new Error('missing stop requested by label: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('reviewer')) throw new Error('missing stop requested by value: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('停止原因')) throw new Error('missing stop reason label: ' + detailBodyHtml);
  if (!detailBodyHtml.includes('manual_stop')) throw new Error('missing stop reason value: ' + detailBodyHtml);
  if (detailBodyHtml.includes('scheduled-run-log-panel')) throw new Error('detail modal should not include logs');
  if (detailBodyHtml.includes('scheduled-run-console-shell')) throw new Error('detail modal should not include console shell');
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_cleanup_summary_shows_considered_count_when_cleanup_is_capped():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const runsBody = makeElement();

global.window = {};
global.document = {
  getElementById: (id) => (id === 'scheduled-runs-table-body' ? runsBody : null),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = { get: async () => ({}), post: async () => ({}), put: async () => ({}) };
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

window.renderScheduledRuns([
  {
    id: 1,
    plan_id: 101,
    plan_name: 'cleanup',
    task_type: 'cpa_cleanup',
    trigger_source: 'manual',
    status: 'success',
    started_at: null,
    finished_at: null,
    summary: {
      probe_items_scanned: 1585,
      probe_items_selected: 1587,
      invalid_items_found: 1395,
      invalid_items_considered: 1000,
      remote_deleted: 1000,
      remaining_valid_count: 995,
    },
  },
]);

const html = runsBody.innerHTML;
if (!html.includes('扫描 1585 · 清理 1000 · 剩余 995')) {
  throw new Error('missing capped cleanup summary: ' + html);
}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_cleanup_summary_uses_dash_when_remaining_count_missing():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const runsBody = makeElement();

global.window = {};
global.document = {
  getElementById: (id) => (id === 'scheduled-runs-table-body' ? runsBody : null),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = { get: async () => ({}), post: async () => ({}), put: async () => ({}) };
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

window.renderScheduledRuns([
  {
    id: 1,
    plan_id: 101,
    plan_name: 'cleanup',
    task_type: 'cpa_cleanup',
    trigger_source: 'manual',
    status: 'success',
    started_at: null,
    finished_at: null,
    summary: {
      probe_items_selected: 1587,
      remote_deleted: 1000,
    },
  },
]);

const html = runsBody.innerHTML;
if (!html.includes('扫描 1587 · 清理 1000 · 剩余 -')) {
  throw new Error('missing cleanup fallback summary: ' + html);
}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def run_scheduled_tasks_log_console_scenario(name: str) -> dict:
    script_source = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scriptSource = {json.dumps(script_source)};

function createMockElement(id = '') {{
  let html = '';
  let text = '';
  const classes = new Set();
  return {{
    id,
    dataset: {{}},
    style: {{}},
    disabled: false,
    value: '',
    checked: false,
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    _listeners: {{}},
    setAttribute() {{}},
    removeAttribute() {{}},
    addEventListener(type, handler) {{ this._listeners[type] = handler; }},
    dispatchEvent(type, event = {{}}) {{
      if (this._listeners[type]) return this._listeners[type](event);
      return undefined;
    }},
    scrollIntoView() {{}},
    reset() {{}},
    classList: {{
      add(name) {{ classes.add(name); }},
      remove(name) {{ classes.delete(name); }},
      contains(name) {{ return classes.has(name); }},
      toggle(name) {{
        if (classes.has(name)) {{
          classes.delete(name);
          return false;
        }}
        classes.add(name);
        return true;
      }},
    }},
    get innerHTML() {{ return html; }},
    set innerHTML(next) {{
      html = String(next ?? '');
      this.scrollHeight = Math.max(html.length, 1);
    }},
    get textContent() {{ return text; }},
    set textContent(next) {{ text = String(next ?? ''); }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
  }};
}}

const elementsById = new Map();
function getElement(id) {{
  if (!elementsById.has(id)) {{
    elementsById.set(id, createMockElement(id));
  }}
  return elementsById.get(id);
}}

[
  'run-detail-modal',
  'run-detail-modal-body',
  'run-log-modal',
  'run-log-status-bar',
  'run-log-refresh-btn',
  'run-log-auto-scroll',
  'run-log-stop-actions',
  'run-log-stop-btn',
  'run-log-modal-body',
  'run-log-console',
  'run-log-search-input',
  'run-log-level-filter',
  'run-log-copy-btn',
  'run-log-clear-btn',
  'run-log-wrap-input',
  'refresh-plans-btn',
  'create-plan-btn',
  'scheduled-run-filter-apply-btn',
  'scheduled-run-filter-reset-btn',
  'scheduled-run-prev-page',
  'scheduled-run-next-page',
  'scheduled-run-page-jump-btn',
  'scheduled-run-page-jump-input',
  'plan-form',
  'plan-trigger-type',
  'plan-task-type',
  'plan-config-mode-table',
  'plan-config-mode-json',
  'plan-config-add-entry-btn',
  'plan-cpa-service-select',
  'plan-config-editor-panel',
  'plan-config-entries-body',
  'plan-config-json-panel',
  'plan-config-json',
  'plan-enabled',
  'plan-form-modal',
  'plan-modal',
].forEach((id) => getElement(id));
getElement('run-log-auto-scroll').checked = true;
getElement('run-log-wrap-input').checked = true;

const domListeners = {{}};
const document = {{
  getElementById(id) {{ return getElement(id); }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  addEventListener(type, handler) {{ domListeners[type] = handler; }},
  createElement() {{
    let value = '';
    return {{
      set textContent(next) {{ value = String(next ?? ''); }},
      get textContent() {{ return value; }},
      get innerHTML() {{ return value; }},
      set innerHTML(next) {{ value = String(next ?? ''); }},
    }};
  }},
}};

let timerCallback = null;
const runRequests = [];
const logRequests = [];
let copiedText = '';
const detailIsRunning = scenarioName === 'second_chunk_reapplies_filters' || scenarioName === 'auto_scroll_disabled_preserves_position';

const defaultFirstChunk = [
  '2026-03-24 09:00:00.100 [INFO] startup ok',
  '2026-03-24 09:00:00.200 [ERROR] boom first',
  '2026-03-24 09:00:00.300 [WARN] warn once',
].join('\n');
const timestampNormalizationChunk = [
  '2026-03-24 09:00:00.100 [INFO] startup ok',
  '2026-03-24 09:00:02 [WARN] warn second precision',
].join('\n');
const copyRegressionChunk = [
  '2026-03-24 09:00:00.100 [INFO] startup ok',
  '2026-03-24 09:00:00.100 [ERROR] boom first',
  '2026-03-24 09:00:00.300 [WARN] warn once',
].join('\n');
const firstChunk = scenarioName === 'timestamp_normalization'
  ? timestampNormalizationChunk
  : (scenarioName === 'copy_visible_logs_preserves_raw_text' ? copyRegressionChunk : defaultFirstChunk);
const secondChunk = '\n' + [
  '2026-03-24 09:00:01.100 [INFO] boom info second',
  '2026-03-24 09:00:01.200 [ERROR] boom second',
].join('\n');
const writeClipboard = async (value) => {{
  copiedText = String(value ?? '');
}};

const context = {{
  console,
  URLSearchParams,
  setTimeout(cb) {{
    timerCallback = cb;
    return 1;
  }},
  clearTimeout() {{
    timerCallback = null;
  }},
  setInterval() {{
    throw new Error('expected self-scheduling polling, not setInterval');
  }},
  clearInterval() {{}},
  document,
  window: {{
    navigator: {{
      clipboard: {{
        writeText: writeClipboard,
      }},
    }},
  }},
  navigator: {{
    clipboard: {{
      writeText: writeClipboard,
    }},
  }},
  theme: {{ toggle() {{}} }},
  format: {{ date(value) {{ return String(value ?? '-'); }} }},
  toast: {{
    warning() {{}},
    error() {{}},
    success() {{}},
  }},
  api: {{
    async get(path) {{
      if (path === '/scheduled-plans') return {{ items: [] }};
      if (path === '/cpa-services') return [];
      if (path.startsWith('/scheduled-runs?')) {{
        runRequests.push(path);
        return {{ items: [], total: 0, page: 1, page_size: 20 }};
      }}
      if (path === '/scheduled-runs/123') {{
        return {{
          id: 123,
          plan_id: 1,
          plan_name: 'nightly cleanup',
          task_type: 'cpa_cleanup',
          trigger_source: 'manual',
          started_at: '2026-03-24T09:00:00',
          finished_at: detailIsRunning ? null : '2026-03-24T09:05:00',
          error_message: null,
          summary: {{ invalid_items_found: 18, remote_deleted: 16 }},
          status: detailIsRunning ? 'running' : 'success',
          last_log_at: '2026-03-24T09:00:00',
          is_running: detailIsRunning,
          stop_requested_at: null,
          can_stop: detailIsRunning,
        }};
      }}
      if (path.startsWith('/scheduled-runs/123/logs?offset=')) {{
        logRequests.push(path);
        if (path.endsWith('offset=0')) {{
          return {{
            chunk: firstChunk,
            next_offset: firstChunk.length,
            has_more: false,
            is_running: detailIsRunning,
            status: detailIsRunning ? 'running' : 'success',
            stop_requested_at: null,
            log_version: 1,
            last_log_at: '2026-03-24T09:00:00',
          }};
        }}
        if (path.endsWith(`offset=${{firstChunk.length}}`)) {{
          return {{
            chunk: secondChunk,
            next_offset: firstChunk.length + secondChunk.length,
            has_more: false,
            is_running: false,
            status: 'success',
            stop_requested_at: null,
            log_version: 2,
            last_log_at: '2026-03-24T09:00:01',
          }};
        }}
        throw new Error('unexpected log request: ' + path);
      }}
      throw new Error('unexpected api path: ' + path);
    }},
    async post() {{ return {{}}; }},
    async put() {{ return {{}}; }},
  }},
}};
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(scriptSource, context);

function trigger(type, element, event = {{}}) {{
  const handler = element && element._listeners ? element._listeners[type] : null;
  if (!handler) return;
  return handler(event);
}}

async function flush() {{
  await new Promise((resolve) => setImmediate(resolve));
}}

async function runScenario() {{
  if (typeof domListeners.DOMContentLoaded !== 'function') {{
    throw new Error('DOMContentLoaded listener missing');
  }}

  domListeners.DOMContentLoaded();
  await flush();
  await flush();

  const searchInput = getElement('run-log-search-input');
  const levelFilter = getElement('run-log-level-filter');
  const logBody = getElement('run-log-modal-body');
  const logConsole = getElement('run-log-console');

  switch (scenarioName) {{
    case 'open_log_console': {{
      await context.window.openScheduledRunLog(123);
      return {{
        logBodyHtml: logBody.innerHTML,
        consoleHtml: logConsole.innerHTML,
        consoleHasShell: logConsole.classList.contains('scheduled-run-console-shell'),
        scrollTop: logConsole.scrollTop,
        scrollHeight: logConsole.scrollHeight,
        logRequests,
        modalActive: getElement('run-log-modal').classList.contains('active'),
      }};
    }}
    case 'timestamp_normalization': {{
      await context.window.openScheduledRunLog(123);
      return {{
        consoleHtml: logConsole.innerHTML,
      }};
    }}
    case 'search_enter': {{
      await context.window.openScheduledRunLog(123);
      const beforeHtml = logConsole.innerHTML;
      searchInput.value = 'boom';
      let enterPrevented = false;
      trigger('keydown', searchInput, {{ key: 'Enter', preventDefault() {{ enterPrevented = true; }} }});
      return {{
        beforeHtml,
        afterHtml: logConsole.innerHTML,
        enterPrevented,
      }};
    }}
    case 'level_filter': {{
      await context.window.openScheduledRunLog(123);
      const beforeHtml = logConsole.innerHTML;
      levelFilter.value = 'ERROR';
      trigger('change', levelFilter, {{ target: levelFilter }});
      return {{
        beforeHtml,
        afterHtml: logConsole.innerHTML,
      }};
    }}
    case 'wrap_toggle': {{
      await context.window.openScheduledRunLog(123);
      const beforeWrap = logConsole.classList.contains('scheduled-run-log-wrap');
      const beforeNoWrap = logConsole.classList.contains('scheduled-run-log-nowrap');
      getElement('run-log-wrap-input').checked = false;
      trigger('change', getElement('run-log-wrap-input'), {{ target: getElement('run-log-wrap-input') }});
      const afterWrap = logConsole.classList.contains('scheduled-run-log-wrap');
      const afterNoWrap = logConsole.classList.contains('scheduled-run-log-nowrap');
      return {{ beforeWrap, beforeNoWrap, afterWrap, afterNoWrap }};
    }}
    case 'second_chunk_reapplies_filters': {{
      await context.window.openScheduledRunLog(123);
      searchInput.value = 'boom';
      trigger('keydown', searchInput, {{ key: 'Enter', preventDefault() {{}} }});
      levelFilter.value = 'ERROR';
      trigger('change', levelFilter, {{ target: levelFilter }});
      const beforeHtml = logConsole.innerHTML;
      if (typeof timerCallback !== 'function') throw new Error('expected polling callback');
      await timerCallback();
      await flush();
      return {{
        beforeHtml,
        afterHtml: logConsole.innerHTML,
        logRequests,
      }};
    }}
    case 'auto_scroll_enabled': {{
      await context.window.openScheduledRunLog(123);
      return {{
        scrollTop: logConsole.scrollTop,
        scrollHeight: logConsole.scrollHeight,
      }};
    }}
    case 'auto_scroll_disabled_preserves_position': {{
      await context.window.openScheduledRunLog(123);
      getElement('run-log-auto-scroll').checked = false;
      logConsole.scrollTop = 17;
      if (typeof timerCallback !== 'function') throw new Error('expected polling callback');
      await timerCallback();
      await flush();
      return {{
        scrollTop: logConsole.scrollTop,
        scrollHeight: logConsole.scrollHeight,
      }};
    }}
    case 'copy_visible_logs_preserves_raw_text': {{
      await context.window.openScheduledRunLog(123);
      levelFilter.value = 'ERROR';
      trigger('change', levelFilter, {{ target: levelFilter }});
      trigger('click', getElement('run-log-copy-btn'), {{ preventDefault() {{}} }});
      await flush();
      await flush();
      return {{
        copiedText,
      }};
    }}
    default:
      throw new Error('unknown scenario: ' + scenarioName);
  }}
}}

runScenario()
  .then((result) => {{
    console.log(JSON.stringify(result));
  }})
  .catch((error) => {{
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_scheduled_tasks_open_run_log_renders_console_shell_and_loads_first_chunk():
    result = run_scheduled_tasks_log_console_scenario("open_log_console")

    assert result["modalActive"] is True
    assert result["consoleHasShell"] is True
    assert ">ERROR<" in result["consoleHtml"]
    assert "boom first" in result["consoleHtml"]
    assert "/scheduled-runs/123/logs?offset=0" in result["logRequests"]




def test_scheduled_tasks_run_log_auto_scroll_scrolls_to_bottom_when_enabled():
    result = run_scheduled_tasks_log_console_scenario("auto_scroll_enabled")

    assert result["scrollHeight"] > 0
    assert result["scrollTop"] == result["scrollHeight"]


def test_scheduled_tasks_run_log_manual_position_is_preserved_when_auto_scroll_is_disabled():
    result = run_scheduled_tasks_log_console_scenario("auto_scroll_disabled_preserves_position")

    assert result["scrollHeight"] > 0
    assert result["scrollTop"] == 17


def test_scheduled_tasks_run_log_search_applies_only_on_enter():
    result = run_scheduled_tasks_log_console_scenario("search_enter")

    assert result["enterPrevented"] is True
    assert "startup ok" in result["beforeHtml"]
    assert "startup ok" not in result["afterHtml"]
    assert ">ERROR<" in result["afterHtml"]
    assert "boom first" in result["afterHtml"]


def test_scheduled_tasks_run_log_level_filter_rerenders_matching_lines_only():
    result = run_scheduled_tasks_log_console_scenario("level_filter")

    assert ">INFO<" in result["beforeHtml"]
    assert "startup ok" in result["beforeHtml"]
    assert ">WARN<" in result["beforeHtml"]
    assert "warn once" in result["beforeHtml"]
    assert "startup ok" not in result["afterHtml"]
    assert "warn once" not in result["afterHtml"]
    assert ">ERROR<" in result["afterHtml"]
    assert "boom first" in result["afterHtml"]


def test_scheduled_tasks_run_log_wrap_toggle_switches_console_wrap_class():
    result = run_scheduled_tasks_log_console_scenario("wrap_toggle")

    assert result["beforeWrap"] is True
    assert result["beforeNoWrap"] is False
    assert result["afterWrap"] is False
    assert result["afterNoWrap"] is True


def test_scheduled_tasks_run_log_reapplies_filters_after_new_chunk_arrives():
    result = run_scheduled_tasks_log_console_scenario("second_chunk_reapplies_filters")

    assert ">ERROR<" in result["beforeHtml"]
    assert "boom first" in result["beforeHtml"]
    assert "boom info second" not in result["beforeHtml"]
    assert ">ERROR<" in result["afterHtml"]
    assert "boom first" in result["afterHtml"]
    assert "boom second" in result["afterHtml"]
    assert "boom info second" not in result["afterHtml"]
    assert "/scheduled-runs/123/logs?offset=0" in result["logRequests"]
    assert any(request.endswith(f"offset={len('2026-03-24 09:00:00.100 [INFO] startup ok\n2026-03-24 09:00:00.200 [ERROR] boom first\n2026-03-24 09:00:00.300 [WARN] warn once')}") for request in result["logRequests"])


def test_scheduled_tasks_run_log_renders_second_precision_timestamps_and_column_hooks():
    result = run_scheduled_tasks_log_console_scenario("timestamp_normalization")

    assert "2026-03-24 09:00:00.100" not in result["consoleHtml"]
    assert "2026-03-24 09:00:00" in result["consoleHtml"]
    assert "2026-03-24 09:00:02" in result["consoleHtml"]
    assert "scheduled-run-log-timestamp" in result["consoleHtml"]
    assert "scheduled-run-log-message" in result["consoleHtml"]
    assert ">INFO<" in result["consoleHtml"]
    assert ">WARN<" in result["consoleHtml"]


def test_scheduled_tasks_run_log_copy_uses_raw_visible_lines():
    result = run_scheduled_tasks_log_console_scenario("copy_visible_logs_preserves_raw_text")

    assert result["copiedText"] == "2026-03-24 09:00:00.100 [ERROR] boom first"
    assert "startup ok" not in result["copiedText"]
    assert "warn once" not in result["copiedText"]


def test_scheduled_tasks_script_drops_stale_builtin_keys_when_task_type_switches():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

global.window = {};
global.document = {
  getElementById: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};
global.api = { get: async () => ({}), post: async () => ({}), put: async () => ({}) };
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

if (typeof window.prepareConfigEntriesForTaskTypeSwitch !== 'function') {
  throw new Error('prepareConfigEntriesForTaskTypeSwitch is not exposed');
}

const result = window.prepareConfigEntriesForTaskTypeSwitch(
  'cpa_refill',
  'cpa_cleanup',
  [
    {
      key: 'max_probe_count',
      keyDescription: '旧内置键',
      rawValue: '100',
      valueDescription: '旧说明',
      valueType: 'number',
      builtin: true,
      readonlyKey: true,
    },
    {
      key: 'max_cleanup_count',
      keyDescription: '旧内置键2',
      rawValue: '10',
      valueDescription: '旧说明2',
      valueType: 'number',
      builtin: true,
      readonlyKey: true,
    },
    {
      key: 'custom_keep',
      keyDescription: '自定义键',
      rawValue: 'custom-value',
      valueDescription: '保留我',
      valueType: 'string',
      builtin: false,
      readonlyKey: false,
    },
  ],
);

console.log(JSON.stringify(result.map((entry) => ({
  key: entry.key,
  builtin: entry.builtin,
  valueDescription: entry.valueDescription,
}))));
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    keys = json.loads(completed.stdout)
    assert {"key": "custom_keep", "builtin": False, "valueDescription": "保留我"} in keys
    assert all(item["key"] not in {"max_probe_count", "max_cleanup_count"} for item in keys)
    assert any(item["key"] == "target_valid_count" and item["builtin"] is True for item in keys)


def test_scheduled_tasks_run_log_loading_drains_chunks_even_when_run_is_finished():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  let text = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    get textContent() { return text; },
    set textContent(next) { text = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const elements = new Map([
  ['run-log-modal', makeElement()],
  ['run-log-status-bar', makeElement()],
  ['run-log-modal-body', makeElement()],
  ['run-log-console', makeElement()],
  ['run-log-stop-btn', makeElement()],
]);

global.window = {};
global.document = {
  getElementById: (id) => {
    if (id === 'scheduled-run-log-output') {
      if (!elements.has(id)) elements.set(id, makeElement());
      return elements.get(id);
    }
    return elements.get(id) ?? null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

let logCalls = 0;
global.api = {
  get: async (url) => {
    if (url === '/scheduled-runs/123') {
      return {
        id: 123,
        plan_id: 1,
        plan_name: 'plan',
        task_type: 'cpa_cleanup',
        trigger_source: 'manual',
        started_at: null,
        finished_at: null,
        error_message: null,
        summary: {},
        status: 'finished',
        last_log_at: null,
        is_running: false,
        stop_requested_at: null,
        can_stop: false,
      };
    }
    if (url.startsWith('/scheduled-runs/123/logs?offset=')) {
      logCalls += 1;
      if (url.endsWith('offset=0')) {
        return {
          chunk: 'a',
          next_offset: 1,
          has_more: true,
          is_running: false,
          status: 'finished',
          stop_requested_at: null,
          log_version: 1,
          last_log_at: null,
        };
      }
      if (url.endsWith('offset=1')) {
        return {
          chunk: 'b',
          next_offset: 2,
          has_more: false,
          is_running: false,
          status: 'finished',
          stop_requested_at: null,
          log_version: 1,
          last_log_at: null,
        };
      }
      throw new Error('unexpected offset url: ' + url);
    }
    throw new Error('unexpected url: ' + url);
  },
  post: async () => ({}),
  put: async () => ({}),
};
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

async function main() {
  await window.openScheduledRunLog(123);
  if (logCalls !== 2) throw new Error('expected 2 log calls, got ' + logCalls);
  const html = elements.get('run-log-console').innerHTML;
  if (!html.includes('>ab<')) {
    throw new Error('expected log output to include merged chunks, got: ' + JSON.stringify(html));
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_run_log_polling_is_single_flight():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const elements = new Map([
  ['run-log-modal', makeElement()],
  ['run-log-status-bar', makeElement()],
  ['run-log-modal-body', makeElement()],
  ['run-log-console', makeElement()],
  ['run-log-stop-btn', makeElement()],
]);

global.window = {};
global.document = {
  getElementById: (id) => elements.get(id) ?? null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

let intervalCb = null;
global.setInterval = () => {
  throw new Error('expected self-scheduling polling, not setInterval');
};
global.clearInterval = () => {};
global.setTimeout = (cb) => {
  intervalCb = cb;
  return 1;
};
global.clearTimeout = () => {
  intervalCb = null;
};

let deferredResolve = null;
const deferred = new Promise((resolve) => { deferredResolve = resolve; });

let logCalls = 0;
global.api = {
  get: async (url) => {
    if (url === '/scheduled-runs/123') {
      return {
        id: 123,
        plan_id: 1,
        plan_name: 'plan',
        task_type: 'cpa_cleanup',
        trigger_source: 'manual',
        started_at: null,
        finished_at: null,
        error_message: null,
        summary: {},
        status: 'running',
        last_log_at: null,
        is_running: true,
        stop_requested_at: null,
        can_stop: true,
      };
    }
    if (url.startsWith('/scheduled-runs/123/logs?offset=')) {
      logCalls += 1;
      if (logCalls === 1) {
        return {
          chunk: '',
          next_offset: 0,
          has_more: false,
          is_running: true,
          status: 'running',
          stop_requested_at: null,
          log_version: 1,
          last_log_at: null,
        };
      }
      if (logCalls === 2) return deferred;
      return {
        chunk: '',
        next_offset: 0,
        has_more: false,
        is_running: true,
        status: 'running',
        stop_requested_at: null,
        log_version: 1,
        last_log_at: null,
      };
    }
    throw new Error('unexpected url: ' + url);
  },
  post: async () => ({}),
  put: async () => ({}),
};
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  await window.openScheduledRunLog(123);
  if (typeof intervalCb !== 'function') throw new Error('expected polling timer callback to be registered');

  intervalCb();
  intervalCb();
  if (logCalls !== 2) {
    throw new Error('expected single-flight polling (2 total log calls incl. initial), got ' + logCalls);
  }

  deferredResolve({
    chunk: '',
    next_offset: 0,
    has_more: false,
    is_running: true,
    status: 'running',
    stop_requested_at: null,
    log_version: 1,
    last_log_at: null,
  });
  await flush();

  if (typeof intervalCb !== 'function') throw new Error('expected polling timer callback to remain registered');
  intervalCb();
  if (logCalls !== 3) throw new Error('expected next polling fetch after completion, got logCalls=' + logCalls);
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_stop_run_failure_does_not_reject_promise():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

global.window = {};
global.document = {
  getElementById: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

global.api = {
  get: async () => ({}),
  post: async () => { throw new Error('stop failed'); },
  put: async () => ({}),
};
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

async function main() {
  await window.stopScheduledRun(99);
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_scheduled_tasks_closing_log_modal_cancels_stale_async_work_and_polling():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function makeElement() {
  let html = '';
  const classes = new Set();
  return {
    dataset: {},
    style: {},
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
    scrollIntoView: () => {},
    get innerHTML() { return html; },
    set innerHTML(next) { html = String(next ?? ''); },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
  };
}

const runLogModal = makeElement();
const runLogStatusBar = makeElement();
const runLogModalBody = makeElement();
const runLogStopBtn = makeElement();

const elements = new Map([
  ['run-log-modal', runLogModal],
  ['run-log-status-bar', runLogStatusBar],
  ['run-log-modal-body', runLogModalBody],
  ['run-log-console', makeElement()],
  ['run-log-stop-btn', runLogStopBtn],
]);

global.window = {};
global.document = {
  getElementById: (id) => elements.get(id) ?? null,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => {
    let value = '';
    return {
      set textContent(next) { value = String(next ?? ''); },
      get textContent() { return value; },
      get innerHTML() { return value; },
      set innerHTML(next) { value = String(next ?? ''); },
    };
  },
};

let intervalCreated = 0;
global.setInterval = () => {
  throw new Error('expected self-scheduling polling, not setInterval');
};
global.clearInterval = () => {};
global.setTimeout = () => {
  intervalCreated += 1;
  return 1;
};
global.clearTimeout = () => {};

let resolveDetail = null;
const detailPromise = new Promise((resolve) => { resolveDetail = resolve; });

let resolveLogs = null;
const logsPromise = new Promise((resolve) => { resolveLogs = resolve; });

global.api = {
  get: async (url) => {
    if (url === '/scheduled-runs/123') return detailPromise;
    if (url.startsWith('/scheduled-runs/123/logs?offset=')) return logsPromise;
    throw new Error('unexpected url: ' + url);
  },
  post: async () => ({}),
  put: async () => ({}),
};
global.toast = { error: () => {}, warning: () => {}, success: () => {} };
global.format = { date: (value) => String(value ?? '-') };
global.theme = { toggle: () => {} };

vm.runInThisContext(fs.readFileSync('static/js/scheduled_tasks.js', 'utf8'), {
  filename: 'static/js/scheduled_tasks.js',
});

async function main() {
  const openPromise = window.openScheduledRunLog(123);

  const closeButton = {
    dataset: { action: 'back-to-runs' },
    disabled: false,
    setAttribute: () => {},
    removeAttribute: () => {},
  };
  await window.handleRunLogAction(closeButton);

  resolveDetail({
    id: 123,
    plan_id: 1,
    plan_name: 'plan',
    task_type: 'cpa_cleanup',
    trigger_source: 'manual',
    started_at: null,
    finished_at: null,
    error_message: null,
    summary: {},
    status: 'running',
    last_log_at: null,
    is_running: true,
    stop_requested_at: null,
    can_stop: true,
  });
  resolveLogs({
    chunk: 'stale',
    next_offset: 4,
    has_more: false,
    is_running: true,
    status: 'running',
    stop_requested_at: null,
    log_version: 1,
    last_log_at: null,
  });

  await openPromise;

  if (runLogModal.classList.contains('active')) throw new Error('modal should remain closed');
  if (intervalCreated !== 0) {
    throw new Error('polling timer should not start after close; got intervalCreated=' + intervalCreated);
  }
  if (runLogStatusBar.innerHTML !== '<span>未选择运行记录</span>') {
    throw new Error('expected status bar to stay reset, got: ' + JSON.stringify(runLogStatusBar.innerHTML));
  }
  const runLogConsole = elements.get('run-log-console');
  if (!String(runLogConsole.innerHTML).includes('暂无记录')) {
    throw new Error('expected console to stay reset, got: ' + JSON.stringify(runLogConsole.innerHTML));
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def run_scheduled_tasks_shared_console_scenario(name: str) -> dict:
    scheduled_tasks_source = Path("static/js/scheduled_tasks.js").read_text(encoding="utf-8")
    store_source = Path("static/js/realtime_log_store.js").read_text(encoding="utf-8")
    client_source = Path("static/js/realtime_log_client.js").read_text(encoding="utf-8")
    console_source = Path("static/js/realtime_log_console.js").read_text(encoding="utf-8")

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scheduledTasksSource = {json.dumps(scheduled_tasks_source)};
const storeSource = {json.dumps(store_source)};
const clientSource = {json.dumps(client_source)};
const consoleSource = {json.dumps(console_source)};

function createClassList() {{
  const classes = new Set();
  return {{
    add(...tokens) {{ tokens.filter(Boolean).forEach((token) => classes.add(token)); }},
    remove(...tokens) {{ tokens.filter(Boolean).forEach((token) => classes.delete(token)); }},
    contains(token) {{ return classes.has(token); }},
    toggle(token, force) {{
      if (force === true) {{ classes.add(token); return true; }}
      if (force === false) {{ classes.delete(token); return false; }}
      if (classes.has(token)) {{
        classes.delete(token);
        return false;
      }}
      classes.add(token);
      return true;
    }},
  }};
}}

function createMockElement(id = '') {{
  let html = '';
  let text = '';
  const classes = createClassList();
  return {{
    id,
    dataset: {{}},
    style: {{}},
    value: '',
    checked: true,
    disabled: false,
    scrollTop: 0,
    scrollHeight: 480,
    clientHeight: 240,
    _listeners: {{}},
    classList: classes,
    addEventListener(type, handler) {{ this._listeners[type] = handler; }},
    removeEventListener() {{}},
    setAttribute() {{}},
    removeAttribute() {{}},
    appendChild() {{}},
    scrollIntoView() {{}},
    reset() {{}},
    click() {{
      if (this._listeners.click) {{
        return this._listeners.click({{ currentTarget: this, target: this, preventDefault() {{}} }});
      }}
      return undefined;
    }},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
    get innerHTML() {{ return html; }},
    set innerHTML(next) {{
      html = String(next ?? '');
      text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    }},
    get textContent() {{ return text; }},
    set textContent(next) {{
      text = String(next ?? '');
      html = text;
    }},
  }};
}}

const elements = new Map();
function getElement(id) {{
  if (!elements.has(id)) {{
    elements.set(id, createMockElement(id));
  }}
  return elements.get(id);
}}

[
  'scheduled-plans-table-body',
  'scheduled-runs-card',
  'scheduled-runs-table-body',
  'refresh-plans-btn',
  'create-plan-btn',
  'scheduled-run-filter-task-type',
  'scheduled-run-filter-status',
  'scheduled-run-filter-started-from',
  'scheduled-run-filter-started-to',
  'scheduled-run-filter-apply-btn',
  'scheduled-run-filter-reset-btn',
  'scheduled-run-pagination-summary',
  'scheduled-run-prev-page',
  'scheduled-run-next-page',
  'scheduled-run-page-jump-input',
  'scheduled-run-page-jump-btn',
  'plan-form-modal',
  'plan-form-title',
  'plan-form',
  'plan-id',
  'plan-form-submit-btn',
  'plan-name',
  'plan-task-type',
  'plan-cpa-service-select',
  'plan-cpa-service-id',
  'plan-trigger-type',
  'plan-cron-group',
  'plan-cron-expression',
  'plan-interval-group',
  'plan-interval-value',
  'plan-interval-unit',
  'plan-config-mode-table',
  'plan-config-mode-json',
  'plan-config-add-entry-btn',
  'plan-config-editor-panel',
  'plan-config-entries-body',
  'plan-config-json-panel',
  'plan-config-json',
  'plan-enabled',
  'plan-modal',
  'plan-modal-body',
  'run-detail-modal',
  'run-detail-modal-body',
  'run-log-modal',
  'run-log-status-bar',
  'run-log-refresh-btn',
  'run-log-auto-scroll',
  'run-log-stop-actions',
  'run-log-stop-btn',
  'run-log-modal-body',
  'run-log-console',
  'run-log-search-input',
  'run-log-level-filter',
  'run-log-copy-btn',
  'run-log-clear-btn',
  'run-log-wrap-input',
].forEach((id) => getElement(id));

getElement('run-log-wrap-input').checked = true;
getElement('run-log-auto-scroll').checked = true;

const domListeners = {{}};
const document = {{
  body: createMockElement('body'),
  activeElement: null,
  getElementById(id) {{ return getElement(id); }},
  querySelectorAll(selector) {{
    if (selector === '[data-close-modal]') {{
      return [];
    }}
    return [];
  }},
  querySelector() {{ return null; }},
  addEventListener(type, handler) {{ domListeners[type] = handler; }},
  createElement() {{
    return createMockElement('created');
  }},
}};

let nextTimerId = 1;
const timerCallbacks = new Map();
const clearedTimers = [];
let latestWs = null;
const createdWsUrls = [];
let fallbackTimerId = null;

class MockWebSocket {{
  constructor(url) {{
    this.url = String(url);
    this.readyState = 1;
    this.sent = [];
    this.closed = false;
    this.closeCount = 0;
    createdWsUrls.push(this.url);
    latestWs = this;
  }}

  send(payload) {{
    this.sent.push(payload);
  }}

  close() {{
    this.closed = true;
    this.closeCount += 1;
    this.readyState = 3;
    if (typeof this.onclose === 'function') {{
      this.onclose({{ code: 1000 }});
    }}
  }}
}}
MockWebSocket.OPEN = 1;

const apiRequests = [];
const context = {{
  console,
  URLSearchParams,
  setTimeout(callback) {{
    const id = nextTimerId++;
    timerCallbacks.set(id, callback);
    fallbackTimerId = id;
    return id;
  }},
  clearTimeout(id) {{
    clearedTimers.push(id);
    timerCallbacks.delete(id);
  }},
  setInterval() {{
    throw new Error('expected no setInterval usage');
  }},
  clearInterval() {{}},
  document,
  window: {{
    location: {{
      protocol: 'http:',
      host: 'localhost',
    }},
    navigator: {{
      clipboard: {{
        writeText: async () => {{}},
      }},
    }},
    WebSocket: MockWebSocket,
  }},
  navigator: {{
    clipboard: {{
      writeText: async () => {{}},
    }},
  }},
  WebSocket: MockWebSocket,
  theme: {{ toggle() {{}} }},
  format: {{ date(value) {{ return String(value ?? '-'); }} }},
  toast: {{
    warning() {{}},
    error() {{}},
    success() {{}},
  }},
  api: {{
    async get(path) {{
      apiRequests.push(path);
      if (path === '/scheduled-plans') return {{ items: [] }};
      if (path === '/cpa-services') return [];
      if (path.startsWith('/scheduled-runs?')) return {{ items: [], total: 0, page: 1, page_size: 20 }};
      if (path === '/scheduled-runs/123') {{
        return {{
          id: 123,
          plan_id: 9,
          plan_name: 'nightly cleanup',
          task_type: 'cpa_cleanup',
          trigger_source: 'manual',
          started_at: '2026-03-27T09:00:00',
          finished_at: null,
          error_message: null,
          summary: {{}},
          status: 'running',
          last_log_at: '2026-03-27T09:00:00',
          is_running: true,
          stop_requested_at: null,
          can_stop: true,
        }};
      }}
      if (path === '/scheduled-runs/123/logs?offset=0') {{
        return {{
          run_id: 123,
          chunk: [
            '2026-03-27 09:00:00.000 [INFO] warmup done',
            '2026-03-27 09:00:00.100 [INFO] history only',
          ].join('\n') + '\n',
          next_offset: 87,
          has_more: false,
          is_running: true,
          status: 'running',
          stop_requested_at: null,
          log_version: 2,
          last_log_at: '2026-03-27T09:00:00',
        }};
      }}
      if (path === '/realtime-streams/run/123/snapshot') {{
        return {{
          seq: 2,
          stream: 'run:123',
          kind: 'snapshot',
          payload: {{
            run: {{
              id: 123,
              plan_id: 9,
              plan_name: 'nightly cleanup',
              task_type: 'cpa_cleanup',
              status: 'running',
              is_running: true,
              can_stop: true,
              log_version: 2,
              last_log_at: '2026-03-27T09:00:00',
            }},
            run_progress: null,
            logs_tail: [
              {{
                seq: 1,
                stream: 'run:123',
                timestamp: '2026-03-27T09:00:00+08:00',
                display_time: '09:00:00',
                level: 'INFO',
                message: 'warmup done',
                raw: '2026-03-27 09:00:00.000 [INFO] warmup done',
                source: 'scheduler',
              }},
              {{
                seq: 2,
                stream: 'run:123',
                timestamp: '2026-03-27T09:00:00+08:00',
                display_time: '09:00:00',
                level: 'INFO',
                message: 'snapshot steady',
                raw: '2026-03-27 09:00:00.050 [INFO] snapshot steady',
                source: 'scheduler',
              }},
            ],
          }},
        }};
      }}
      if (path.startsWith('/realtime-streams/run/123/events?after_seq=')) {{
        return {{
          stream: 'run:123',
          events: [],
        }};
      }}
      throw new Error('unexpected api path: ' + path);
    }},
    async post() {{ return {{}}; }},
    async put() {{ return {{}}; }},
  }},
}};
context.global = context;
context.globalThis = context;
context.window.window = context.window;
context.window.document = document;
context.window.navigator = context.navigator;

vm.createContext(context);
vm.runInContext(storeSource, context, {{ filename: 'realtime_log_store.js' }});
vm.runInContext(clientSource, context, {{ filename: 'realtime_log_client.js' }});
vm.runInContext(consoleSource, context, {{ filename: 'realtime_log_console.js' }});
vm.runInContext(scheduledTasksSource, context, {{ filename: 'scheduled_tasks.js' }});

async function flush() {{
  await new Promise((resolve) => setImmediate(resolve));
}}

function trigger(type, element, event = {{}}) {{
  const handler = element && element._listeners ? element._listeners[type] : null;
  if (!handler) return;
  return handler(event);
}}

async function runScenario() {{
  if (typeof domListeners.DOMContentLoaded !== 'function') {{
    throw new Error('DOMContentLoaded listener missing');
  }}

  domListeners.DOMContentLoaded();
  await flush();
  await flush();

  await context.window.openScheduledRunLog(123);
  await flush();

  if (latestWs && typeof latestWs.onopen === 'function') {{
    latestWs.onopen();
  }}

  if (latestWs && typeof latestWs.onmessage === 'function') {{
    latestWs.onmessage({{
      data: JSON.stringify({{
        seq: 3,
        stream: 'run:123',
        kind: 'log_appended',
        payload: {{
          entry: {{
            seq: 3,
            stream: 'run:123',
            timestamp: '2026-03-27T09:00:01+08:00',
            display_time: '09:00:01',
            level: 'ERROR',
            message: 'fatal issue',
            raw: '2026-03-27 09:00:01.000 [ERROR] fatal issue',
            source: 'scheduler',
          }},
        }},
      }}),
    }});
  }}
  await flush();

  if (scenarioName === 'shared_console_controls') {{
    const logConsole = getElement('run-log-console');
    const searchInput = getElement('run-log-search-input');
    const levelFilter = getElement('run-log-level-filter');
    const wrapInput = getElement('run-log-wrap-input');

    searchInput.value = 'fatal';
    let enterPrevented = false;
    trigger('keydown', searchInput, {{
      key: 'Enter',
      preventDefault() {{
        enterPrevented = true;
      }},
    }});
    await flush();
    const htmlAfterSearch = logConsole.innerHTML;

    levelFilter.value = 'ERROR';
    trigger('change', levelFilter, {{ target: levelFilter }});
    await flush();
    const htmlAfterLevelFilter = logConsole.innerHTML;

    wrapInput.checked = false;
    trigger('change', wrapInput, {{ target: wrapInput }});
    await flush();

    return {{
      search_prevented_enter: enterPrevented,
      search_filters_shared_console: htmlAfterSearch.includes('fatal issue')
        && !htmlAfterSearch.includes('warmup done')
        && htmlAfterSearch.includes('realtime-log-level-badge'),
      level_filter_keeps_shared_markup: htmlAfterLevelFilter.includes('fatal issue')
        && !htmlAfterLevelFilter.includes('scheduled-run-log-level-badge'),
      wrap_toggle_keeps_shared_console: logConsole.classList.contains('realtime-log-console--nowrap')
        && !logConsole.innerHTML.includes('scheduled-run-log-line'),
    }};
  }}

  if (scenarioName !== 'run_ws_live_append') {{
    throw new Error('unknown scenario: ' + scenarioName);
  }}

  if (latestWs && typeof latestWs.onerror === 'function') {{
    latestWs.onerror(new Error('socket failed'));
  }}
  await flush();

  const consoleHtmlBeforeClose = getElement('run-log-console').innerHTML;
  const historyTailCount = (consoleHtmlBeforeClose.match(/warmup done/g) || []).length;
  const sharedClassBeforeClose = getElement('run-log-console').classList.contains('realtime-log-console-shell');
  const errorClassVisible = consoleHtmlBeforeClose.includes('realtime-log-level-error') ? 'realtime-log-level-error' : '';
  const fallbackTimerBeforeClose = fallbackTimerId;

  await context.window.handleRunLogAction({{
    dataset: {{ action: 'back-to-runs' }},
    disabled: false,
    setAttribute() {{}},
    removeAttribute() {{}},
  }});
  await flush();

  return {{
    ws_url: createdWsUrls[0] || '',
    console_has_shared_class: sharedClassBeforeClose,
    last_line_level_class: errorClassVisible,
    history_tail_deduped: historyTailCount === 1,
    teardown_closed_ws: !!(latestWs && latestWs.closed),
    teardown_stopped_fallback: fallbackTimerBeforeClose !== null && clearedTimers.includes(fallbackTimerBeforeClose),
    api_requests: apiRequests,
  }};
}}

runScenario()
  .then((result) => {{
    process.stdout.write(JSON.stringify(result));
  }})
  .catch((error) => {{
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }});
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as script_file:
        script_file.write(node_script)
        script_path = Path(script_file.name)

    try:
        completed = subprocess.run(
            ["node", str(script_path)],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout or "{}")


def test_scheduled_tasks_run_log_modal_uses_shared_console_and_run_ws_contract():
    result = run_scheduled_tasks_shared_console_scenario("run_ws_live_append")

    assert result["ws_url"] == "ws://localhost/api/ws/run/123?after_seq=0"
    assert "/realtime-streams/run/123/snapshot" in result["api_requests"]
    assert not any(request.startswith("/api/realtime-streams/") for request in result["api_requests"])
    assert result["console_has_shared_class"] is True
    assert result["last_line_level_class"] == "realtime-log-level-error"
    assert result["history_tail_deduped"] is True
    assert result["teardown_closed_ws"] is True
    assert result["teardown_stopped_fallback"] is True


def test_scheduled_tasks_shared_console_controls_stay_on_shared_runtime():
    result = run_scheduled_tasks_shared_console_scenario("shared_console_controls")

    assert result["search_prevented_enter"] is True
    assert result["search_filters_shared_console"] is True
    assert result["level_filter_keeps_shared_markup"] is True
    assert result["wrap_toggle_keeps_shared_console"] is True
