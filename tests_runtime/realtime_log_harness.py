from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE_JS = ROOT / "static" / "js" / "realtime_log_store.js"
CLIENT_JS = ROOT / "static" / "js" / "realtime_log_client.js"
CONSOLE_JS = ROOT / "static" / "js" / "realtime_log_console.js"
REGISTRATION_STREAM_JS = ROOT / "static" / "js" / "registration_stream.js"


def run_realtime_log_scenario(name: str) -> dict:
    store_source = STORE_JS.read_text(encoding="utf-8") if STORE_JS.exists() else ""
    client_source = CLIENT_JS.read_text(encoding="utf-8") if CLIENT_JS.exists() else ""
    console_source = CONSOLE_JS.read_text(encoding="utf-8") if CONSOLE_JS.exists() else ""
    registration_stream_source = REGISTRATION_STREAM_JS.read_text(encoding="utf-8") if REGISTRATION_STREAM_JS.exists() else ""

    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const storeSource = {json.dumps(store_source)};
const clientSource = {json.dumps(client_source)};
const consoleSource = {json.dumps(console_source)};
const registrationStreamSource = {json.dumps(registration_stream_source)};

function createClassList() {{
  const classes = new Set();
  return {{
    add(...tokens) {{ tokens.filter(Boolean).forEach((token) => classes.add(token)); }},
    remove(...tokens) {{ tokens.filter(Boolean).forEach((token) => classes.delete(token)); }},
    contains(token) {{ return classes.has(token); }},
    toggle(token, force) {{
      if (force === true) {{ classes.add(token); return true; }}
      if (force === false) {{ classes.delete(token); return false; }}
      if (classes.has(token)) {{ classes.delete(token); return false; }}
      classes.add(token); return true;
    }},
    toString() {{ return [...classes].join(' '); }},
  }};
}}

function createMockElement(id = '') {{
  const element = {{
    id,
    style: {{}},
    dataset: {{}},
    classList: createClassList(),
    _innerHTML: '',
    _textContent: '',
    scrollTop: 0,
    scrollHeight: 1200,
    clientHeight: 240,
    addEventListener() {{}},
    appendChild() {{}},
    querySelector() {{ return null; }},
    querySelectorAll() {{ return []; }},
  }};

  Object.defineProperty(element, 'innerHTML', {{
    get() {{ return this._innerHTML; }},
    set(value) {{
      this._innerHTML = String(value ?? '');
      this._textContent = this._innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    }},
  }});

  Object.defineProperty(element, 'textContent', {{
    get() {{ return this._textContent; }},
    set(value) {{
      this._textContent = String(value ?? '');
      this._innerHTML = this._textContent;
    }},
  }});

  return element;
}}

const clipboard = {{ copiedText: '' }};
const document = {{
  body: createMockElement('body'),
  createElement(id) {{ return createMockElement(id); }},
}};

const context = {{
  console,
  document,
  window: {{}},
  navigator: {{
    clipboard: {{
      writeText: async (text) => {{
        clipboard.copiedText = String(text ?? '');
      }},
    }},
  }},
  setTimeout,
  clearTimeout,
  Promise,
}};
context.window = context;
context.window.document = document;
context.window.navigator = context.navigator;

vm.createContext(context);
vm.runInContext(storeSource, context, {{ filename: 'realtime_log_store.js' }});
vm.runInContext(clientSource, context, {{ filename: 'realtime_log_client.js' }});
vm.runInContext(consoleSource, context, {{ filename: 'realtime_log_console.js' }});
vm.runInContext(registrationStreamSource, context, {{ filename: 'registration_stream.js' }});

function makeEntry(seq, level, message, time) {{
  return {{
    seq,
    stream: 'run:demo',
    timestamp: `2026-03-26T${{time}}+08:00`,
    display_time: time,
    level,
    message,
    raw: `2026-03-26 ${{time}}.000 [${{level}}] ${{message}}`,
    source: 'scheduler',
  }};
}}

