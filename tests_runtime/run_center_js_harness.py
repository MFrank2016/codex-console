from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_CENTER_JS = ROOT / "static" / "js" / "run_center.js"
RUN_CENTER_SHARED_JS = ROOT / "static" / "js" / "run_center_shared.js"
REALTIME_LOG_STORE_JS = ROOT / "static" / "js" / "realtime_log_store.js"
REALTIME_LOG_CLIENT_JS = ROOT / "static" / "js" / "realtime_log_client.js"
REALTIME_LOG_CONSOLE_JS = ROOT / "static" / "js" / "realtime_log_console.js"


def run_run_center_js_scenario(name: str) -> dict:
    run_center_source = RUN_CENTER_JS.read_text(encoding="utf-8") if RUN_CENTER_JS.exists() else ""
    shared_source = RUN_CENTER_SHARED_JS.read_text(encoding="utf-8") if RUN_CENTER_SHARED_JS.exists() else ""
    store_source = REALTIME_LOG_STORE_JS.read_text(encoding="utf-8") if REALTIME_LOG_STORE_JS.exists() else ""
    client_source = REALTIME_LOG_CLIENT_JS.read_text(encoding="utf-8") if REALTIME_LOG_CLIENT_JS.exists() else ""
    console_source = REALTIME_LOG_CONSOLE_JS.read_text(encoding="utf-8") if REALTIME_LOG_CONSOLE_JS.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const runCenterSource = {json.dumps(run_center_source)};
const sharedSource = {json.dumps(shared_source)};
const storeSource = {json.dumps(store_source)};
const clientSource = {json.dumps(client_source)};
const consoleSource = {json.dumps(console_source)};

function createClassList() {{
  const classes = new Set();
  return {{
    add(...tokens) {{ tokens.filter(Boolean).forEach(token => classes.add(token)); }},
    remove(...tokens) {{ tokens.filter(Boolean).forEach(token => classes.delete(token)); }},
    contains(token) {{ return classes.has(token); }},
    toggle(token, force) {{
      if (force === true) {{ classes.add(token); return true; }}
      if (force === false) {{ classes.delete(token); return false; }}
      if (classes.has(token)) {{ classes.delete(token); return false; }}
      classes.add(token);
      return true;
    }},
    toString() {{ return [...classes].join(' '); }},
  }};
}}

