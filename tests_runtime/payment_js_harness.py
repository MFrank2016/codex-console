from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAYMENT_JS = ROOT / "static" / "js" / "payment.js"


def run_payment_js_scenario(name: str) -> dict:
    payment_source = PAYMENT_JS.read_text(encoding="utf-8") if PAYMENT_JS.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const paymentSource = {json.dumps(payment_source)};

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
    className: '',
    classList: createClassList(),
    _textContent: '',
    _innerHTML: '',
    _children: [],
    _listeners: {{}},
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
    appendChild(child) {{
      this._children.push(child);
      return child;
    }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
    focus() {{}},
    select() {{}},
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
  getElementById(id) {{ return getElement(id); }},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
  addEventListener(type, handler) {{ domListeners[type] = handler; }},
  createElement() {{ return createMockElement(); }},
  execCommand() {{ return true; }},
  body: createMockElement('body'),
}};

const logs = {{
  apiGetPaths: [],
  apiPostPaths: [],
  toastCalls: [],
}};

const context = {{
  console,
  document,
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  setTimeout,
  clearTimeout,
  toast: {{
    success(message) {{ logs.toastCalls.push(['success', String(message)]); }},
    error(message) {{ logs.toastCalls.push(['error', String(message)]); }},
    warning(message) {{ logs.toastCalls.push(['warning', String(message)]); }},
    info(message) {{ logs.toastCalls.push(['info', String(message)]); }},
  }},
  api: {{
    async get(path) {{
      logs.apiGetPaths.push(String(path));
      if (path === '/accounts?page=1&page_size=100&status=active') {{
        return {{ accounts: [{{ id: 101, email: 'alpha@example.com' }}] }};
      }}
      throw new Error(`unexpected GET: ${{path}}`);
    }},
    async post(path) {{
      logs.apiPostPaths.push(String(path));
      if (path === '/payment/generate-link') {{
        return {{ success: true, link: 'https://pay.example.com/session-1' }};
      }}
      if (path === '/payment/open-incognito') {{
        return {{ success: true }};
      }}
      throw new Error(`unexpected POST: ${{path}}`);
    }},
  }},
}};

context.global = context;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(paymentSource + `
;globalThis.__paymentTestExports = {{
  selectPlan,
  onCountryChange,
  generateLink,
  openIncognito,
  getSelectedPlan: () => selectedPlan,
  paymentElements,
}};`, context);

const exported = context.__paymentTestExports;

async function flush() {{
  await Promise.resolve();
  await Promise.resolve();
}}

async function bootstrap() {{
  getElement('country-select').value = 'SG';
  getElement('account-select').value = '';
  getElement('workspace-name').value = 'MyTeam';
  getElement('seat-quantity').value = '5';
  getElement('price-interval').value = 'month';
  if (typeof domListeners.DOMContentLoaded === 'function') {{
    await domListeners.DOMContentLoaded({{ preventDefault() {{}} }});
    await flush();
  }}
}}

async function runScenario() {{
  await bootstrap();

  switch (scenarioName) {{
    case 'event_binding_matrix': {{
      logs.apiPostPaths = [];
      getElement('plan-team').click();
      getElement('country-select').value = 'US';
      getElement('country-select').dispatchEvent('change');
      getElement('account-select').value = '101';
      getElement('generate-link-btn').click();
      await flush();
      getElement('open-incognito-btn').click();
      await flush();
      return {{
        selected_plan: exported.getSelectedPlan(),
        currency: getElement('currency-display').value,
        api_get_paths: logs.apiGetPaths.slice(),
        api_post_paths: logs.apiPostPaths.slice(),
      }};
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
