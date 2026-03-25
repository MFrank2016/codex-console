from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "js" / "dashboard.js"


def run_dashboard_js_scenario(name: str) -> dict:
    script_source = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const scriptSource = {json.dumps(script_source)};

function createMockElement(id = '') {{
  return {{
    id,
    _innerHTML: '',
    addEventListener() {{}},
    get innerHTML() {{
      return this._innerHTML;
    }},
    set innerHTML(next) {{
      this._innerHTML = String(next ?? '');
    }},
  }};
}}

const elementsById = new Map();
const document = {{
  getElementById(id) {{
    if (!elementsById.has(id)) {{
      elementsById.set(id, createMockElement(id));
    }}
    return elementsById.get(id);
  }},
  addEventListener() {{
    // harness 不触发 DOMContentLoaded，避免触发网络请求
  }},
}};

const context = {{
  console,
  document,
  window: {{}},
}};

vm.createContext(context);
vm.runInContext(scriptSource, context);

function sampleSummary() {{
  return {{
    registration: {{
      total_tasks: 12,
      running: 3,
      failed: 1,
      pending: 8,
      success_rate: 91.2,
    }},
    accounts: {{
      total: 50,
      active: 40,
    }},
    scheduled: {{
      plans_total: 4,
      plans_enabled: 2,
      runs_today: 5,
      runs_running: 1,
      runs_failed: 0,
    }},
    quick_links: [
      {{
        label: '去注册工作台',
        href: '/registration-workbench',
        description: '创建/查看注册任务',
      }},
    ],
    recent_activity: [
      {{
        title: '<script>alert(1)</script>',
        status: 'completed',
        href: '/registration/tasks/task-001',
        timestamp: '2026-03-25T08:00:00Z',
        description: '示例活动',
      }},
    ],
  }};
}}

function ensureFunction(name) {{
  if (typeof context[name] !== 'function') {{
    throw new Error(`missing function: ${{name}}`);
  }}
}}

const result = {{}};

if (scenarioName === 'render_dashboard') {{
  const summary = sampleSummary();
  ensureFunction('renderDashboardHero');
  ensureFunction('renderRecentActivity');
  ensureFunction('renderQuickActions');
  result.hero_html = context.renderDashboardHero(summary);
  result.activity_html = context.renderRecentActivity(summary.recent_activity);
  result.quick_actions_html = context.renderQuickActions(summary.quick_links);
}} else {{
  throw new Error(`unknown scenario: ${{scenarioName}}`);
}}

process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}

