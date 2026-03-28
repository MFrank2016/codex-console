from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static" / "js" / "app.js"
REALTIME_LOG_STORE_JS = ROOT / "static" / "js" / "realtime_log_store.js"
REALTIME_LOG_CLIENT_JS = ROOT / "static" / "js" / "realtime_log_client.js"
REALTIME_LOG_CONSOLE_JS = ROOT / "static" / "js" / "realtime_log_console.js"
REGISTRATION_STREAM_JS = ROOT / "static" / "js" / "registration_stream.js"


def run_app_js_scenario(name: str) -> dict:
    app_source = APP_JS.read_text(encoding="utf-8")
    realtime_log_store_source = REALTIME_LOG_STORE_JS.read_text(encoding="utf-8")
    realtime_log_client_source = REALTIME_LOG_CLIENT_JS.read_text(encoding="utf-8")
    realtime_log_console_source = REALTIME_LOG_CONSOLE_JS.read_text(encoding="utf-8")
    registration_stream_source = REGISTRATION_STREAM_JS.read_text(encoding="utf-8")
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const appSource = {json.dumps(app_source)};
const realtimeLogStoreSource = {json.dumps(realtime_log_store_source)};
const realtimeLogClientSource = {json.dumps(realtime_log_client_source)};
const realtimeLogConsoleSource = {json.dumps(realtime_log_console_source)};
const registrationStreamSource = {json.dumps(registration_stream_source)};

const harnessConsole = {{
  log() {{}},
  info() {{}},
  warn() {{}},
  error(...args) {{
    console.error(...args);
  }},
}};

function createClassList() {{
  const classes = new Set();
  return {{
    add(...tokens) {{
      tokens.filter(Boolean).forEach(token => classes.add(token));
    }},
    remove(...tokens) {{
      tokens.filter(Boolean).forEach(token => classes.delete(token));
    }},
    contains(token) {{
      return classes.has(token);
    }},
    toggle(token, force) {{
      if (force === true) {{
        classes.add(token);
        return true;
      }}
      if (force === false) {{
        classes.delete(token);
        return false;
      }}
      if (classes.has(token)) {{
        classes.delete(token);
        return false;
      }}
      classes.add(token);
      return true;
    }},
    toString() {{
      return [...classes].join(' ');
    }},
  }};
}}

