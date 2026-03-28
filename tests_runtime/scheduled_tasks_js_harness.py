from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_TASKS_JS = ROOT / "static" / "js" / "scheduled_tasks.js"
RUN_CENTER_SHARED_JS = ROOT / "static" / "js" / "run_center_shared.js"


def run_scheduled_tasks_js_scenario(name: str) -> dict:
    scheduled_source = SCHEDULED_TASKS_JS.read_text(encoding="utf-8") if SCHEDULED_TASKS_JS.exists() else ""
    shared_source = RUN_CENTER_SHARED_JS.read_text(encoding="utf-8") if RUN_CENTER_SHARED_JS.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scheduledSource = {json.dumps(scheduled_source)};
const sharedSource = {json.dumps(shared_source)};

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

function dataAttrToDatasetKey(name) {{
  return name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}}

function matchesDataSelector(target, selector) {{
  if (!target || !target.dataset) return false;
  const matches = [...String(selector || '').matchAll(/\[data-([a-z0-9-]+)(?:=[^\]]+)?\]/g)];
  if (matches.length === 0) return false;
  return matches.every(match => target.dataset[dataAttrToDatasetKey(match[1])] !== undefined);
}}

function createMockElement(id = '') {{
  const element = {{
    id,
    style: {{}},
    dataset: {{}},
    disabled: false,
    checked: false,
    required: false,
    value: '',
    href: '',
    className: '',
    classList: createClassList(),
    _textContent: '',
    _innerHTML: '',
    _listeners: {{}},
    addEventListener(type, handler) {{
      this._listeners[type] = handler;
    }},
    async dispatchEvent(type, event = {{}}) {{
      const handler = this._listeners[type];
      if (!handler) return undefined;
      return handler({{ currentTarget: this, target: this, preventDefault() {{}}, ...event }});
    }},
    click() {{
      return this.dispatchEvent('click');
    }},
    reset() {{
      this.value = '';
      this.checked = false;
    }},
    focus() {{}},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
    closest(selector) {{
      return matchesDataSelector(this, selector) ? this : null;
    }},
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
}};

document.body.appendChild = () => {{}};
document.body.removeChild = () => {{}};

const logs = {{
  apiGetPaths: [],
  apiPostPaths: [],
  toastCalls: [],
}};

const locationState = {{
  protocol: 'http:',
  host: 'localhost',
  pathname: '/scheduled-tasks',
  href: 'http://localhost/scheduled-tasks',
  search: '?scope=scheduled&source=scheduled-tasks',
  assign(url) {{
    this.href = String(url);
  }},
}};

const context = {{
  console,
  URLSearchParams,
  document,
  window: {{ location: locationState }},
  location: locationState,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  toast: {{
    success(message) {{ logs.toastCalls.push(['success', String(message)]); }},
    error(message) {{ logs.toastCalls.push(['error', String(message)]); }},
    warning(message) {{ logs.toastCalls.push(['warning', String(message)]); }},
    info(message) {{ logs.toastCalls.push(['info', String(message)]); }},
  }},
  format: {{
    date(value) {{ return String(value ?? '-'); }},
  }},
  api: {{
    async get(path) {{
      logs.apiGetPaths.push(String(path));
      if (path === '/scheduled-plans') {{
        return {{
          items: [{{
            id: 42,
            name: 'nightly cleanup',
            task_type: 'cpa_cleanup',
            trigger_type: 'interval',
            interval_value: 5,
            interval_unit: 'minutes',
            enabled: true,
            next_run_at: '2026-03-28T00:00:00Z',
            last_run_started_at: '2026-03-27T23:55:00Z',
            last_run_status: 'success',
          }}],
        }};
      }}
      if (path === '/cpa-services') {{
        return [{{ id: 7, name: 'CPA-7', enabled: true }}];
      }}
      throw new Error(`unexpected GET: ${{path}}`);
    }},
    async post(path) {{
      logs.apiPostPaths.push(String(path));
      return {{ success: true }};
    }},
    async put(path) {{
      return {{ success: true, path: String(path) }};
    }},
  }},
}};

context.window.window = context.window;
context.window.document = document;
context.window.toast = context.toast;
context.window.format = context.format;
context.window.api = context.api;
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(sharedSource, context);
vm.runInContext(
  scheduledSource + `
;globalThis.__scheduledTasksTestExports = {{
  renderPlans,
  setConfigEditorState,
  scheduledTaskElements,
  getCurrentConfigEntries: () => currentConfigEntries,
}};`,
  context,
);

const exported = context.__scheduledTasksTestExports;

async function flush() {{
  await Promise.resolve();
  await Promise.resolve();
}}

function createDelegatedTarget(dataset, value = '') {{
  return {{
    dataset: {{ ...dataset }},
    value,
    disabled: false,
    className: '',
    setAttribute(name, value) {{
      this[name] = String(value);
    }},
    removeAttribute(name) {{
      delete this[name];
    }},
    closest(selector) {{
      return matchesDataSelector(this, selector) ? this : null;
    }},
  }};
}}

async function bootstrap() {{
  getElement('plan-task-type').value = 'cpa_cleanup';
  getElement('plan-trigger-type').value = 'interval';
  getElement('plan-config-json').value = '{{}}';
  if (typeof domListeners.DOMContentLoaded === 'function') {{
    await domListeners.DOMContentLoaded({{ preventDefault() {{}} }});
    await flush();
  }}
}}

async function runScenario() {{
  await bootstrap();

  switch (scenarioName) {{
    case 'delegated_plan_action_run_now': {{
      logs.apiPostPaths = [];
      const button = createDelegatedTarget({{ action: 'run-now', planId: '42' }});
      await getElement('scheduled-plans-table-body').dispatchEvent('click', {{ target: button }});
      await flush();
      return {{ api_post_paths: logs.apiPostPaths.slice() }};
    }}
    case 'delegated_config_value_change': {{
      exported.setConfigEditorState('cpa_cleanup', {{}}, {{}});
      await flush();
      const input = createDelegatedTarget({{ configIndex: '0', configField: 'rawValue' }}, '12');
      await getElement('plan-config-entries-body').dispatchEvent('change', {{ target: input }});
      await flush();
      return {{ updated_value: exported.getCurrentConfigEntries()[0].rawValue }};
    }}
    default:
      throw new Error(`unknown scenario: ${{scenarioName}}`);
  }}
}}

runScenario()
  .then(result => process.stdout.write(JSON.stringify(result)))
  .catch(error => {{
    console.error(error);
    process.exit(1);
  }});
"""

    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)
