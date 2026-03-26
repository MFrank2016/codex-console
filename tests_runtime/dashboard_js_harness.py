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
const domListeners = {{}};
const document = {{
  getElementById(id) {{
    if (!elementsById.has(id)) {{
      elementsById.set(id, createMockElement(id));
    }}
    return elementsById.get(id);
  }},
  addEventListener(type, handler) {{
    domListeners[type] = handler;
  }},
}};

const logs = {{
  fetchPaths: [],
}};

async function flushPromises() {{
  return new Promise((resolve) => setImmediate(resolve));
}}

const context = {{
  console,
  document,
  window: {{}},
  setImmediate,
  fetch: async (url) => {{
    logs.fetchPaths.push(String(url));
    return {{
      ok: true,
      status: 200,
      async json() {{
        return sampleSummary();
      }},
    }};
  }},
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
      {{
        label: '危险链接',
        href: 'javascript:alert(1)',
        description: '不应被允许',
      }},
      {{
        label: '数据协议',
        href: 'data:text/html,<b>bad</b>',
        description: '不应被允许',
      }},
      {{
        label: '协议相对',
        href: '//evil.example/path',
        description: '不应被允许',
      }},
    ],
    recent_activity: [
      {{
        title: '<script>alert(1)</script>',
        status: 'completed',
        href: 'javascript:alert(1)',
        timestamp: '2026-03-25T08:00:00Z',
        description: '示例活动',
      }},
      {{
        title: '外部活动',
        status: 'running',
        href: 'https://example.com/activity',
        timestamp: '2026-03-25T09:00:00Z',
        description: '外部链接允许 https',
      }},
      {{
        title: '协议相对活动',
        status: 'running',
        href: '//evil.example/activity',
        timestamp: '2026-03-25T10:00:00Z',
        description: '不应被允许',
      }},
    ],
  }};
}}

function ensureFunction(name) {{
  if (typeof context[name] !== 'function') {{
    throw new Error(`missing function: ${{name}}`);
  }}
}}

async function main() {{
  const result = {{}};

  if (scenarioName === 'render_dashboard') {{
    const summary = sampleSummary();
    ensureFunction('renderDashboardHero');
    ensureFunction('renderRecentActivity');
    ensureFunction('renderQuickActions');
    result.metric_html = context.renderDashboardHero(summary);
    result.activity_html = context.renderRecentActivity(summary.recent_activity);
    result.quick_actions_html = context.renderQuickActions(summary.quick_links);
  }} else if (scenarioName === 'render_metric_card_with_invalid_tone') {{
    ensureFunction('renderMetricCard');
    result.html = context.renderMetricCard('注册任务', '12', '运行中 3', 'bad" data-evil="1');
  }} else if (scenarioName === 'render_error') {{
    ensureFunction('renderDashboardError');
    context.renderDashboardError(new Error('boom'));
    result.metric_html = document.getElementById('dashboard-metric-grid').innerHTML;
    result.activity_html = document.getElementById('dashboard-activity-feed').innerHTML;
    result.quick_actions_html = document.getElementById('dashboard-quick-actions').innerHTML;
  }} else if (scenarioName === 'safe_href_matrix') {{
    ensureFunction('safeHref');
    result.relative_ok = context.safeHref('/registration-workbench');
    result.https_ok = context.safeHref('https://example.com/activity');
    result.protocol_relative_rejected = context.safeHref('//evil.example/path');
    result.javascript_rejected = context.safeHref('javascript:alert(1)');
    result.data_rejected = context.safeHref('data:text/html,<b>bad</b>');
  }} else if (scenarioName === 'dom_content_loaded_flow') {{
    if (typeof domListeners.DOMContentLoaded !== 'function') {{
      throw new Error('missing DOMContentLoaded listener');
    }}

    // 触发真实主链路：DOMContentLoaded -> loadDashboardSummary -> mountDashboard
    await domListeners.DOMContentLoaded();
    await flushPromises();

    result.fetch_paths = logs.fetchPaths;
    result.metric_grid_html = document.getElementById('dashboard-metric-grid').innerHTML;
    result.activity_html = document.getElementById('dashboard-activity-feed').innerHTML;
    result.quick_actions_html = document.getElementById('dashboard-quick-actions').innerHTML;
  }} else {{
    throw new Error(`unknown scenario: ${{scenarioName}}`);
  }}

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