function createMockElement(id = '') {{
  function matchesClassSelector(className, selector) {{
    return String(className || '')
      .split(/\s+/)
      .filter(Boolean)
      .includes(selector.replace(/^\./, ''));
  }}

  function parseInnerHtmlByClass(html, selector) {{
    const targetClass = selector.replace(/^\./, '');
    const pattern = /<div class="([^"]*)">([\s\S]*?)<\/div>/g;
    const matches = [];
    let match;
    while ((match = pattern.exec(String(html || ''))) !== null) {{
      if (!matchesClassSelector(match[1], selector)) {{
        continue;
      }}
      const child = createMockElement();
      child.className = match[1];
      child.innerHTML = match[2];
      matches.push(child);
    }}
    return matches;
  }}

  const element = {{
    id,
    tagName: 'DIV',
    style: {{}},
    dataset: {{}},
    open: false,
    disabled: false,
    checked: false,
    value: '',
    className: '',
    classList: createClassList(),
    _textContent: '',
    _innerHTML: '',
    _children: [],
    _listeners: {{}},
    scrollTop: 0,
    scrollHeight: 1200,
    clientHeight: 240,
    addEventListener(type, handler) {{
      this._listeners[type] = handler;
    }},
    dispatchEvent(type, event = {{}}) {{
      if (this._listeners[type]) {{
        return this._listeners[type](event);
      }}
      return undefined;
    }},
    appendChild(child) {{
      this._children.push(child);
      return child;
    }},
    removeChild(child) {{
      this._children = this._children.filter(item => item !== child);
      return child;
    }},
    querySelectorAll(selector) {{
      if (selector === '.log-line') {{
        const childMatches = this._children.filter(child => matchesClassSelector(child.className, selector));
        if (childMatches.length > 0) {{
          return childMatches;
        }}
        return parseInnerHtmlByClass(this._innerHTML, selector);
      }}
      if (selector === '.realtime-log-line') {{
        return parseInnerHtmlByClass(this._innerHTML, selector);
      }}
      return [];
    }},
    querySelector() {{
      return null;
    }},
    showModal() {{
      this.open = true;
    }},
    close() {{
      this.open = false;
    }},
    remove() {{}},
    reset() {{
      this.value = '';
      this.checked = false;
    }},
    focus() {{}},
    select() {{}},
  }};

  Object.defineProperty(element, 'textContent', {{
    get() {{
      return this._textContent;
    }},
    set(value) {{
      this._textContent = String(value ?? '');
      this._innerHTML = this._textContent;
    }},
  }});

  Object.defineProperty(element, 'innerHTML', {{
    get() {{
      return this._innerHTML;
    }},
    set(value) {{
      this._innerHTML = String(value ?? '');
      this._textContent = this._innerHTML;
      this._children = [];
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
  getElementById(id) {{
    return getElement(id);
  }},
  querySelectorAll() {{
    return [];
  }},
  querySelector() {{
    return null;
  }},
  addEventListener(type, handler) {{
    domListeners[type] = handler;
  }},
  createElement() {{
    return createMockElement();
  }},
  body: createMockElement('body'),
}};

document.body.appendChild = () => {{}};
document.body.removeChild = () => {{}};

const sessionStore = new Map();
const logs = {{
  lastPostPath: null,
  lastPostPayload: null,
  apiGetPaths: [],
}};
const wsInstances = [];
const intervalHandles = [];
const timeoutHandles = [];
const nativeSetTimeout = setTimeout;
const nativeClearTimeout = clearTimeout;
const NativeDate = Date;
let currentNowMs = NativeDate.parse('2026-03-27T09:01:01Z');

class MockDate extends NativeDate {{
  constructor(...args) {{
    if (args.length === 0) {{
      super(currentNowMs);
      return;
    }}
    super(...args);
  }}

  static now() {{
    return currentNowMs;
  }}

  static parse(value) {{
    return NativeDate.parse(value);
  }}

  static UTC(...args) {{
    return NativeDate.UTC(...args);
  }}
}}

class MockWebSocket {{
  static OPEN = 1;
  static CLOSED = 3;

  constructor(url) {{
    this.url = url;
    this.readyState = MockWebSocket.OPEN;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    wsInstances.push(this);
  }}

  send() {{}}

  close() {{
    this.readyState = MockWebSocket.CLOSED;
    if (typeof this.onclose === 'function') {{
      this.onclose({{ code: 1000 }});
    }}
  }}
}}

const context = {{
  console: harnessConsole,
  Date: MockDate,
  URLSearchParams,
  document,
  window: {{ location: {{ protocol: 'http:', host: 'localhost' }} }},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  sessionStorage: {{
    getItem(key) {{
      return sessionStore.has(key) ? sessionStore.get(key) : null;
    }},
    setItem(key, value) {{
      sessionStore.set(key, String(value));
    }},
    removeItem(key) {{
      sessionStore.delete(key);
    }},
  }},
  setTimeout(fn, ms, ...args) {{
    if ((ms ?? 0) <= 0) {{
      return nativeSetTimeout(fn, ms, ...args);
    }}
    const handle = {{
      id: timeoutHandles.length + 1,
      fn: () => fn(...args),
      ms,
      cleared: false,
    }};
    timeoutHandles.push(handle);
    return handle;
  }},
  clearTimeout(handle) {{
    if (!handle) return;
    if (typeof handle === 'object' && 'fn' in handle) {{
      handle.cleared = true;
      return;
    }}
    nativeClearTimeout(handle);
  }},
  setInterval(fn, ms) {{
    const handle = {{
      id: intervalHandles.length + 1,
      fn,
      ms,
      cleared: false,
      lastLogIndex: 0,
    }};
    intervalHandles.push(handle);
    return handle;
  }},
  clearInterval(handle) {{
    if (!handle) return;
    if (typeof handle === 'object') {{
      handle.cleared = true;
      return;
    }}
    const index = Number(handle) - 1;
    if (index >= 0 && index < intervalHandles.length) {{
      intervalHandles[index].cleared = true;
    }}
  }},
  WebSocket: MockWebSocket,
  theme: {{ applyTheme() {{}}, toggle() {{}} }},
  toast: {{ success() {{}}, error() {{}}, warning() {{}}, info() {{}} }},
  format: {{ date(value) {{ return value ? String(value) : '-'; }} }},
  escapeHtml(value) {{ return String(value ?? ''); }},
  getServiceTypeText(value) {{ return String(value ?? '-'); }},
  fetch: async () => ({{ ok: true, json: async () => ({{}}), blob: async () => ({{}}), headers: {{ get() {{ return null; }} }} }}),
  confirm: async () => true,
  api: {{
    async post(path, payload) {{
      logs.lastPostPath = path;
      logs.lastPostPayload = JSON.parse(JSON.stringify(payload));
      if (path === '/registration/start') {{
        return {{ task_uuid: 'task-single-01', status: 'pending' }};
      }}
      return {{ batch_id: 'batch-001', count: payload.count }};
    }},
    async get(path) {{
      logs.apiGetPaths.push(path);
      const parsedUrl = new URL(path, 'http://localhost');
      const pathname = parsedUrl.pathname;
      const searchParams = parsedUrl.searchParams;

      if (pathname === '/registration/failures/summary') {{
        return {{
          total_failed_attempts: 12,
          today_failed_attempts: 3,
          top_email_suffixes: [
            {{ value: searchParams.get('pipeline_key') || 'blocked.test', count: 8 }},
            {{ value: 'other.test', count: 4 }},
          ],
          top_error_codes: [
            {{ value: 'registration_disallowed', count: 9 }},
            {{ value: 'proxy_error', count: 3 }},
          ],
          top_proxy_ips: [
            {{ value: '1.1.1.1', count: 5 }},
            {{ value: 'unknown', count: 2 }},
          ],
        }};
      }}

      if (pathname === '/registration/failures') {{
        return {{
          total: 12,
          items: [
            {{
              id: 1,
              task_uuid: 'task-failure-01',
              attempt_no: 1,
              pipeline_key: searchParams.get('pipeline_key') || 'current_pipeline',
              registration_mode: 'batch',
              email: 'tester@blocked.test',
              email_suffix: 'blocked.test',
              proxy_ip: '1.1.1.1',
              error_code: 'registration_disallowed',
              error_detail: 'blocked by upstream',
              failed_at: '2026-03-28T10:00:00Z',
              extra_json: {{ step: 'create_account_profile' }},
            }},
          ],
        }};
      }}

      if (scenarioName === 'single_task_log_event_immediate_append' && path === '/registration/tasks/task-single-01') {{
        return new Promise(() => {{}});
      }}

      if (path === '/registration/batch/batch-unlimited-01') {{
        return {{
          total: 0,
          completed: 4,
          success: 2,
          failed: 2,
          finished: false,
          is_unlimited: true,
          consecutive_failures: 1,
          max_consecutive_failures: 10,
          domain_stats: [],
        }};
      }}
      if (path === '/registration/tasks/task-single-01') {{
        return {{
          task_uuid: 'task-single-01',
          status: 'running',
          email: 'tester@example.com',
          email_service: 'tempmail',
          steps: [
            {{ step_key: 'create_email', status: 'running', duration_ms: 88 }},
          ],
        }};
      }}
      if (path === '/registration/batch/batch-001') {{
        return {{
          batch_id: 'batch-001',
          status: 'running',
          total: 2,
          completed: 1,
          success: 1,
          failed: 0,
          finished: false,
          is_unlimited: false,
          consecutive_failures: 0,
          max_consecutive_failures: 10,
          domain_stats: [],
        }};
      }}
      if (path === '/registration/outlook-batch/batch-001') {{
        return {{
          batch_id: 'batch-001',
          status: 'running',
          total: 2,
          completed: 1,
          success: 1,
          failed: 0,
          finished: false,
          skipped: 0,
          logs: [],
        }};
      }}
      if (path === '/registration/streams/task/task-single-01/snapshot') {{
        if (scenarioName === 'single_task_ws_handshake_timeout_falls_back_to_polling') {{
          return {{
            seq: 10,
            stream: 'task:task-single-01',
            kind: 'snapshot',
            payload: {{
              task: {{ task_uuid: 'task-single-01', status: 'running' }},
              current_step: {{ step_key: 'create_email', status: 'running' }},
              steps: [{{ step_key: 'create_email', status: 'running' }}],
              logs_tail: [],
            }},
          }};
        }}
        return {{
          seq: 10,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'completed' }},
            current_step: {{}},
            steps: [],
            logs_tail: ['done'],
          }},
        }};
      }}
      if (path === '/registration/streams/batch/batch-001/snapshot') {{
        return {{
          seq: 20,
          stream: 'batch:batch-001',
          kind: 'snapshot',
          payload: {{
            batch: {{
              batch_id: 'batch-001',
              status: 'completed',
              finished: true,
              total: 2,
              completed: 2,
              success: 2,
              failed: 0,
              skipped: 0,
              is_unlimited: false,
              consecutive_failures: 0,
              max_consecutive_failures: 10,
              domain_stats: [],
            }},
            logs_tail: ['batch-done'],
          }},
        }};
      }}

      return {{ accounts: [], finished: false }};
    }},
    async patch() {{ return {{ success: true }}; }},
    async delete() {{ return {{ success: true }}; }},
  }},
}};