async function main() {{
  const root = createMockElement('realtime-log-root');
  const controller = context.realtimeLogConsole.mountRealtimeLogConsole(root, {{ state: context.realtimeLogStore.createState() }});
  const client = context.realtimeLogClient.createStreamClient({{
    initialState: context.realtimeLogStore.createState(),
    onStateChange(nextState) {{
      controller.setState(nextState);
    }},
  }});

  if (scenarioName === 'snapshot_required_resync') {{
    client.applyHistoryChunk('2026-03-26 09:59:57.000 [INFO] history-line');
    const logsTail = Array.from({{ length: 500 }}, (_, index) =>
      makeEntry(
        index + 1,
        index === 499 ? 'ERROR' : 'INFO',
        index === 499 ? 'proxy fallback failed' : `line-${{index}}`,
        '10:00:00'
      )
    );

    client.dispatchEvent({{ kind: 'snapshot_required', stream: 'run:demo', payload: {{ reason: 'after_seq_expired' }} }});
    client.dispatchEvent({{ seq: 8, stream: 'run:demo', kind: 'log_appended', payload: {{ entry: makeEntry(8, 'WARN', 'stale-event', '09:59:58') }} }});
    client.dispatchEvent({{ seq: 9, stream: 'run:demo', kind: 'log_appended', payload: {{ entry: makeEntry(9, 'WARN', 'stale-event-2', '09:59:59') }} }});
    client.applySnapshot({{
      seq: 9,
      stream: 'run:demo',
      kind: 'snapshot',
      payload: {{
        run: {{ id: 9, status: 'running' }},
        run_progress: {{ step: 'sync' }},
        logs_tail: logsTail,
      }},
    }});

    const state = client.getState();
    const visibleEntries = controller.lastRender.visibleEntries;
    const levels = [...new Set(visibleEntries.map((entry) => String(entry.level)))]
    return {{
      cursor_after_snapshot: state.cursors['run:demo'] || 0,
      visible_levels: levels,
      last_rendered_text: visibleEntries.length ? `${{visibleEntries[visibleEntries.length - 1].display_time}} ${{visibleEntries[visibleEntries.length - 1].level}} ${{visibleEntries[visibleEntries.length - 1].message}}` : '',
      theme_error_class: root.innerHTML.includes('realtime-log-level-error') ? 'realtime-log-level-error' : '',
      live_window_size: Array.isArray(state.liveWindow) ? state.liveWindow.length : -1,
      history_chunk_merged: Array.isArray(state.historyPrefix) && state.historyPrefix.length === 1 && Array.isArray(state.logs) && state.logs.length === 501,
      resync_pending_replayed_in_order: client.getDiagnostics().replayedInOrder,
    }};
  }}

  if (scenarioName === 'search_and_level_filter') {{
    const initialState = context.realtimeLogStore.createState({{
      liveWindow: [
        makeEntry(1, 'INFO', 'proxy bootstrap ok', '10:00:00'),
        makeEntry(2, 'ERROR', 'proxy fallback failed', '10:00:01'),
        makeEntry(3, 'WARN', 'other warning', '10:00:02'),
      ],
    }});
    const comparisonEvent = {{
      seq: 4,
      stream: 'run:demo',
      kind: 'run_status_changed',
      payload: {{ status: 'running', plan_name: 'demo' }},
    }};
    const shimState = context.registrationStream.reduce(initialState, comparisonEvent);
    const sharedState = context.realtimeLogStore.reduceEvent(context.realtimeLogStore.createState(initialState), comparisonEvent);

    controller.setState(context.realtimeLogStore.createState({{
      liveWindow: [
        makeEntry(1, 'INFO', 'proxy bootstrap ok', '10:00:00'),
        makeEntry(2, 'ERROR', 'proxy fallback failed', '10:00:01'),
        makeEntry(3, 'WARN', 'other warning', '10:00:02'),
      ],
    }}));
    controller.setSearch('proxy fallback');
    controller.setLevelFilter('ERROR');
    return {{
      visible_messages: controller.lastRender.visibleEntries.map((entry) => entry.message),
      registration_shim_uses_shared_store: JSON.stringify(shimState) === JSON.stringify(sharedState),
    }};
  }}

  if (scenarioName === 'wrap_and_auto_scroll_toggle') {{
    controller.setState(context.realtimeLogStore.createState({{
      liveWindow: [
        makeEntry(1, 'INFO', 'first line', '10:00:00'),
        makeEntry(2, 'ERROR', 'second line', '10:00:01'),
      ],
    }}));
    controller.toggleAutoScroll(false);
    controller.rememberManualScroll(120);
    controller.toggleWrap(false);
    controller.setState(controller.state);
    return {{
      has_nowrap_class: root.classList.contains('realtime-log-console--nowrap'),
      auto_scroll_preserved_manual_position: root.scrollTop === 120,
    }};
  }}

  if (scenarioName === 'copy_and_clear_view') {{
    controller.setState(context.realtimeLogStore.createState({{
      liveWindow: [
        makeEntry(1, 'INFO', 'proxy bootstrap ok', '10:00:00'),
        makeEntry(2, 'ERROR', 'proxy fallback failed', '10:00:01'),
      ],
    }}));
    const copiedText = await controller.copyVisibleText();
    controller.clearView();
    return {{
      copied_text: clipboard.copiedText || copiedText,
      clear_keeps_store_entries: Array.isArray(controller.state.logs) && controller.state.logs.length === 2 && controller.lastRender.visibleEntries.length === 0,
    }};
  }}

  if (scenarioName === 'connection_empty_error_states') {{
    client.setConnectionStatus('reconnecting', {{ errorMessage: 'ws closed' }});
    controller.setState(client.getState());
    return {{
      connection_text: root.dataset.connectionText || '',
      empty_state_visible: root.dataset.emptyVisible === 'true',
      error_state_visible: root.dataset.errorVisible === 'true',
    }};
  }}

  throw new Error(`Unknown scenario: ${{scenarioName}}`);
}}

main()
  .then((result) => {{
    process.stdout.write(JSON.stringify(result));
  }})
  .catch((error) => {{
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
