from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_JS = ROOT / "static" / "js" / "accounts.js"


def run_accounts_js_scenario(name: str) -> dict:
    accounts_source = ACCOUNTS_JS.read_text(encoding="utf-8") if ACCOUNTS_JS.exists() else ""
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const accountsSource = {json.dumps(accounts_source)};

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
  }};
}}

const elementsById = new Map();
const document = {{
  activeElement: null,
  body: null,
  getElementById(id) {{
    if (!elementsById.has(id)) {{
      const element = {{
        id,
        style: {{}},
        dataset: {{}},
        hidden: false,
        disabled: false,
        value: '',
        innerHTML: '',
        textContent: '',
        className: '',
        classList: createClassList(),
        _listeners: {{}},
        addEventListener(type, handler) {{ this._listeners[type] = handler; }},
        dispatchEvent(type, event = {{}}) {{
          if (this._listeners[type]) {{
            return this._listeners[type]({{ currentTarget: this, target: this, preventDefault() {{}}, ...event }});
          }}
          return undefined;
        }},
        focus() {{ document.activeElement = this; }},
        querySelector() {{ return null; }},
        querySelectorAll() {{ return []; }},
        setAttribute(name, value) {{ this[name] = String(value); }},
        removeAttribute(name) {{ delete this[name]; }},
      }};
      elementsById.set(id, element);
    }}
    return elementsById.get(id);
  }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  addEventListener() {{}},
  createElement() {{ return this.getElementById(`generated-${{elementsById.size + 1}}`); }},
}};
document.body = document.getElementById('body');

const context = {{
  console,
  document,
  window: {{ location: {{ protocol: 'http:', host: 'localhost' }} }},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  setTimeout,
  clearTimeout,
  theme: {{ toggle() {{}} }},
  debounce: (fn) => fn,
  delegate() {{}},
  escapeHtml(value) {{ return String(value ?? ''); }},
  copyToClipboard() {{}},
  format: {{ number(value) {{ return String(value ?? 0); }}, date(value) {{ return value ? String(value) : '-'; }} }},
  api: {{ async get() {{ return {{ total: 0, accounts: [] }}; }}, async post() {{ return {{ success: true }}; }}, async patch() {{ return {{ success: true }}; }}, async delete() {{ return {{ success: true }}; }} }},
  toast: {{ info() {{}}, success() {{}}, warning() {{}}, error() {{}} }},
  confirm: async () => true,
  fetch: async () => ({{ ok: true, json: async () => ({{}}), blob: async () => ({{}}), headers: {{ get() {{ return null; }} }} }}),
}};
context.global = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(
  accountsSource + `\n;globalThis.__accountsDrawerExports = {{\n  elements,\n  openAccountDrawer,\n  closeAccountDrawer,\n}};`,
  context,
);

const exported = context.__accountsDrawerExports;

function runScenario() {{
  if (scenarioName === 'drawer_focus_contract') {{
    const trigger = document.getElementById('drawer-trigger');
    const drawer = document.getElementById('accounts-detail-drawer');
    trigger.focus();
    exported.openAccountDrawer('<div>drawer body</div>', trigger);
    const focusMovedIntoDrawer = document.activeElement === drawer;
    drawer.dispatchEvent('keydown', {{ key: 'Escape' }});
    return {{
      focus_moved_into_drawer: focusMovedIntoDrawer,
      escape_closes_drawer: drawer.hidden === true,
      focus_returned_to_trigger: document.activeElement === trigger,
    }};
  }}
  throw new Error(`Unknown scenario: ${{scenarioName}}`);
}}

process.stdout.write(JSON.stringify(runScenario()));
"""
    completed = subprocess.run(["node", "-e", node_script], cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(
            f"Node harness failed for scenario {name!r}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}