context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(realtimeLogStoreSource, context);
vm.runInContext(realtimeLogClientSource, context);
vm.runInContext(realtimeLogConsoleSource, context);
vm.runInContext(registrationStreamSource, context);
vm.runInContext(
  appSource + `\n;globalThis.__appTestExports = {{\n  handleStartRegistration,\n  handleModeChange,\n  handleBatchRegistration,\n  handleSingleRegistration,\n  handleOutlookBatchRegistration,\n  handleRegistrationLogAutoScrollChange,\n  reduceRegistrationStream,\n  renderTaskSteps,\n  renderSingleTaskProgressSummary,\n  buildRegistrationFailureQueryParams,\n  loadRegistrationFailureAnalysis,\n  loadRegistrationFailureSummary,\n  loadRegistrationFailureList,\n  renderRegistrationFailureRows,\n  openRegistrationFailureDetail,\n  openRegistrationFailureDetailByIndex,\n  closeRegistrationFailureDetail,\n  showTaskStatus,\n  showBatchStatus,\n  updateBatchProgress,\n  restoreActiveTask,\n  finalizeSingleTaskIfTerminal,\n  resetButtons,\n  elements,\n}};`,
  context,
);

const exported = context.__appTestExports;

function setupBaseElements() {{
  getElement('email-service').value = 'tempmail:default';
  getElement('reg-mode').value = 'single';
  getElement('batch-count').value = '5';
  getElement('interval-min').value = '5';
  getElement('interval-max').value = '30';
  getElement('concurrency-count').value = '3';
  getElement('concurrency-mode').value = 'pipeline';
  getElement('pipeline-key').value = 'current_pipeline';
  getElement('use-proxy').checked = false;
  getElement('proxy').value = '';
  getElement('batch-count-group').style.display = 'none';
  getElement('batch-options').style.display = 'none';
  getElement('batch-domain-stats').innerHTML = '';
  getElement('batch-consecutive-failures').textContent = '-';
  getElement('registration-log-auto-scroll').checked = true;
}}

function getRegistrationConsoleController() {{
  return getElement('console-log').__realtimeLogConsoleController || null;
}}

function getRenderedConsoleLineCount() {{
  const controller = getRegistrationConsoleController();
  if (controller && controller.lastRender && Array.isArray(controller.lastRender.visibleEntries)) {{
    return controller.lastRender.visibleEntries.length;
  }}
  return getElement('console-log').querySelectorAll('.log-line').length;
}}

function getLastRenderedConsoleText() {{
  const controller = getRegistrationConsoleController();
  if (controller && controller.lastRender && Array.isArray(controller.lastRender.visibleEntries) && controller.lastRender.visibleEntries.length > 0) {{
    const lastEntry = controller.lastRender.visibleEntries[controller.lastRender.visibleEntries.length - 1];
    return `${{lastEntry.display_time || ''}} ${{lastEntry.level || ''}} ${{lastEntry.message || ''}}`.trim();
  }}
  const logLines = getElement('console-log').querySelectorAll('.log-line');
  const lastLine = logLines.length ? logLines[logLines.length - 1] : null;
  return lastLine ? String(lastLine.innerHTML || '') : '';
}}

function consoleHasVisibleMessage(keyword) {{
  const controller = getRegistrationConsoleController();
  if (controller && controller.lastRender && Array.isArray(controller.lastRender.visibleEntries)) {{
    return controller.lastRender.visibleEntries.some(entry => String(entry.message || entry.raw || '').includes(keyword));
  }}
  return String(getElement('console-log').innerHTML || '').includes(keyword);
}}