function createMockElement(id = '') {{
  const element = {{
    id,
    style: {{}},
    dataset: {{}},
    disabled: false,
    checked: false,
    value: '',
    href: '',
    className: '',
    classList: createClassList(),
    _textContent: '',
    _innerHTML: '',
    _listeners: {{}},
    scrollTop: 0,
    scrollHeight: 1200,
    clientHeight: 240,
    addEventListener(type, handler) {{
      this._listeners[type] = handler;
    }},
    dispatchEvent(type, event = {{}}) {{
      const handler = this._listeners[type];
      if (!handler) return undefined;
      return handler({{ currentTarget: this, target: this, preventDefault() {{}}, ...event }});
    }},
    click() {{
      return this.dispatchEvent('click');
    }},
    setAttribute(name, value) {{
      this[name] = String(value);
    }},
    removeAttribute(name) {{
      delete this[name];
    }},
    appendChild() {{ return null; }},
    removeChild() {{ return null; }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
    scrollIntoView() {{}},
    focus() {{}},
  }};

  Object.defineProperty(element, 'textContent', {{
    get() {{ return this._textContent; }},
    set(value) {{
      this._textContent = String(value ?? '');
      this._innerHTML = this._textContent;
    }},
  }});

  Object.defineProperty(element, 'innerHTML', {{
    get() {{ return this._innerHTML; }},
    set(value) {{
      this._innerHTML = String(value ?? '');
      this._textContent = this._innerHTML;
    }},
  }});

  return element;
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
  createElement() {{ return createMockElement(); }},
  body: createMockElement('body'),
  activeElement: null,
}};

document.body.appendChild = () => {{}};
document.body.removeChild = () => {{}};

const logs = {{
  apiGetPaths: [],
  apiPostPaths: [],
  assignedHref: null,
}};

const locationState = {{
  protocol: 'http:',
  host: 'localhost',
  pathname: '/run-center',
  href: 'http://localhost/run-center',
  search: '',
  assign(url) {{
    logs.assignedHref = String(url);
    this.href = String(url);
  }},
}};

function applyScenarioSearch() {{
  if (['scheduled_scope_bootstrap', 'safe_row_rendering', 'filter_and_pagination', 'log_modal_and_stop', 'runs_load_failure'].includes(scenarioName)) {{
    locationState.search = '?scope=scheduled&plan_id=52&source=scheduled-tasks';
    return;
  }}
  if (scenarioName === 'task_scope_retry_handoff') {{
    locationState.search = '?scope=task&task_uuid=task-single-01&source=registration-workbench';
    return;
  }}
  throw new Error('unknown scenario: ' + scenarioName);
}}

applyScenarioSearch();

const context = {{
  console,
  URLSearchParams,
  document,
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  window: {{ location: locationState }},
  location: locationState,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  theme: {{ toggle() {{}}, applyTheme() {{}} }},
  toast: {{ success() {{}}, error() {{}}, warning() {{}}, info() {{}} }},
  format: {{ date(value) {{ return String(value ?? '-'); }} }},
  api: {{
    async get(path) {{
      logs.apiGetPaths.push(String(path));
      if (path.startsWith('/scheduled-runs?')) {{
        if (scenarioName === 'runs_load_failure') {{
          throw new Error('upstream unavailable');
        }}
        const url = new URL(`http://localhost${{path}}`);
        const page = Number.parseInt(url.searchParams.get('page') || '1', 10);
        if (scenarioName === 'safe_row_rendering') {{
          return {{
            items: [{{
              id: 401,
              plan_id: 52,
              plan_name: '<script>alert(1)</script>',
              task_type: 'custom_task',
              trigger_source: 'scheduled',
              status: 'failed',
              started_at: '2026-03-27T09:00:00Z',
              finished_at: '2026-03-27T09:02:00Z',
              can_stop: false,
              summary: {{ note: '<b>boom</b>' }},
            }}],
            total: 1,
            page: 1,
            page_size: 20,
          }};
        }}
        return {{
          items: [{{
            id: 201,
            plan_id: 52,
            plan_name: 'nightly refill',
            task_type: url.searchParams.get('task_type') || 'cpa_refill',
            trigger_source: 'scheduled',
            status: url.searchParams.get('status') || (scenarioName === 'log_modal_and_stop' ? 'running' : 'success'),
            started_at: '2026-03-27T10:00:00Z',
            finished_at: page >= 2 ? '2026-03-27T10:05:00Z' : '',
            can_stop: scenarioName === 'log_modal_and_stop',
            is_running: scenarioName === 'log_modal_and_stop',
            summary: {{ uploaded_success: 3 }},
          }}],
          total: 52,
          page,
          page_size: 20,
        }};
      }}
      if (path.startsWith('/scheduled-runs/201/logs')) {{
        return {{
          chunk: '2026-03-27 10:00:00 [INFO] line one\\n',
          next_offset: 1,
          has_more: false,
          is_running: scenarioName === 'log_modal_and_stop',
          status: scenarioName === 'log_modal_and_stop' ? 'running' : 'success',
          stop_requested_at: null,
          log_version: 1,
          last_log_at: '2026-03-27T10:00:05Z',
        }};
      }}
      if (path.startsWith('/scheduled-runs/')) {{
        return {{
          id: 201,
          plan_id: 52,
          plan_name: 'nightly refill',
          task_type: 'cpa_refill',
          trigger_source: 'scheduled',
          status: scenarioName === 'log_modal_and_stop' ? 'running' : 'success',
          is_running: scenarioName === 'log_modal_and_stop',
          can_stop: scenarioName === 'log_modal_and_stop',
          started_at: '2026-03-27T10:00:00Z',
          finished_at: '',
          last_log_at: '2026-03-27T10:00:05Z',
          summary: {{ uploaded_success: 3 }},
        }};
      }}
      if (path.startsWith('/realtime-streams/run/')) {{
        return {{ kind: 'snapshot', payload: {{ logs_tail: [] }} }};
      }}
      throw new Error('unexpected GET path: ' + path);
    }},
    async post(path) {{
      logs.apiPostPaths.push(String(path));
      return {{ success: true }};
    }},
  }},
}};
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(storeSource, context);
vm.runInContext(clientSource, context);
vm.runInContext(consoleSource, context);
vm.runInContext(sharedSource, context);
vm.runInContext(runCenterSource, context);

async function flush() {{
  await new Promise(resolve => setTimeout(resolve, 0));
  await new Promise(resolve => setTimeout(resolve, 0));
}}

async function main() {{
  if (typeof domListeners.DOMContentLoaded === 'function') {{
    domListeners.DOMContentLoaded();
  }}
  await flush();

  const page = getElement('run-center-page');
  const scopeInput = getElement('run-center-control-scope');
  const contextLink = getElement('run-center-context-link');
  const retryBtn = getElement('run-center-retry-btn');
  const paginationSummary = getElement('scheduled-run-pagination-summary');
  const tableBody = getElement('scheduled-runs-table-body');
  const prevPageBtn = getElement('scheduled-run-prev-page');
  const nextPageBtn = getElement('scheduled-run-next-page');
  const jumpInput = getElement('scheduled-run-page-jump-input');
  const logStatusBar = getElement('run-log-status-bar');
  const logConsole = getElement('run-log-console');
  const stopBtn = getElement('run-log-stop-btn');
  const pageApi = context.window.runCenterPage || context.runCenterPage || null;

  if (scenarioName === 'task_scope_retry_handoff') {{
    retryBtn.click();
    await flush();
  }}

  if (scenarioName === 'filter_and_pagination') {{
    getElement('scheduled-run-filter-task-type').value = 'cpa_refill';
    getElement('scheduled-run-filter-status').value = 'running';
    getElement('scheduled-run-filter-started-from').value = '2026-03-27T08:00';
    getElement('scheduled-run-filter-started-to').value = '2026-03-27T12:00';
    if (pageApi && typeof pageApi.applyFilters === 'function') {{
      await pageApi.applyFilters();
    }}
    await flush();
    if (pageApi && typeof pageApi.jumpToPage === 'function') {{
      await pageApi.jumpToPage('2');
    }}
    await flush();
  }}

  if (scenarioName === 'log_modal_and_stop') {{
    if (pageApi && typeof pageApi.openRunLog === 'function') {{
      await pageApi.openRunLog(201);
      await flush();
    }}
    if (pageApi && typeof pageApi.stopRun === 'function') {{
      await pageApi.stopRun(201);
      await flush();
    }}
  }}

  process.stdout.write(JSON.stringify({{
    page_ready: String(page.dataset.pageReady || ''),
    control_scope: String(scopeInput.value || scopeInput.dataset.scope || scopeInput.textContent || ''),
    context_href: String(contextLink.href || ''),
    assigned_href: logs.assignedHref,
    api_get_paths: logs.apiGetPaths,
    api_post_paths: logs.apiPostPaths,
    pagination_summary: String(paginationSummary.textContent || ''),
    table_html: String(tableBody.innerHTML || ''),
    prev_disabled: Boolean(prevPageBtn.disabled),
    next_disabled: Boolean(nextPageBtn.disabled),
    jump_value: String(jumpInput.value || ''),
    log_status_html: String(logStatusBar.innerHTML || ''),
    log_console_html: String(logConsole.innerHTML || logConsole.textContent || ''),
    stop_button_hidden: String(stopBtn.style.display || '') === 'none',
  }}));
}}

main().catch((error) => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""

    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Node harness failed for scenario {name!r}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}
