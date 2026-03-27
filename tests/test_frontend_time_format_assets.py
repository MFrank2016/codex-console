import os
import subprocess
from pathlib import Path


def test_utils_js_formats_naive_utc_datetimes_as_beijing_time():
    node_script = r"""
const fs = require('fs');
const vm = require('vm');

function createElement() {
  let text = '';
  let html = '';
  return {
    style: {},
    className: '',
    appendChild() {},
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    get textContent() { return text; },
    set textContent(next) {
      text = String(next ?? '');
      html = text;
    },
    get innerHTML() { return html; },
    set innerHTML(next) {
      html = String(next ?? '');
      text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    },
  };
}

const body = createElement();
body.appendChild = () => {};

const context = {
  console,
  window: {},
  document: {
    body,
    documentElement: { setAttribute() {} },
    createElement,
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
  },
  localStorage: {
    getItem() { return null; },
    setItem() {},
    removeItem() {},
  },
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  setTimeout,
  clearTimeout,
  URLSearchParams,
  AbortController,
};

vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/utils.js', 'utf8'), context, {
  filename: 'static/js/utils.js',
});

const format = context.window.format;
const naiveUtcRendered = format.date('2026-03-22T09:00:00');
const awareShanghaiRendered = format.date('2026-03-22T09:00:00+08:00');

if (!/17:00/.test(naiveUtcRendered)) {
  throw new Error('naive UTC datetime should render as Beijing time: ' + naiveUtcRendered);
}
if (!/09:00/.test(awareShanghaiRendered)) {
  throw new Error('aware Beijing datetime should keep Beijing wall clock: ' + awareShanghaiRendered);
}
"""

    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TZ": "UTC"},
    )

    assert completed.returncode == 0, completed.stderr


def test_utils_js_declares_beijing_time_zone_for_date_formatters():
    script = Path("static/js/utils.js").read_text(encoding="utf-8")
    assert "const SHANGHAI_TIME_ZONE = 'Asia/Shanghai';" in script
    assert "timeZone: SHANGHAI_TIME_ZONE" in script