async function runScenario() {{
  setupBaseElements();

  switch (scenarioName) {{
    case 'unlimited_mode_request': {{
      const regMode = getElement('reg-mode');
      regMode.value = 'unlimited';
      exported.handleModeChange({{ target: regMode }});

      const requestPayload = {{ email_service_type: 'tempmail' }};
      await exported.handleBatchRegistration(requestPayload);

      return {{
        batch_count_display: getElement('batch-count-group').style.display || '',
        request_payload: logs.lastPostPayload,
        saved_active_task: JSON.parse(context.sessionStorage.getItem('activeTask') || 'null'),
      }};
    }}
    case 'pipeline_batch_request': {{
      getElement('pipeline-key').value = 'codexgen_pipeline';
      const requestPayload = {{ email_service_type: 'tempmail' }};
      await exported.handleBatchRegistration(requestPayload);
      return {{
        request_payload: logs.lastPostPayload,
      }};
    }}
    case 'batch_mode_persists_after_reset': {{
      const regMode = getElement('reg-mode');
      regMode.value = 'batch';
      exported.handleModeChange({{ target: regMode }});
      exported.resetButtons();
      getElement('pipeline-key').value = 'codexgen_pipeline';
      await exported.handleStartRegistration({{ preventDefault() {{}} }});
      return {{
        reg_mode_value: regMode.value,
        request_path: logs.lastPostPath,
      }};
    }}
    case 'single_use_proxy_request_matrix': {{
      getElement('email-service').value = 'tempmail:default';
      getElement('proxy').value = 'http://manual-static:8000';
      getElement('use-proxy').checked = false;
      await exported.handleStartRegistration({{ preventDefault() {{}} }});
      const disabledRequest = JSON.parse(JSON.stringify(logs.lastPostPayload));

      getElement('proxy').value = 'http://manual-static:8000';
      getElement('use-proxy').checked = true;
      await exported.handleStartRegistration({{ preventDefault() {{}} }});
      const enabledRequest = JSON.parse(JSON.stringify(logs.lastPostPayload));

      return {{
        disabled_request: disabledRequest,
        enabled_request: enabledRequest,
      }};
    }}
    case 'render_task_steps': {{
      exported.renderTaskSteps([
        {{ step_key: 'create_email', status: 'completed', duration_ms: 123 }},
        {{ step_key: 'submit_login_email', status: 'failed', duration_ms: 456, error_message: 'timeout' }},
      ]);
      return {{
        waterfall_html: getElement('task-step-waterfall').innerHTML,
      }};
    }}
    case 'single_task_step_refresh': {{
      await exported.handleSingleRegistration({{ email_service_type: 'tempmail', pipeline_key: 'current_pipeline' }});
      return {{
        api_get_paths: logs.apiGetPaths.slice(),
        waterfall_html: getElement('task-step-waterfall').innerHTML,
      }};
    }}
    case 'codexgen_single_task_hides_steps': {{
      exported.showTaskStatus({{
        task_uuid: 'task-single-01',
        status: 'running',
        email: 'tester@example.com',
        email_service: 'tempmail',
        pipeline_key: 'codexgen_pipeline',
        started_at: '2026-03-27T09:00:49Z',
        task_progress: {{
          step_index: 2,
          total_steps: 5,
          progress_percent: 40,
          elapsed_ms: 12000,
        }},
        steps: [
          {{ step_key: 'create_email', status: 'completed', duration_ms: 100 }},
          {{ step_key: 'submit_login_email', status: 'running', duration_ms: 200 }},
        ],
      }});

      return {{
        waterfall_html: getElement('task-step-waterfall').innerHTML,
        waterfall_display: getElement('task-step-waterfall').style.display || '',
      }};
    }}
    case 'single_task_progress_summary': {{
      exported.reduceRegistrationStream({{
        seq: 10,
        stream: 'task:task-single-01',
        kind: 'snapshot',
        payload: {{
          task: {{ task_uuid: 'task-single-01', status: 'running', started_at: '2026-03-27T09:00:49Z' }},
          current_step: {{ step_key: 'submit_login_email', status: 'running' }},
          steps: [
            {{ step_key: 'create_email', status: 'completed', duration_ms: 100 }},
            {{ step_key: 'submit_login_email', status: 'running', duration_ms: 200 }},
          ],
          task_progress: {{
            step_index: 2,
            total_steps: 5,
            progress_percent: 40,
            elapsed_ms: 12000,
          }},
          logs_tail: [],
        }},
      }});

      return {{
        progress_step_text: getElement('single-progress-step-text').textContent,
        progress_current_step: getElement('single-progress-current-step').textContent,
        progress_elapsed_text: getElement('single-progress-elapsed').textContent,
        progress_bar_width: getElement('single-progress-bar').style.width || '',
      }};
    }}
    case 'single_task_runtime_timer': {{
      currentNowMs = NativeDate.parse('2026-03-27T09:01:01Z');
      exported.showTaskStatus({{
        task_uuid: 'task-single-01',
        status: 'running',
        email: 'tester@example.com',
        email_service: 'tempmail',
        started_at: '2026-03-27T08:00:00Z',
        task_progress: {{
          step_index: 2,
          total_steps: 5,
          progress_percent: 40,
          elapsed_ms: 12000,
        }},
        steps: [],
      }});

      const progressElapsedText = getElement('single-progress-elapsed').textContent;
      const runtimeHandle = intervalHandles.find(handle => handle && handle.ms === 1000 && handle.cleared !== true);
      if (!runtimeHandle) {{
        throw new Error('runtime interval handle missing');
      }}
      currentNowMs += 1000;
      await runtimeHandle.fn();
      return {{
        progress_elapsed_text: progressElapsedText,
        progress_elapsed_after_tick: getElement('single-progress-elapsed').textContent,
      }};
    }}
    case 'single_task_runtime_timer_naive_utc': {{
      const originalParse = context.Date.parse;
      context.Date.parse = (value) => {{
        const text = String(value ?? '');
        if (/Z$|[+-]\\d\\d:\\d\\d$/.test(text)) {{
          return NativeDate.parse(text);
        }}
        return NativeDate.parse(`${{text}}+08:00`);
      }};
      currentNowMs = NativeDate.parse('2026-03-27T09:01:01Z');
      exported.showTaskStatus({{
        task_uuid: 'task-single-01',
        status: 'running',
        email: 'tester@example.com',
        email_service: 'tempmail',
        started_at: '2026-03-27T08:00:00',
        task_progress: {{
          step_index: 2,
          total_steps: 5,
          progress_percent: 40,
          elapsed_ms: 12000,
        }},
        steps: [],
      }});

      const progressElapsedText = getElement('single-progress-elapsed').textContent;
      const runtimeHandle = intervalHandles.find(handle => handle && handle.ms === 1000 && handle.cleared !== true);
      if (!runtimeHandle) {{
        throw new Error('runtime interval handle missing');
      }}
      currentNowMs += 1000;
      await runtimeHandle.fn();
      context.Date.parse = originalParse;
      return {{
        progress_elapsed_text: progressElapsedText,
        progress_elapsed_after_tick: getElement('single-progress-elapsed').textContent,
      }};
    }}
    case 'single_task_terminal_freezes_elapsed': {{
      currentNowMs = NativeDate.parse('2026-03-27T09:01:01Z');
      exported.showTaskStatus({{
        task_uuid: 'task-single-01',
        status: 'running',
        email: 'tester@example.com',
        email_service: 'tempmail',
        pipeline_key: 'current_pipeline',
        started_at: '2026-03-27T08:00:00Z',
        task_progress: {{
          step_index: 2,
          total_steps: 5,
          progress_percent: 40,
          elapsed_ms: 12000,
        }},
        steps: [],
      }});

      const runtimeHandle = intervalHandles.find(handle => handle && handle.ms === 1000 && handle.cleared !== true);
      if (!runtimeHandle) {{
        throw new Error('runtime interval handle missing');
      }}
      const progressElapsedBeforeFinalize = getElement('single-progress-elapsed').textContent;
      currentNowMs += 5000;
      exported.finalizeSingleTaskIfTerminal('task-single-01', 'completed');
      return {{
        progress_elapsed_before_finalize: progressElapsedBeforeFinalize,
        progress_elapsed_after_finalize: getElement('single-progress-elapsed').textContent,
        runtime_handle_cleared: runtimeHandle.cleared === true,
      }};
    }}
    case 'single_task_snapshot_required_terminal_snapshot_should_finalize': {{
      // 模拟：按钮已进入运行态
      getElement('start-btn').disabled = true;
      getElement('cancel-btn').disabled = false;

      // 创建任务并建立 websocket（不会触发 onopen，避免心跳 setInterval 持续占用）
      await exported.handleSingleRegistration({{ email_service_type: 'tempmail', pipeline_key: 'current_pipeline' }});

      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      // 触发 snapshot_required → 拉取 snapshot（completed）→ 应当执行收尾逻辑
      await ws.onmessage({{
        data: JSON.stringify({{
          stream: 'task:task-single-01',
          kind: 'snapshot_required',
          payload: {{ reason: 'after_seq_expired' }},
        }}),
      }});

      return {{
        start_disabled: !!getElement('start-btn').disabled,
        cancel_disabled: !!getElement('cancel-btn').disabled,
        connection_status: String(getElement('registration-stream-status').textContent || ''),
        ws_ready_state: ws.readyState,
      }};
    }}
    case 'batch_snapshot_required_terminal_snapshot_should_finalize': {{
      // 模拟：按钮已进入运行态
      getElement('start-btn').disabled = true;
      getElement('cancel-btn').disabled = false;

      // 触发批量注册（创建 batch websocket）
      const requestPayload = {{ email_service_type: 'tempmail' }};
      await exported.handleBatchRegistration(requestPayload);

      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      await ws.onmessage({{
        data: JSON.stringify({{
          stream: 'batch:batch-001',
          kind: 'snapshot_required',
          payload: {{ reason: 'after_seq_expired' }},
        }}),
      }});

      return {{
        start_disabled: !!getElement('start-btn').disabled,
        cancel_disabled: !!getElement('cancel-btn').disabled,
        connection_status: String(getElement('registration-stream-status').textContent || ''),
        ws_ready_state: ws.readyState,
      }};
    }}
    case 'batch_ws_error_fallback_non_outlook_uses_registration_batch_endpoint': {{
      // 模拟：按钮已进入运行态
      getElement('start-btn').disabled = true;
      getElement('cancel-btn').disabled = false;

      // 普通批量注册（非 Outlook）
      const requestPayload = {{ email_service_type: 'tempmail' }};
      await exported.handleBatchRegistration(requestPayload);

      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      // 触发 ws error，进入 polling fallback
      if (typeof ws.onerror !== 'function') {{
        throw new Error('ws.onerror missing');
      }}
      ws.onerror(new Error('boom'));

      // 执行一次 polling tick，触发 api.get
      const lastInterval = intervalHandles.length ? intervalHandles[intervalHandles.length - 1] : null;
      if (!lastInterval) {{
        throw new Error('interval handle missing');
      }}
      await lastInterval.fn();

      return {{
        api_get_paths: logs.apiGetPaths.slice(),
      }};
    }}
    case 'unlimited_progress_running': {{
      currentNowMs = NativeDate.parse('2026-03-27T09:01:01Z');
      exported.showBatchStatus({{ count: 0 }});
      exported.updateBatchProgress({{
        started_at: '2026-03-27T08:00:00Z',
        is_unlimited: true,
        completed: 5,
        total: 0,
        finished: false,
        success: 2,
        failed: 1,
        consecutive_failures: 3,
        max_consecutive_failures: 10,
        domain_stats: [
          {{ domain: 'gmail.com', success: 3, failed: 1, total: 4, success_rate: 75, failure_rate: 25 }},
        ],
      }});

      return {{
        progress_text: getElement('batch-progress-text').textContent,
        progress_percent: getElement('batch-progress-percent').textContent,
        progress_bar_indeterminate: getElement('progress-bar').classList.contains('indeterminate'),
        consecutive_failures_text: getElement('batch-consecutive-failures').textContent,
        domain_stats_display: getElement('batch-domain-stats').style.display || '',
        domain_stats_html: getElement('batch-domain-stats').innerHTML,
        batch_elapsed_text: getElement('batch-progress-elapsed').textContent,
        batch_avg_elapsed_text: getElement('batch-progress-avg-elapsed').textContent,
        batch_avg_elapsed_zero_success_text: (() => {{
          exported.updateBatchProgress({{
            started_at: '2026-03-27T08:00:00Z',
            is_unlimited: true,
            completed: 1,
            total: 0,
            finished: false,
            success: 0,
            failed: 1,
            consecutive_failures: 1,
            max_consecutive_failures: 10,
            domain_stats: [],
          }});
          return getElement('batch-progress-avg-elapsed').textContent;
        }})(),
      }};
    }}
    case 'unlimited_progress_finished': {{
      exported.showBatchStatus({{ count: 0 }});
      exported.updateBatchProgress({{
        is_unlimited: true,
        completed: 8,
        total: 0,
        finished: true,
        success: 6,
        failed: 2,
        consecutive_failures: 0,
        max_consecutive_failures: 10,
        domain_stats: [
          {{ domain: 'gmail.com', success: 3, failed: 1, total: 4, success_rate: 75, failure_rate: 25 }},
        ],
      }});

      return {{
        progress_text: getElement('batch-progress-text').textContent,
        progress_percent: getElement('batch-progress-percent').textContent,
        progress_bar_indeterminate: getElement('progress-bar').classList.contains('indeterminate'),
        domain_stats_html: getElement('batch-domain-stats').innerHTML,
      }};
    }}
    case 'restore_unlimited_task': {{
      context.sessionStorage.setItem('activeTask', JSON.stringify({{
        batch_id: 'batch-unlimited-01',
        mode: 'unlimited',
        total: 0,
      }}));

      await exported.restoreActiveTask();

      return {{
        api_get_paths: logs.apiGetPaths.slice(),
        batch_progress_display: getElement('batch-progress-section').style.display || '',
      }};
    }}
    case 'realtime_store_seq_dedup': {{
      const reduce = context.window?.registrationStream?.reduce;
      if (typeof reduce !== 'function') {{
        throw new Error('registrationStream.reduce missing');
      }}

      const events = [
        {{
          seq: 1,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'submit_login_email' }},
            steps: [{{ step_key: 'submit_login_email', status: 'running' }}],
            logs_tail: ['boot'],
          }},
        }},
        // 相同 message，但不同 seq：必须都保留（不能被 message 去重吞掉）
        {{ seq: 2, stream: 'task:task-single-01', kind: 'log_appended', payload: {{ task_uuid: 'task-single-01', message: 'same-line' }} }},
        {{ seq: 2, stream: 'task:task-single-01', kind: 'log_appended', payload: {{ task_uuid: 'task-single-01', message: 'same-line-dup-seq' }} }},
        {{ seq: 3, stream: 'task:task-single-01', kind: 'log_appended', payload: {{ task_uuid: 'task-single-01', message: 'same-line' }} }},
        // 第二次 snapshot：必须覆盖 logs_tail，而不是追加（避免 snapshot 重放导致重复）
        {{
          seq: 4,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'submit_login_email' }},
            steps: [{{ step_key: 'submit_login_email', status: 'running' }}],
            logs_tail: ['same-line', 'same-line'],
          }},
        }},
        {{ seq: 3, stream: 'batch:batch-001', kind: 'batch_progress_updated', payload: {{ batch_id: 'batch-001', success: 3 }} }},
        {{ seq: 999, stream: 'task:task-single-01', kind: 'connection_state_changed', payload: {{ status: 'polling' }}, meta: {{ local: true }} }},
      ];

      let state = {{
        cursors: {{}},
        currentStep: null,
        steps: [],
        batch: {{}},
        logs: [],
        connection: {{ status: 'disconnected' }},
      }};

      for (const event of events) {{
        state = reduce(state, event);
        exported.reduceRegistrationStream(event);
      }}

      const renderedLogCount = getRenderedConsoleLineCount();
      return {{
        current_step_key: state.currentStep ? String(state.currentStep.step_key || '') : '',
        batch_success: state.batch ? String(state.batch.success ?? '') : '',
        log_count: Array.isArray(state.logs) ? state.logs.length : 0,
        rendered_log_count: renderedLogCount,
        connection_status: state.connection ? String(state.connection.status || '') : '',
      }};
    }}
    case 'realtime_store_full_window_log_append': {{
      const reduce = context.window?.registrationStream?.reduce;
      if (typeof reduce !== 'function') {{
        throw new Error('registrationStream.reduce missing');
      }}

      const stream = 'task:task-single-01';
      const tail = Array.from({{ length: 500 }}, (_, i) => `line-${{i}}`);
      const events = [
        {{
          seq: 1,
          stream,
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'submit_login_email' }},
            steps: [],
            logs_tail: tail,
          }},
        }},
        {{ seq: 2, stream, kind: 'log_appended', payload: {{ task_uuid: 'task-single-01', message: 'after-full' }} }},
      ];

      let state = {{
        cursors: {{}},
        currentStep: null,
        steps: [],
        batch: {{}},
        logs: [],
        connection: {{ status: 'disconnected' }},
      }};

      for (const event of events) {{
        state = reduce(state, event);
        exported.reduceRegistrationStream(event);
      }}

      const lastHtml = getLastRenderedConsoleText();
      const consoleHtml = String(getElement('console-log').innerHTML || '');

      return {{
        log_count: Array.isArray(state.logs) ? state.logs.length : 0,
        rendered_log_count: getRenderedConsoleLineCount(),
        last_rendered_contains_after_full: lastHtml.includes('after-full')
          || consoleHtml.includes('after-full')
          || consoleHasVisibleMessage('after-full'),
      }};
    }}
    case 'single_task_log_event_immediate_append': {{
      const registrationPromise = exported.handleSingleRegistration({{
        email_service_type: 'tempmail',
        pipeline_key: 'codexgen_pipeline',
      }});
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => setTimeout(resolve, 0));

      getElement('console-log').innerHTML = '';

      const ws = wsInstances[0];
      if (ws && typeof ws.onmessage === 'function') {{
        await ws.onmessage({{
          data: JSON.stringify({{
            seq: 1,
            stream: 'task:task-single-01',
            kind: 'snapshot',
            payload: {{
              task: {{ task_uuid: 'task-single-01', status: 'running' }},
              current_step: {{ step_key: 'create_email', status: 'running' }},
              steps: [{{ step_key: 'create_email', status: 'running' }}],
              logs_tail: ['boot-line'],
            }},
          }}),
        }});
        await ws.onmessage({{
          data: JSON.stringify({{
            seq: 2,
            stream: 'task:task-single-01',
            kind: 'log_appended',
            payload: {{ task_uuid: 'task-single-01', message: 'live-line' }},
          }}),
        }});
      }}

      const lastHtml = getLastRenderedConsoleText();
      const consoleHtml = String(getElement('console-log').innerHTML || '');

      return {{
        rendered_log_count: getRenderedConsoleLineCount(),
        last_rendered_contains_live_line: lastHtml.includes('live-line')
          || consoleHtml.includes('live-line')
          || consoleHasVisibleMessage('live-line'),
      }};
    }}
    case 'shared_console_single_task_live_append': {{
      await exported.handleSingleRegistration({{
        email_service_type: 'tempmail',
        pipeline_key: 'codexgen_pipeline',
      }});
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => nativeSetTimeout(resolve, 0));

      const consoleRoot = getElement('console-log');
      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 1,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'create_email', status: 'running' }},
            steps: [{{ step_key: 'create_email', status: 'running' }}],
            logs_tail: [
              {{
                seq: 1,
                stream: 'task:task-single-01',
                timestamp: '2026-03-27T09:00:00+08:00',
                display_time: '09:00:00',
                level: 'INFO',
                message: 'boot-line',
                raw: '2026-03-27 09:00:00.000 [INFO] boot-line',
                source: 'scheduler',
              }},
            ],
          }},
        }}),
      }});

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 2,
          stream: 'task:task-single-01',
          kind: 'log_appended',
          payload: {{
            entry: {{
              seq: 2,
              stream: 'task:task-single-01',
              timestamp: '2026-03-27T09:00:01+08:00',
              display_time: '09:00:01',
              level: 'INFO',
              message: 'live-line',
              raw: '2026-03-27 09:00:01.000 [INFO] live-line',
              source: 'scheduler',
            }},
          }},
        }}),
      }});
      await Promise.resolve();

      const htmlBeforeTeardown = String(consoleRoot.innerHTML || '');
      const renderedLogCount = getRenderedConsoleLineCount();
      const lastLineLevelClass = htmlBeforeTeardown.includes('realtime-log-level-info')
        ? 'realtime-log-level-info'
        : '';
      const legacyDirectAppendPathUsed = /class="log-line(?:\s|")/.test(htmlBeforeTeardown);

      if (typeof ws.onerror !== 'function') {{
        throw new Error('ws.onerror missing');
      }}
      ws.onerror(new Error('boom'));
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => nativeSetTimeout(resolve, 0));

      const fallbackHandle = intervalHandles.length ? intervalHandles[intervalHandles.length - 1] : null;

      return {{
        console_has_shared_class: consoleRoot.classList.contains('realtime-log-console-shell'),
        rendered_log_count: renderedLogCount,
        last_line_level_class: lastLineLevelClass,
        legacy_direct_append_path_used: legacyDirectAppendPathUsed,
        teardown_closed_ws: ws.readyState === MockWebSocket.CLOSED,
        teardown_stopped_fallback: !!(fallbackHandle && fallbackHandle.cleared),
      }};
    }}
    case 'shared_console_manual_scroll_preserved': {{
      await exported.handleSingleRegistration({{
        email_service_type: 'tempmail',
        pipeline_key: 'codexgen_pipeline',
      }});
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => nativeSetTimeout(resolve, 0));

      const consoleRoot = getElement('console-log');
      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 1,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'create_email', status: 'running' }},
            steps: [{{ step_key: 'create_email', status: 'running' }}],
            logs_tail: [
              {{
                seq: 1,
                stream: 'task:task-single-01',
                timestamp: '2026-03-27T09:00:00+08:00',
                display_time: '09:00:00',
                level: 'INFO',
                message: 'boot-line',
                raw: '2026-03-27 09:00:00.000 [INFO] boot-line',
                source: 'scheduler',
              }},
            ],
          }},
        }}),
      }});

      consoleRoot.scrollTop = 120;
      consoleRoot.scrollHeight = 1200;
      consoleRoot.clientHeight = 240;
      consoleRoot.dispatchEvent('scroll');

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 2,
          stream: 'task:task-single-01',
          kind: 'log_appended',
          payload: {{
            entry: {{
              seq: 2,
              stream: 'task:task-single-01',
              timestamp: '2026-03-27T09:00:01+08:00',
              display_time: '09:00:01',
              level: 'INFO',
              message: 'live-line',
              raw: '2026-03-27 09:00:01.000 [INFO] live-line',
              source: 'scheduler',
            }},
          }},
        }}),
      }});

      const controller = getRegistrationConsoleController();
      return {{
        auto_scroll_disabled_after_manual_scroll: controller ? controller.ui.autoScroll === false : false,
        scroll_top_after_live_append: Number(consoleRoot.scrollTop || 0),
        last_rendered_contains_live_line: consoleHasVisibleMessage('live-line'),
      }};
    }}
    case 'shared_console_auto_scroll_toggle_ui': {{
      await exported.handleSingleRegistration({{
        email_service_type: 'tempmail',
        pipeline_key: 'codexgen_pipeline',
      }});
      await Promise.resolve();
      await Promise.resolve();
      await new Promise(resolve => nativeSetTimeout(resolve, 0));

      const consoleRoot = getElement('console-log');
      const autoScrollInput = getElement('registration-log-auto-scroll');
      const ws = wsInstances[0];
      if (!ws) {{
        throw new Error('MockWebSocket instance missing');
      }}

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 1,
          stream: 'task:task-single-01',
          kind: 'snapshot',
          payload: {{
            task: {{ task_uuid: 'task-single-01', status: 'running' }},
            current_step: {{ step_key: 'create_email', status: 'running' }},
            steps: [{{ step_key: 'create_email', status: 'running' }}],
            logs_tail: [
              {{
                seq: 1,
                stream: 'task:task-single-01',
                timestamp: '2026-03-27T09:00:00+08:00',
                display_time: '09:00:00',
                level: 'INFO',
                message: 'boot-line',
                raw: '2026-03-27 09:00:00.000 [INFO] boot-line',
                source: 'scheduler',
              }},
            ],
          }},
        }}),
      }});

      consoleRoot.scrollTop = 120;
      autoScrollInput.checked = false;
      exported.handleRegistrationLogAutoScrollChange();

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 2,
          stream: 'task:task-single-01',
          kind: 'log_appended',
          payload: {{
            entry: {{
              seq: 2,
              stream: 'task:task-single-01',
              timestamp: '2026-03-27T09:00:01+08:00',
              display_time: '09:00:01',
              level: 'INFO',
              message: 'live-line-1',
              raw: '2026-03-27 09:00:01.000 [INFO] live-line-1',
              source: 'scheduler',
            }},
          }},
        }}),
      }});

      const scrollTopAfterDisableAndAppend = Number(consoleRoot.scrollTop || 0);

      autoScrollInput.checked = true;
      exported.handleRegistrationLogAutoScrollChange();

      await ws.onmessage({{
        data: JSON.stringify({{
          seq: 3,
          stream: 'task:task-single-01',
          kind: 'log_appended',
          payload: {{
            entry: {{
              seq: 3,
              stream: 'task:task-single-01',
              timestamp: '2026-03-27T09:00:02+08:00',
              display_time: '09:00:02',
              level: 'INFO',
              message: 'live-line-2',
              raw: '2026-03-27 09:00:02.000 [INFO] live-line-2',
              source: 'scheduler',
            }},
          }},
        }}),
      }});

      return {{
        scroll_top_after_disable_and_append: scrollTopAfterDisableAndAppend,
        scroll_top_after_reenable_and_append: Number(consoleRoot.scrollTop || 0),
        checkbox_checked_after_reenable: autoScrollInput.checked === true,
      }};
    }}
    case 'load_registration_failures': {{
      getElement('failure-filter-pipeline-key').value = 'codexgen_pipeline';
      getElement('failure-filter-registration-mode').value = 'batch';
      getElement('failure-filter-email-suffix').value = 'blocked.test';
      getElement('failure-filter-error-keyword').value = 'registration_disallowed';

      await exported.loadRegistrationFailureAnalysis();

      return {{
        api_get_paths: logs.apiGetPaths.slice(),
        summary_total_text: getElement('failure-total-attempts').textContent,
        table_html: getElement('registration-failure-table-body').innerHTML,
        page_indicator: getElement('failure-page-indicator').textContent,
      }};
    }}
    case 'render_registration_failure_rows': {{
      const malicious = '<script>alert(1)</script>@blocked.test';
      exported.renderRegistrationFailureRows([
        {{
          id: 1,
          task_uuid: 'task-failure-evil',
          attempt_no: 1,
          pipeline_key: 'codexgen_pipeline',
          registration_mode: 'batch',
          email: malicious,
          email_suffix: 'blocked.test',
          proxy_ip: '1.1.1.1',
          error_code: 'registration_disallowed',
          error_detail: malicious,
          failed_at: '2026-03-28T10:00:00Z',
          extra_json: {{ html: malicious }},
        }},
      ]);
      exported.openRegistrationFailureDetailByIndex(0);

      return {{
        table_html: getElement('registration-failure-table-body').innerHTML,
        detail_dialog_open: getElement('registration-failure-detail-dialog').open === true,
        detail_uses_text_content: getElement('registration-failure-detail-text').dataset.renderMode === 'textContent',
      }};
    }}
    case 'single_task_ws_handshake_timeout_falls_back_to_polling': {{
      await exported.handleSingleRegistration({{
        email_service_type: 'tempmail',
        pipeline_key: 'current_pipeline',
      }});

      const timeoutHandle = timeoutHandles.find(handle => handle && handle.cleared !== true);
      if (!timeoutHandle) {{
        throw new Error('timeout handle missing');
      }}

      await timeoutHandle.fn();
      await Promise.resolve();
      await new Promise(resolve => nativeSetTimeout(resolve, 0));

      const pollingHandle = intervalHandles.find(handle => handle && handle.cleared !== true);

      return {{
        connection_status: String(getElement('registration-stream-status').textContent || ''),
        api_get_paths: logs.apiGetPaths.slice(),
        polling_interval_started: !!pollingHandle,
      }};
    }}
    default:
      throw new Error(`Unknown scenario: ${{scenarioName}}`);
  }}
}}

runScenario()
  .then(result => {{
    process.stdout.write(JSON.stringify(result));
  }})
  .catch(error => {{
    process.stderr.write(String(error.stack || error));
    process.exit(1);
  }});
"""

    result = subprocess.run(
        ["node"],
        input=node_script,
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Node harness failed for scenario {name!r}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return json.loads(result.stdout)
