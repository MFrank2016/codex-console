from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "js" / "workspace.js"


def run_workspace_js_scenario(name: str) -> dict:
    script_source = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scriptSource = {json.dumps(script_source)};

function createClassList(initial = []) {{
  const classes = new Set(initial);
  return {{
    add(token) {{ classes.add(String(token)); }},
    remove(token) {{ classes.delete(String(token)); }},
    contains(token) {{ return classes.has(String(token)); }},
    toggle(token, force) {{
      const normalized = String(token);
      if (force === undefined) {{
        if (classes.has(normalized)) {{
          classes.delete(normalized);
          return false;
        }}
        classes.add(normalized);
        return true;
      }}
      if (force) {{
        classes.add(normalized);
        return true;
      }}
      classes.delete(normalized);
      return false;
    }},
  }};
}}

function createMockButton(id) {{
  return {{
    id,
    textContent: '',
    title: '',
    _attrs: {{}},
    _listeners: {{}},
    setAttribute(name, value) {{
      this._attrs[String(name)] = String(value);
    }},
    addEventListener(type, handler) {{
      this._listeners[type] = handler;
    }},
    click() {{
      if (typeof this._listeners.click === 'function') {{
        this._listeners.click();
      }}
    }},
  }};
}}

const sidebarToggle = createMockButton('workspace-sidebar-toggle');
const themeToggle = createMockButton('workspace-theme-toggle');
const themeToggles = [themeToggle];
const domListeners = {{}};
const localStorageMap = new Map([['codex-console.workspace.sidebar', 'collapsed']]);

const document = {{
  body: {{ classList: createClassList() }},
  documentElement: {{
    _attrs: {{}},
    setAttribute(name, value) {{
      this._attrs[String(name)] = String(value);
    }},
  }},
  addEventListener(type, handler) {{
    domListeners[type] = handler;
  }},
  getElementById(id) {{
    if (id === 'workspace-sidebar-toggle') {{
      return sidebarToggle;
    }}
    if (id === 'workspace-theme-toggle') {{
      return themeToggle;
    }}
    return null;
  }},
  querySelectorAll(selector) {{
    if (selector === '.theme-toggle') {{
      return themeToggles;
    }}
    return [];
  }},
}};

const context = {{
  console,
  document,
  window: {{}},
  localStorage: {{
    getItem(key) {{
      return localStorageMap.has(key) ? localStorageMap.get(key) : null;
    }},
    setItem(key, value) {{
      localStorageMap.set(key, String(value));
    }},
  }},
}};

vm.createContext(context);
vm.runInContext(scriptSource, context);

function ensureFunction(name) {{
  if (typeof context[name] !== 'function') {{
    throw new Error(`missing function: ${{name}}`);
  }}
}}

async function main() {{
  if (scenarioName !== 'sidebar_toggle_flow') {{
    throw new Error(`unknown scenario: ${{scenarioName}}`);
  }}

  if (typeof domListeners.DOMContentLoaded !== 'function') {{
    throw new Error('missing DOMContentLoaded listener');
  }}

  ensureFunction('toggleWorkspaceSidebar');

  await domListeners.DOMContentLoaded();

  const result = {{
    after_restore_collapsed: document.body.classList.contains('workspace-sidebar-collapsed'),
  }};

  sidebarToggle.click();

  result.after_click_collapsed = document.body.classList.contains('workspace-sidebar-collapsed');
  result.stored_sidebar_value = localStorageMap.get('codex-console.workspace.sidebar');

  process.stdout.write(JSON.stringify(result));
}}

main().catch((error) => {{
  console.error(error);
  process.exitCode = 1;
}});
"""

    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}
