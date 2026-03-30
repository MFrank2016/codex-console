from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"


def run_settings_js_scenario(name: str) -> dict:
    settings_source = SETTINGS_JS.read_text(encoding="utf-8")
    node_script = rf"""
const vm = require('vm');

const scenarioName = {json.dumps(name)};
const settingsSource = {json.dumps(settings_source)};

function escapeHtml(value) {{
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

function createMockElement(id = '') {{
  const element = {{
    id,
    tagName: 'DIV',
    style: {{}},
    dataset: {{}},
    disabled: false,
    checked: false,
    indeterminate: false,
    value: '',
    _listeners: {{}},
    _proxyCheckboxes: [],
    _submitButton: null,
    _textContent: '',
    _innerHTML: '',
    classList: {{
      add() {{}},
      remove() {{}},
      contains() {{ return false; }},
    }},
    addEventListener(type, handler) {{
      this._listeners[type] = handler;
    }},
    dispatchEvent(type, event = {{}}) {{
      if (this._listeners[type]) {{
        return this._listeners[type](event);
      }}
      return undefined;
    }},
    querySelectorAll(selector) {{
      if (selector === '.proxy-checkbox[data-id]') {{
        return this._proxyCheckboxes;
      }}
      return [];
    }},
    querySelector(selector) {{
      if (selector === 'button[type="submit"]') {{
        return this._submitButton;
      }}
      return null;
    }},
    appendChild() {{}},
    removeChild() {{}},
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
      this._innerHTML = escapeHtml(this._textContent);
    }},
  }});

  Object.defineProperty(element, 'innerHTML', {{
    get() {{
      return this._innerHTML;
    }},
    set(value) {{
      this._innerHTML = String(value ?? '');
      if (this.id === 'proxies-table') {{
        const inputTags = [...this._innerHTML.matchAll(/<input[\s\S]*?>/g)].map(match => match[0]);
        this._proxyCheckboxes = inputTags
          .filter(tag => tag.includes('class="proxy-checkbox"'))
          .map(tag => {{
            const idMatch = tag.match(/data-id="(\d+)"/);
            const checkbox = createMockElement(`proxy-checkbox-${{idMatch ? idMatch[1] : 'unknown'}}`);
            checkbox.tagName = 'INPUT';
            checkbox.type = 'checkbox';
            checkbox.dataset.id = idMatch ? idMatch[1] : '';
            checkbox.checked = /\bchecked\b/.test(tag);
            return checkbox;
          }});
      }}
    }},
  }});

  if (id === 'proxy-batch-import-form') {{
    element._submitButton = createMockElement('proxy-batch-import-submit');
    element._submitButton.tagName = 'BUTTON';
    element._submitButton.type = 'submit';
  }}

  return element;
}}

const elementsById = new Map();
function getElement(id) {{
  if (!elementsById.has(id)) {{
    elementsById.set(id, createMockElement(id));
  }}
  return elementsById.get(id);
}}

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
  addEventListener() {{}},
  createElement() {{
    return createMockElement();
  }},
  body: createMockElement('body'),
}};

document.body.appendChild = () => {{}};
document.body.removeChild = () => {{}};

const logs = {{
  apiGets: [],
  apiPosts: [],
  apiPatches: [],
  apiDeletes: [],
  toasts: [],
}};

const apiGetResponses = {{}};
const apiGetErrors = {{}};

function cloneValue(value) {{
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}}

const context = {{
  console,
  URLSearchParams,
  document,
  window: {{ location: {{}}, URL: {{ createObjectURL() {{ return 'blob:test'; }}, revokeObjectURL() {{}} }} }},
  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
  setTimeout,
  clearTimeout,
  fetch: async () => ({{ ok: true, json: async () => ({{}}), blob: async () => ({{}}), headers: {{ get() {{ return null; }} }} }}),
  theme: {{ applyTheme() {{}}, toggle() {{}} }},
  toast: {{
    success(msg) {{ logs.toasts.push(['success', msg]); }},
    error(msg) {{ logs.toasts.push(['error', msg]); }},
    warning(msg) {{ logs.toasts.push(['warning', msg]); }},
    info(msg) {{ logs.toasts.push(['info', msg]); }},
  }},
  format: {{
    date(value) {{ return value ? `DATE:${{value}}` : '-'; }},
  }},
  getServiceTypeText(value) {{
    return String(value || '-');
  }},
  api: {{
    async get(path) {{
      logs.apiGets.push(path);
      if (Object.prototype.hasOwnProperty.call(apiGetErrors, path)) {{
        throw new Error(apiGetErrors[path]);
      }}
      if (Object.prototype.hasOwnProperty.call(apiGetResponses, path)) {{
        return cloneValue(apiGetResponses[path]);
      }}
      if (path.startsWith('/settings/proxies')) {{
        return {{ proxies: [] }};
      }}
      return {{}};
    }},
    async post(path, payload) {{
      logs.apiPosts.push([path, payload]);
      return {{ success: true }};
    }},
    async patch(path, payload) {{
      logs.apiPatches.push([path, payload]);
      return {{ success: true }};
    }},
    async delete(path) {{
      logs.apiDeletes.push(path);
      return {{ success: true }};
    }},
  }},
  confirm: async () => true,
}};

context.global = context;
context.globalThis = context;
context.window.getServiceTypeText = context.getServiceTypeText;

vm.createContext(context);
vm.runInContext(
  settingsSource + `\n;globalThis.__settingsTestExports = {{\n  buildProxyQueryString,\n  handleApplyProxyFilters,\n  updateProxySelectionUi,\n  renderProxyImportResultItem: typeof renderProxyImportResultItem === 'function' ? renderProxyImportResultItem : null,\n  renderProxyImportResultDetails: typeof renderProxyImportResultDetails === 'function' ? renderProxyImportResultDetails : null,\n  renderProxyImportResult,\n  renderProxies,\n  closeManagedServiceModal: typeof closeManagedServiceModal === 'function' ? closeManagedServiceModal : null,\n  closeSub2ApiServiceModal: typeof closeSub2ApiServiceModal === 'function' ? closeSub2ApiServiceModal : null,\n  loadManagedServiceTable: typeof loadManagedServiceTable === 'function' ? loadManagedServiceTable : null,\n  readManagedServiceSaveForm: typeof readManagedServiceSaveForm === 'function' ? readManagedServiceSaveForm : null,\n  runManagedServiceEdit: typeof runManagedServiceEdit === 'function' ? runManagedServiceEdit : null,\n  runManagedServiceSave: typeof runManagedServiceSave === 'function' ? runManagedServiceSave : null,\n  runManagedServiceFormTest: typeof runManagedServiceFormTest === 'function' ? runManagedServiceFormTest : null,\n  runManagedServiceConnectionTest: typeof runManagedServiceConnectionTest === 'function' ? runManagedServiceConnectionTest : null,\n  runManagedServiceSavedTest: typeof runManagedServiceSavedTest === 'function' ? runManagedServiceSavedTest : null,\n  loadSettings: typeof loadSettings === 'function' ? loadSettings : null,\n  loadTmServices: typeof loadTmServices === 'function' ? loadTmServices : null,\n  loadCpaServices: typeof loadCpaServices === 'function' ? loadCpaServices : null,\n  loadSub2ApiServices: typeof loadSub2ApiServices === 'function' ? loadSub2ApiServices : null,\n  handleSaveDynamicProxy: typeof handleSaveDynamicProxy === 'function' ? handleSaveDynamicProxy : null,\n  parseDynamicProxyCurlInput: typeof parseDynamicProxyCurlInput === 'function' ? parseDynamicProxyCurlInput : null,\n  buildDynamicProxyPayload: typeof buildDynamicProxyPayload === 'function' ? buildDynamicProxyPayload : null,\n  normalizeEmailSuffixInput: typeof normalizeEmailSuffixInput === 'function' ? normalizeEmailSuffixInput : null,
  renderEmailServices: typeof renderEmailServices === 'function' ? renderEmailServices : null,
  renderEmailServiceRow: typeof renderEmailServiceRow === 'function' ? renderEmailServiceRow : null,
  renderEmailServicesEmptyState: typeof renderEmailServicesEmptyState === 'function' ? renderEmailServicesEmptyState : null,
  renderEmailServicesErrorState: typeof renderEmailServicesErrorState === 'function' ? renderEmailServicesErrorState : null,
  renderEmailSuffixBlacklistRow: typeof renderEmailSuffixBlacklistRow === 'function' ? renderEmailSuffixBlacklistRow : null,
  renderProxyRow: typeof renderProxyRow === 'function' ? renderProxyRow : null,
  renderTmServicesTable: typeof renderTmServicesTable === 'function' ? renderTmServicesTable : null,
  renderCpaServicesTable: typeof renderCpaServicesTable === 'function' ? renderCpaServicesTable : null,
  openCpaServiceModal: typeof openCpaServiceModal === 'function' ? openCpaServiceModal : null,
  renderSub2ApiServices: typeof renderSub2ApiServices === 'function' ? renderSub2ApiServices : null,
  openSub2ApiServiceModal: typeof openSub2ApiServiceModal === 'function' ? openSub2ApiServiceModal : null,
  renderEmailSuffixBlacklist: typeof renderEmailSuffixBlacklist === 'function' ? renderEmailSuffixBlacklist : null,
  handleSaveEmailSuffixBlacklist: typeof handleSaveEmailSuffixBlacklist === 'function' ? handleSaveEmailSuffixBlacklist : null,
  handleSettingsDelegatedTableClick: typeof handleSettingsDelegatedTableClick === 'function' ? handleSettingsDelegatedTableClick : null,
  elements,
  getProxyFilters: () => ({{ ...proxyFilters }}),\n  getSelectedProxyIds: () => Array.from(selectedProxyIds).sort((a, b) => a - b),\n  resetProxyState: () => {{\n    Object.assign(proxyFilters, getDefaultProxyFilters());\n    selectedProxyIds = new Set();\n  }},\n}};`,
  context,
);

const exported = context.__settingsTestExports;

function snapshotSelectionState() {{
  const selectAll = getElement('select-all-proxies');
  const batchDelete = getElement('batch-delete-proxies-btn');
  return {{
    select_all_disabled: !!selectAll.disabled,
    select_all_checked: !!selectAll.checked,
    select_all_indeterminate: !!selectAll.indeterminate,
    batch_delete_disabled: !!batchDelete.disabled,
    batch_delete_text: batchDelete.textContent,
  }};
}}

async function runScenario() {{
  exported.resetProxyState();

  switch (scenarioName) {{
    case 'apply_proxy_filters': {{
      getElement('proxy-filter-keyword').value = '  us-west  ';
      getElement('proxy-filter-type').value = 'http';
      getElement('proxy-filter-enabled').value = 'true';
      getElement('proxy-filter-is-default').value = 'false';
      getElement('proxy-filter-location').value = ' Seattle ';

      await exported.handleApplyProxyFilters({{ preventDefault() {{}} }});
      return {{
        api_path: logs.apiGets.at(-1),
        filters: exported.getProxyFilters(),
      }};
    }}
    case 'proxy_selection_ui': {{
      exported.renderProxies([]);
      const emptyState = snapshotSelectionState();

      exported.renderProxies([
        {{ id: 1, name: '代理-001', type: 'http', host: '1.1.1.1', port: 8080, country: '美国', city: '西雅图', is_default: false, enabled: true, last_used: '2026-03-22T10:00:00', username: null }},
        {{ id: 2, name: '代理-002', type: 'socks5', host: '2.2.2.2', port: 1080, country: '', city: '', is_default: true, enabled: false, last_used: null, username: 'alice' }},
      ]);
      const afterRender = snapshotSelectionState();

      const checkboxes = getElement('proxies-table').querySelectorAll('.proxy-checkbox[data-id]');
      checkboxes[0].checked = true;
      checkboxes[0].dispatchEvent('change', {{ target: checkboxes[0] }});
      const afterOneSelected = {{
        ...snapshotSelectionState(),
        selected_ids: exported.getSelectedProxyIds(),
      }};

      checkboxes[1].checked = true;
      checkboxes[1].dispatchEvent('change', {{ target: checkboxes[1] }});
      const afterAllSelected = {{
        ...snapshotSelectionState(),
        selected_ids: exported.getSelectedProxyIds(),
      }};

      return {{ empty_state: emptyState, after_render: afterRender, after_one_selected: afterOneSelected, after_all_selected: afterAllSelected }};
    }}
    case 'proxy_import_result': {{
      exported.renderProxyImportResult({{
        success: 1,
        skipped: 1,
        failed: 1,
        results: [
          {{ line_no: 1, status: 'success', proxy: {{ name: '美国-西雅图-001', host: '1.1.1.1', port: 8080 }} }},
          {{ line_no: 2, status: 'skipped', reason: 'duplicate' }},
          {{ line_no: 3, status: 'failed', reason: 'invalid format' }},
        ],
      }});
      const importResult = getElement('proxy-import-result');
      return {{
        display: importResult.style.display,
        html: importResult.innerHTML,
      }};
    }}
    case 'render_proxy_import_result_item': {{
      if (typeof exported.renderProxyImportResultItem !== 'function') {{
        throw new Error('renderProxyImportResultItem is not implemented');
      }}
      return {{
        html: exported.renderProxyImportResultItem({{
          line_no: 3,
          status: 'success',
          proxy: {{ name: '美国-西雅图-003', host: '3.3.3.3', port: 8080 }},
        }}),
      }};
    }}
    case 'render_proxy_import_result_details': {{
      if (typeof exported.renderProxyImportResultDetails !== 'function') {{
        throw new Error('renderProxyImportResultDetails is not implemented');
      }}
      return {{
        html: exported.renderProxyImportResultDetails([
          {{ line_no: 4, status: 'failed', reason: 'timeout' }},
        ]),
      }};
    }}
    case 'render_email_service_row_helper': {{
      if (typeof exported.renderEmailServiceRow !== 'function') {{
        throw new Error('renderEmailServiceRow is not implemented');
      }}
      return {{
        html: exported.renderEmailServiceRow({{
          id: 17,
          name: 'Service-17',
          service_type: 'temp_mail',
          enabled: true,
          priority: 2,
          last_used: '2026-03-29T09:00:00Z',
        }}),
      }};
    }}
    case 'render_email_services_empty_state_helper': {{
      if (typeof exported.renderEmailServicesEmptyState !== 'function') {{
        throw new Error('renderEmailServicesEmptyState is not implemented');
      }}
      return {{
        html: exported.renderEmailServicesEmptyState(),
      }};
    }}
    case 'render_email_services_error_state_helper': {{
      if (typeof exported.renderEmailServicesErrorState !== 'function') {{
        throw new Error('renderEmailServicesErrorState is not implemented');
      }}
      return {{
        html: exported.renderEmailServicesErrorState(),
      }};
    }}
    case 'managed_service_connection_test_helper_saved': {{
      if (typeof exported.runManagedServiceConnectionTest !== 'function') {{
        throw new Error('runManagedServiceConnectionTest is not implemented');
      }}
      const button = getElement('managed-service-test-helper-button-saved');
      button.disabled = false;
      button.textContent = '🔌 测试连接';
      await exported.runManagedServiceConnectionTest({{
        id: '12',
        secretValue: '',
        button,
        idleText: '🔌 测试连接',
        savedTestPath: '/tm-services/12/test',
        connectionPath: '/tm-services/test-connection',
        connectionPayload: {{ api_url: 'https://tm.example.com', api_key: 'ignored' }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        api_post_payloads: logs.apiPosts.map(([, payload]) => payload),
        button_disabled: !!button.disabled,
        button_text: button.textContent,
      }};
    }}
    case 'managed_service_connection_test_helper_new': {{
      if (typeof exported.runManagedServiceConnectionTest !== 'function') {{
        throw new Error('runManagedServiceConnectionTest is not implemented');
      }}
      const button = getElement('managed-service-test-helper-button-new');
      button.disabled = false;
      button.textContent = '🔌 测试连接';
      await exported.runManagedServiceConnectionTest({{
        id: '',
        secretValue: 'secret-123',
        button,
        idleText: '🔌 测试连接',
        savedTestPath: '/tm-services/12/test',
        connectionPath: '/tm-services/test-connection',
        connectionPayload: {{ api_url: 'https://tm.example.com', api_key: 'secret-123' }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        api_post_payloads: logs.apiPosts.map(([, payload]) => payload),
        button_disabled: !!button.disabled,
        button_text: button.textContent,
      }};
    }}
    case 'managed_service_saved_test_helper': {{
      if (typeof exported.runManagedServiceSavedTest !== 'function') {{
        throw new Error('runManagedServiceSavedTest is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.toasts.length = 0;
      const originalPost = context.api.post;
      context.api.post = async (path, payload) => {{
        logs.apiPosts.push([path, payload]);
        return {{ success: true, message: '连接正常' }};
      }};
      try {{
        await exported.runManagedServiceSavedTest('/tm-services/15/test');
      }} finally {{
        context.api.post = originalPost;
      }}
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        success_toasts: logs.toasts
          .filter(([level]) => level === 'success')
          .map(([, message]) => message),
      }};
    }}
    case 'managed_service_form_test_helper_requires_secret': {{
      if (typeof exported.runManagedServiceFormTest !== 'function') {{
        throw new Error('runManagedServiceFormTest is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.toasts.length = 0;
      getElement('cpa-service-id').value = '';
      getElement('cpa-service-url').value = 'https://cpa.example.com';
      getElement('cpa-service-token').value = '';
      const button = getElement('managed-service-form-helper-button-requires-secret');
      button.disabled = false;
      button.textContent = '🔌 测试连接';
      await exported.runManagedServiceFormTest({{
        idFieldId: 'cpa-service-id',
        urlFieldId: 'cpa-service-url',
        secretFieldId: 'cpa-service-token',
        secretLabel: 'API Token',
        button,
        idleText: '🔌 测试连接',
        buildSavedTestPath: (id) => `/cpa-services/${{id}}/test`,
        connectionPath: '/cpa-services/test-connection',
        buildConnectionPayload: ({{ apiUrl, secretValue }}) => ({{ api_url: apiUrl, api_token: secretValue }}),
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        error_toasts: logs.toasts
          .filter(([level]) => level === 'error')
          .map(([, message]) => message),
      }};
    }}
    case 'managed_service_form_test_helper_new_connection': {{
      if (typeof exported.runManagedServiceFormTest !== 'function') {{
        throw new Error('runManagedServiceFormTest is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.toasts.length = 0;
      getElement('cpa-service-id').value = '';
      getElement('cpa-service-url').value = 'https://cpa.example.com';
      getElement('cpa-service-token').value = 'token-88';
      const button = getElement('managed-service-form-helper-button-new-connection');
      button.disabled = false;
      button.textContent = '🔌 测试连接';
      await exported.runManagedServiceFormTest({{
        idFieldId: 'cpa-service-id',
        urlFieldId: 'cpa-service-url',
        secretFieldId: 'cpa-service-token',
        secretLabel: 'API Token',
        button,
        idleText: '🔌 测试连接',
        buildSavedTestPath: (id) => `/cpa-services/${{id}}/test`,
        connectionPath: '/cpa-services/test-connection',
        buildConnectionPayload: ({{ apiUrl, secretValue }}) => ({{ api_url: apiUrl, api_token: secretValue }}),
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        api_post_payloads: logs.apiPosts.map(([, payload]) => payload),
        button_disabled: !!button.disabled,
        button_text: button.textContent,
      }};
    }}
    case 'managed_service_form_test_helper_existing_saved': {{
      if (typeof exported.runManagedServiceFormTest !== 'function') {{
        throw new Error('runManagedServiceFormTest is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.toasts.length = 0;
      getElement('tm-service-id').value = '88';
      getElement('tm-service-url').value = 'https://tm.example.com';
      getElement('tm-service-key').value = '';
      const button = getElement('managed-service-form-helper-button-existing-saved');
      button.disabled = false;
      button.textContent = '🔌 测试连接';
      await exported.runManagedServiceFormTest({{
        idFieldId: 'tm-service-id',
        urlFieldId: 'tm-service-url',
        secretFieldId: 'tm-service-key',
        secretLabel: 'API Key',
        button,
        idleText: '🔌 测试连接',
        buildSavedTestPath: (id) => `/tm-services/${{id}}/test`,
        connectionPath: '/tm-services/test-connection',
        buildConnectionPayload: ({{ apiUrl, secretValue }}) => ({{ api_url: apiUrl, api_key: secretValue }}),
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        button_disabled: !!button.disabled,
        button_text: button.textContent,
      }};
    }}
    case 'managed_service_load_helper_success': {{
      if (typeof exported.loadManagedServiceTable !== 'function') {{
        throw new Error('loadManagedServiceTable is not implemented');
      }}
      logs.apiGets.length = 0;
      let renderedItems = null;
      const originalGet = context.api.get;
      context.api.get = async (path) => {{
        logs.apiGets.push(path);
        return [
          {{
            id: 51,
            name: 'TM-51',
            api_url: 'https://tm-51.example.com',
            enabled: true,
            priority: 5,
          }},
        ];
      }};
      try {{
        await exported.loadManagedServiceTable({{
          tableElement: getElement('managed-service-load-helper-table'),
          listPath: '/tm-services',
          renderTable: (items) => {{
            renderedItems = items;
          }},
        }});
      }} finally {{
        context.api.get = originalGet;
      }}
      return {{
        api_get_paths: logs.apiGets,
        rendered_items: renderedItems,
      }};
    }}
    case 'managed_service_load_helper_error': {{
      if (typeof exported.loadManagedServiceTable !== 'function') {{
        throw new Error('loadManagedServiceTable is not implemented');
      }}
      logs.apiGets.length = 0;
      const table = getElement('managed-service-load-helper-error-table');
      const originalGet = context.api.get;
      context.api.get = async (path) => {{
        logs.apiGets.push(path);
        throw new Error('service unavailable');
      }};
      try {{
        await exported.loadManagedServiceTable({{
          tableElement: table,
          listPath: '/sub2api-services',
          renderTable: () => {{}},
        }});
      }} finally {{
        context.api.get = originalGet;
      }}
      return {{
        api_get_paths: logs.apiGets,
        html: table.innerHTML,
      }};
    }}
    case 'managed_service_save_form_helper_requires_name_url': {{
      if (typeof exported.readManagedServiceSaveForm !== 'function') {{
        throw new Error('readManagedServiceSaveForm is not implemented');
      }}
      logs.toasts.length = 0;
      getElement('tm-service-id').value = '';
      getElement('tm-service-name').value = '   ';
      getElement('tm-service-url').value = '   ';
      getElement('tm-service-key').value = ' secret ';
      getElement('tm-service-priority').value = '2';
      getElement('tm-service-enabled').checked = true;
      const result = exported.readManagedServiceSaveForm({{
        idFieldId: 'tm-service-id',
        nameFieldId: 'tm-service-name',
        urlFieldId: 'tm-service-url',
        secretFieldId: 'tm-service-key',
        priorityFieldId: 'tm-service-priority',
        enabledFieldId: 'tm-service-enabled',
        requireNameAndUrl: true,
        secretRequiredMessage: '新增服务时 API Key 不能为空',
      }});
      return {{
        result,
        error_toasts: logs.toasts
          .filter(([level]) => level === 'error')
          .map(([, message]) => message),
      }};
    }}
    case 'managed_service_save_form_helper_success': {{
      if (typeof exported.readManagedServiceSaveForm !== 'function') {{
        throw new Error('readManagedServiceSaveForm is not implemented');
      }}
      logs.toasts.length = 0;
      getElement('tm-service-id').value = '41';
      getElement('tm-service-name').value = '  TM-41  ';
      getElement('tm-service-url').value = '  https://tm-41.example.com  ';
      getElement('tm-service-key').value = '   ';
      getElement('tm-service-priority').value = '7';
      getElement('tm-service-enabled').checked = false;
      return {{
        result: exported.readManagedServiceSaveForm({{
          idFieldId: 'tm-service-id',
          nameFieldId: 'tm-service-name',
          urlFieldId: 'tm-service-url',
          secretFieldId: 'tm-service-key',
          priorityFieldId: 'tm-service-priority',
          enabledFieldId: 'tm-service-enabled',
          requireNameAndUrl: true,
          secretRequiredMessage: '新增服务时 API Key 不能为空',
        }}),
      }};
    }}
    case 'managed_service_save_form_helper_skip_name_url': {{
      if (typeof exported.readManagedServiceSaveForm !== 'function') {{
        throw new Error('readManagedServiceSaveForm is not implemented');
      }}
      logs.toasts.length = 0;
      getElement('sub2api-service-id').value = '';
      getElement('sub2api-service-name').value = '';
      getElement('sub2api-service-url').value = '';
      getElement('sub2api-service-key').value = 'key-51';
      getElement('sub2api-service-priority').value = '0';
      getElement('sub2api-service-enabled').checked = true;
      return {{
        result: exported.readManagedServiceSaveForm({{
          idFieldId: 'sub2api-service-id',
          nameFieldId: 'sub2api-service-name',
          urlFieldId: 'sub2api-service-url',
          secretFieldId: 'sub2api-service-key',
          priorityFieldId: 'sub2api-service-priority',
          enabledFieldId: 'sub2api-service-enabled',
          requireNameAndUrl: false,
          secretRequiredMessage: '请填写 API Key',
        }}),
      }};
    }}
    case 'managed_service_close_helper': {{
      if (typeof exported.closeManagedServiceModal !== 'function') {{
        throw new Error('closeManagedServiceModal is not implemented');
      }}
      let removeCalls = 0;
      let resetCalls = 0;
      let afterCloseCalls = 0;
      const modal = getElement('managed-service-close-helper-modal');
      modal.classList.remove = (token) => {{
        if (token === 'active') removeCalls += 1;
      }};
      const form = getElement('managed-service-close-helper-form');
      form.reset = () => {{
        resetCalls += 1;
      }};
      exported.closeManagedServiceModal({{
        modalElement: modal,
        formElement: form,
        afterClose: () => {{
          afterCloseCalls += 1;
        }},
      }});
      return {{
        remove_calls: removeCalls,
        reset_calls: resetCalls,
        after_close_calls: afterCloseCalls,
      }};
    }}
    case 'sub2api_close_modal': {{
      if (typeof exported.closeSub2ApiServiceModal !== 'function') {{
        throw new Error('closeSub2ApiServiceModal is not implemented');
      }}
      let removeCalls = 0;
      let resetCalls = 0;
      const modal = getElement('sub2api-service-edit-modal');
      modal.classList.remove = (token) => {{
        if (token === 'active') removeCalls += 1;
      }};
      const form = getElement('sub2api-service-form');
      form.reset = () => {{
        resetCalls += 1;
      }};
      exported.closeSub2ApiServiceModal();
      return {{
        remove_calls: removeCalls,
        reset_calls: resetCalls,
      }};
    }}
    case 'sub2api_modal_add_mode': {{
      if (typeof exported.openSub2ApiServiceModal !== 'function') {{
        throw new Error('openSub2ApiServiceModal is not implemented');
      }}
      getElement('sub2api-service-id').value = '77';
      getElement('sub2api-service-name').value = 'stale-name';
      getElement('sub2api-service-url').value = 'https://stale.example.com';
      getElement('sub2api-service-key').value = 'stale-key';
      getElement('sub2api-service-key').placeholder = 'stale-placeholder';
      getElement('sub2api-service-priority').value = 9;
      getElement('sub2api-service-enabled').checked = false;

      exported.openSub2ApiServiceModal(null);

      return {{
        id_value: getElement('sub2api-service-id').value,
        name_value: getElement('sub2api-service-name').value,
        url_value: getElement('sub2api-service-url').value,
        key_value: getElement('sub2api-service-key').value,
        key_placeholder: getElement('sub2api-service-key').placeholder,
        priority_value: getElement('sub2api-service-priority').value,
        enabled_checked: !!getElement('sub2api-service-enabled').checked,
        title_text: getElement('sub2api-service-modal-title').textContent,
      }};
    }}
    case 'proxy_row_actions': {{
      exported.renderProxies([
        {{ id: 7, name: '代理-007', type: 'http', host: '7.7.7.7', port: 8080, country: '美国', city: '西雅图', is_default: false, enabled: true, last_used: '2026-03-22T10:00:00', username: 'bob' }},
      ]);
      return {{ html: getElement('proxies-table').innerHTML }};
    }}
    case 'delegated_proxy_edit': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ proxyAction: 'edit', proxyId: '7' }},
          closest(selector) {{
            return selector === '[data-proxy-action][data-proxy-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_get_paths: logs.apiGets,
      }};
    }}
    case 'delegated_proxy_test': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ proxyAction: 'test', proxyId: '7' }},
          closest(selector) {{
            if (selector === '[data-proxy-action][data-proxy-id]') return this;
            if (selector === '.dropdown-menu') return {{ classList: {{ remove() {{}} }} }};
            return null;
          }},
        }},
        preventDefault() {{}},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
      }};
    }}
    case 'delegated_proxy_toggle': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ proxyAction: 'toggle', proxyId: '7', nextEnabled: 'false' }},
          closest(selector) {{
            if (selector === '[data-proxy-action][data-proxy-id]') return this;
            if (selector === '.dropdown-menu') return {{ classList: {{ remove() {{}} }} }};
            return null;
          }},
        }},
        preventDefault() {{}},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
      }};
    }}
    case 'delegated_proxy_set_default': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ proxyAction: 'set-default', proxyId: '7' }},
          closest(selector) {{
            if (selector === '[data-proxy-action][data-proxy-id]') return this;
            if (selector === '.dropdown-menu') return {{ classList: {{ remove() {{}} }} }};
            return null;
          }},
        }},
        preventDefault() {{}},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
      }};
    }}
    case 'delegated_proxy_delete': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ proxyAction: 'delete', proxyId: '7' }},
          closest(selector) {{
            return selector === '[data-proxy-action][data-proxy-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_delete_paths: logs.apiDeletes,
      }};
    }}
    case 'delegated_proxy_toggle_more': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      let active = false;
      const menu = {{
        classList: {{
          contains() {{ return active; }},
          add(token) {{ if (token === 'active') active = true; }},
          remove(token) {{ if (token === 'active') active = false; }},
        }},
      }};
      const button = {{
        dataset: {{ proxyAction: 'toggle-more', proxyId: '7' }},
        nextElementSibling: menu,
        closest(selector) {{
          return selector === '[data-proxy-action][data-proxy-id]' ? this : null;
        }},
      }};
      await exported.handleSettingsDelegatedTableClick({{
        target: button,
        stopPropagation() {{}},
      }});
      return {{
        menu_active: active,
      }};
    }}
    case 'parse_dynamic_proxy_curl': {{
      getElement('dynamic-proxy-curl-input').value = `curl -X POST 'https://proxy.example.com/fetch' -H 'Authorization: Bearer token-123' -H 'Content-Type: application/json' --data '{{"region":"us","count":5}}'`;
      if (typeof exported.parseDynamicProxyCurlInput !== 'function') {{
        throw new Error('parseDynamicProxyCurlInput is not implemented');
      }}
      exported.parseDynamicProxyCurlInput();
      return {{
        request_method: getElement('dynamic-proxy-request-method').value,
        request_url: getElement('dynamic-proxy-request-url').value,
        request_headers: getElement('dynamic-proxy-request-headers').value,
        request_body: getElement('dynamic-proxy-request-body').value,
      }};
    }}
    case 'build_dynamic_proxy_payload': {{
      getElement('dynamic-proxy-enabled').checked = true;
      getElement('dynamic-proxy-api-url').value = 'https://api.example.com/get_proxy';
      getElement('dynamic-proxy-api-key').value = '';
      getElement('dynamic-proxy-api-key-header').value = 'X-API-Key';
      getElement('dynamic-proxy-result-field').value = 'data';
      getElement('dynamic-proxy-request-method').value = 'POST';
      getElement('dynamic-proxy-request-url').value = 'https://proxy.example.com/fetch';
      getElement('dynamic-proxy-request-headers').value = '{{"Authorization":"Bearer token-123"}}';
      getElement('dynamic-proxy-request-body').value = '{{"region":"us"}}';
      getElement('dynamic-proxy-response-item-mode').value = 'object_list';
      getElement('dynamic-proxy-field-map-proxy-url').value = 'proxy';
      getElement('dynamic-proxy-field-map-username').value = 'auth.username';
      getElement('dynamic-proxy-field-map-password').value = 'auth.password';
      getElement('dynamic-proxy-single-registration-allocation-strategy').value = 'round_robin';
      getElement('dynamic-proxy-batch-registration-allocation-strategy').value = 'exclusive';
      getElement('dynamic-proxy-unlimited-registration-allocation-strategy').value = 'sticky';
      getElement('dynamic-proxy-outlook-batch-allocation-strategy').value = 'exclusive';
      getElement('dynamic-proxy-generic-single-allocation-strategy').value = 'round_robin';
      if (typeof exported.buildDynamicProxyPayload !== 'function') {{
        throw new Error('buildDynamicProxyPayload is not implemented');
      }}
      return exported.buildDynamicProxyPayload();
    }}
    case 'load_and_save_dynamic_proxy_settings': {{
      apiGetResponses['/settings'] = {{
        proxy: {{
          dynamic_enabled: true,
          dynamic_api_url: 'https://api.example.com/get_proxy',
          dynamic_api_key_header: 'X-API-Key',
          dynamic_result_field: 'data',
        }},
        registration: {{}},
        email_code: {{}},
        webui: {{}},
      }};
      apiGetResponses['/settings/proxy/dynamic'] = {{
        enabled: true,
        api_url: 'https://api.example.com/get_proxy',
        api_key_header: 'X-API-Key',
        result_field: 'data',
        request_method: 'POST',
        request_url: 'https://proxy.example.com/fetch',
        request_headers_template: {{ Authorization: 'Bearer token-123' }},
        request_body_template: {{ region: 'us' }},
        response_item_mode: 'object_list',
        response_field_mapping: {{ proxy_url: 'proxy' }},
        task_defaults: {{
          batch_registration: {{
            allocation_strategy: 'exclusive',
          }},
        }},
      }};
      apiGetResponses['/settings/outlook'] = {{
        default_client_id: '',
      }};
      if (typeof exported.loadSettings !== 'function') {{
        throw new Error('loadSettings is not implemented');
      }}
      if (typeof exported.handleSaveDynamicProxy !== 'function') {{
        throw new Error('handleSaveDynamicProxy is not implemented');
      }}
      await exported.loadSettings();
      const afterLoad = {{
        api_url: getElement('dynamic-proxy-api-url').value,
        request_url: getElement('dynamic-proxy-request-url').value,
        request_method: getElement('dynamic-proxy-request-method').value,
        response_item_mode: getElement('dynamic-proxy-response-item-mode').value,
        batch_registration_allocation_strategy: getElement('dynamic-proxy-batch-registration-allocation-strategy').value,
      }};
      await exported.handleSaveDynamicProxy({{ preventDefault() {{}} }});
      return {{
        api_gets: logs.apiGets,
        after_load: afterLoad,
        saved_payload: logs.apiPosts.at(-1)?.[1] || null,
      }};
    }}
    case 'load_dynamic_proxy_settings_failure_blocks_save': {{
      apiGetResponses['/settings'] = {{
        proxy: {{
          dynamic_enabled: true,
          dynamic_api_url: 'https://api.example.com/get_proxy',
          dynamic_api_key_header: 'X-API-Key',
          dynamic_result_field: 'data',
        }},
        registration: {{}},
        email_code: {{}},
        webui: {{}},
      }};
      apiGetErrors['/settings/proxy/dynamic'] = 'dynamic proxy settings unavailable';
      apiGetResponses['/settings/outlook'] = {{
        default_client_id: '',
      }};
      if (typeof exported.loadSettings !== 'function') {{
        throw new Error('loadSettings is not implemented');
      }}
      if (typeof exported.handleSaveDynamicProxy !== 'function') {{
        throw new Error('handleSaveDynamicProxy is not implemented');
      }}
      await exported.loadSettings();
      await exported.handleSaveDynamicProxy({{ preventDefault() {{}} }});
      return {{
        api_gets: logs.apiGets,
        save_post_attempted: logs.apiPosts.some(([path]) => path === '/settings/proxy/dynamic'),
        error_toasts: logs.toasts
          .filter(([level]) => level === 'error')
          .map(([, message]) => message),
      }};
    }}
    case 'save_email_suffix_blacklist': {{
      if (typeof exported.handleSaveEmailSuffixBlacklist !== 'function') {{
        throw new Error('handleSaveEmailSuffixBlacklist is not implemented');
      }}
      getElement('email-suffix-blacklist-id').value = '';
      getElement('email-suffix-blacklist-suffix').value = '@BadMail.COM';
      getElement('email-suffix-blacklist-enabled').checked = true;
      getElement('email-suffix-blacklist-reason').value = '临时封禁';
      await exported.handleSaveEmailSuffixBlacklist({{ preventDefault() {{}} }});
      const post = logs.apiPosts.at(-1) || [null, null];
      return {{
        post_path: post[0],
        payload: post[1],
      }};
    }}
    case 'render_email_suffix_blacklist_rows': {{
      if (typeof exported.renderEmailSuffixBlacklist !== 'function') {{
        throw new Error('renderEmailSuffixBlacklist is not implemented');
      }}
      exported.renderEmailSuffixBlacklist([
        {{ id: 5, suffix: 'badmail.com', enabled: true, reason: '高风险域名' }},
      ]);
      return {{
        html: getElement('email-suffix-blacklist-table').innerHTML,
      }};
    }}
    case 'render_email_service_rows': {{
      if (typeof exported.renderEmailServices !== 'function') {{
        throw new Error('renderEmailServices is not implemented');
      }}
      exported.renderEmailServices([
        {{ id: 7, name: 'Service-7', service_type: 'temp_mail', enabled: true, priority: 3, last_used: '2026-03-28T10:00:00Z' }},
      ]);
      return {{
        html: getElement('email-services-table').innerHTML,
      }};
    }}
    case 'render_blacklist_row_helper': {{
      if (typeof exported.renderEmailSuffixBlacklistRow !== 'function') {{
        throw new Error('renderEmailSuffixBlacklistRow is not implemented');
      }}
      return {{
        html: exported.renderEmailSuffixBlacklistRow({{ id: 42, suffix: 'blocked.com', enabled: true, reason: 'risk' }}),
      }};
    }}
    case 'render_proxy_row_helper': {{
      if (typeof exported.renderProxyRow !== 'function') {{
        throw new Error('renderProxyRow is not implemented');
      }}
      return {{
        html: exported.renderProxyRow({{
          id: 21,
          name: 'Proxy-21',
          type: 'http',
          host: '9.9.9.9',
          port: 8080,
          country: '美国',
          city: '西雅图',
          is_default: false,
          enabled: true,
          last_used: '2026-03-29T08:00:00',
          username: 'tester',
        }}),
      }};
    }}
    case 'delegated_custom_service_test': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ emailServiceAction: 'test', serviceId: '7' }},
          closest(selector) {{
            return selector === '[data-email-service-action][data-service-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
      }};
    }}
    case 'delegated_blacklist_toggle': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ blacklistAction: 'toggle', blacklistId: '12', nextEnabled: 'false' }},
          closest(selector) {{
            return selector === '[data-blacklist-action][data-blacklist-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_patch_paths: logs.apiPatches.map(([path]) => path),
      }};
    }}
    case 'render_tm_service_rows': {{
      if (typeof exported.renderTmServicesTable !== 'function') {{
        throw new Error('renderTmServicesTable is not implemented');
      }}
      exported.renderTmServicesTable([
        {{ id: 11, name: 'TM-11', api_url: 'https://tm.example.com', enabled: true, priority: 2 }},
      ]);
      return {{
        html: getElement('tm-services-table').innerHTML,
      }};
    }}
    case 'managed_service_edit_helper_success': {{
      if (typeof exported.runManagedServiceEdit !== 'function') {{
        throw new Error('runManagedServiceEdit is not implemented');
      }}
      logs.apiGets.length = 0;
      let capturedService = null;
      const originalGet = context.api.get;
      context.api.get = async (path) => {{
        logs.apiGets.push(path);
        return {{
          id: 21,
          name: 'TM-21',
          api_url: 'https://tm-21.example.com',
          enabled: true,
          priority: 6,
          has_key: true,
        }};
      }};
      try {{
        await exported.runManagedServiceEdit({{
          detailPath: '/tm-services/21',
          openModal: (service) => {{
            capturedService = service;
          }},
        }});
      }} finally {{
        context.api.get = originalGet;
      }}
      return {{
        api_get_paths: logs.apiGets,
        captured_service: capturedService,
      }};
    }}
    case 'managed_service_edit_helper_error': {{
      if (typeof exported.runManagedServiceEdit !== 'function') {{
        throw new Error('runManagedServiceEdit is not implemented');
      }}
      logs.apiGets.length = 0;
      logs.toasts.length = 0;
      const originalGet = context.api.get;
      context.api.get = async (path) => {{
        logs.apiGets.push(path);
        throw new Error('service unavailable');
      }};
      try {{
        await exported.runManagedServiceEdit({{
          detailPath: '/sub2api-services/8',
          openModal: () => {{}},
          errorPrefix: '加载失败',
        }});
      }} finally {{
        context.api.get = originalGet;
      }}
      return {{
        api_get_paths: logs.apiGets,
        error_toasts: logs.toasts
          .filter(([level]) => level === 'error')
          .map(([, message]) => message),
      }};
    }}
    case 'managed_service_save_helper_create': {{
      if (typeof exported.runManagedServiceSave !== 'function') {{
        throw new Error('runManagedServiceSave is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.apiPatches.length = 0;
      logs.toasts.length = 0;
      let closeCalls = 0;
      let reloadCalls = 0;
      await exported.runManagedServiceSave({{
        id: '',
        payload: {{
          name: 'TM-31',
          api_url: 'https://tm-31.example.com',
          priority: 3,
          enabled: true,
        }},
        secretField: 'api_key',
        secretValue: 'secret-31',
        createPath: '/tm-services',
        updatePath: '/tm-services/31',
        closeModal: () => {{
          closeCalls += 1;
        }},
        reloadFn: async () => {{
          reloadCalls += 1;
        }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        api_post_payloads: logs.apiPosts.map(([, payload]) => payload),
        api_patch_paths: logs.apiPatches.map(([path]) => path),
        success_toasts: logs.toasts
          .filter(([level]) => level === 'success')
          .map(([, message]) => message),
        close_calls: closeCalls,
        reload_calls: reloadCalls,
      }};
    }}
    case 'managed_service_save_helper_update': {{
      if (typeof exported.runManagedServiceSave !== 'function') {{
        throw new Error('runManagedServiceSave is not implemented');
      }}
      logs.apiPosts.length = 0;
      logs.apiPatches.length = 0;
      logs.toasts.length = 0;
      let closeCalls = 0;
      let reloadCalls = 0;
      await exported.runManagedServiceSave({{
        id: '31',
        payload: {{
          name: 'TM-31',
          api_url: 'https://tm-31.example.com',
          priority: 4,
          enabled: false,
        }},
        secretField: 'api_key',
        secretValue: '',
        createPath: '/tm-services',
        updatePath: '/tm-services/31',
        closeModal: () => {{
          closeCalls += 1;
        }},
        reloadFn: async () => {{
          reloadCalls += 1;
        }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
        api_patch_paths: logs.apiPatches.map(([path]) => path),
        api_patch_payloads: logs.apiPatches.map(([, payload]) => payload),
        success_toasts: logs.toasts
          .filter(([level]) => level === 'success')
          .map(([, message]) => message),
        close_calls: closeCalls,
        reload_calls: reloadCalls,
      }};
    }}
    case 'delegated_tm_service_edit': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ managedServiceAction: 'edit', managedServiceType: 'tm', serviceId: '11', serviceName: 'TM-11' }},
          closest(selector) {{
            return selector === '[data-managed-service-action][data-managed-service-type][data-service-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_get_paths: logs.apiGets,
      }};
    }}
    case 'render_cpa_service_rows': {{
      if (typeof exported.renderCpaServicesTable !== 'function') {{
        throw new Error('renderCpaServicesTable is not implemented');
      }}
      exported.renderCpaServicesTable([
        {{ id: 12, name: 'CPA-12', api_url: 'https://cpa.example.com', enabled: false, priority: 5 }},
      ]);
      return {{
        html: getElement('cpa-services-table').innerHTML,
      }};
    }}
    case 'delegated_cpa_service_test': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ managedServiceAction: 'test', managedServiceType: 'cpa', serviceId: '12', serviceName: 'CPA-12' }},
          closest(selector) {{
            return selector === '[data-managed-service-action][data-managed-service-type][data-service-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_post_paths: logs.apiPosts.map(([path]) => path),
      }};
    }}
    case 'cpa_modal_add_mode': {{
      if (typeof exported.openCpaServiceModal !== 'function') {{
        throw new Error('openCpaServiceModal is not implemented');
      }}
      getElement('cpa-service-id').value = '88';
      getElement('cpa-service-name').value = 'stale-cpa';
      getElement('cpa-service-url').value = 'https://stale-cpa.example.com';
      getElement('cpa-service-token').value = 'stale-token';
      getElement('cpa-service-token').placeholder = 'stale-token-placeholder';
      getElement('cpa-service-priority').value = 7;
      getElement('cpa-service-enabled').checked = false;

      exported.openCpaServiceModal(null);

      return {{
        id_value: getElement('cpa-service-id').value,
        name_value: getElement('cpa-service-name').value,
        url_value: getElement('cpa-service-url').value,
        token_value: getElement('cpa-service-token').value,
        token_placeholder: getElement('cpa-service-token').placeholder,
        priority_value: getElement('cpa-service-priority').value,
        enabled_checked: !!getElement('cpa-service-enabled').checked,
        title_text: getElement('cpa-service-modal-title').textContent,
      }};
    }}
    case 'render_sub2api_service_rows': {{
      if (typeof exported.renderSub2ApiServices !== 'function') {{
        throw new Error('renderSub2ApiServices is not implemented');
      }}
      exported.renderSub2ApiServices([
        {{ id: 13, name: 'Sub2API-13', api_url: 'https://sub2api.example.com', enabled: true, priority: 1 }},
      ]);
      return {{
        html: getElement('sub2api-services-table').innerHTML,
      }};
    }}
    case 'delegated_sub2api_service_delete': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      await exported.handleSettingsDelegatedTableClick({{
        target: {{
          dataset: {{ managedServiceAction: 'delete', managedServiceType: 'sub2api', serviceId: '13', serviceName: 'Sub2API-13' }},
          closest(selector) {{
            return selector === '[data-managed-service-action][data-managed-service-type][data-service-id]' ? this : null;
          }},
        }},
      }});
      return {{
        api_delete_paths: logs.apiDeletes,
      }};
    }}
    case 'delegated_sub2api_service_delete_cancelled': {{
      if (typeof exported.handleSettingsDelegatedTableClick !== 'function') {{
        throw new Error('handleSettingsDelegatedTableClick is not implemented');
      }}
      const originalConfirm = context.confirm;
      context.confirm = async () => false;
      try {{
        await exported.handleSettingsDelegatedTableClick({{
          target: {{
            dataset: {{ managedServiceAction: 'delete', managedServiceType: 'sub2api', serviceId: '13', serviceName: 'Sub2API-13' }},
            closest(selector) {{
              return selector === '[data-managed-service-action][data-managed-service-type][data-service-id]' ? this : null;
            }},
          }},
        }});
      }} finally {{
        context.confirm = originalConfirm;
      }}
      return {{
        api_delete_paths: logs.apiDeletes,
      }};
    }}
    case 'managed_service_empty_states': {{
      if (
        typeof exported.renderTmServicesTable !== 'function'
        || typeof exported.renderCpaServicesTable !== 'function'
        || typeof exported.renderSub2ApiServices !== 'function'
      ) {{
        throw new Error('managed service renderers are not implemented');
      }}
      exported.renderTmServicesTable([]);
      exported.renderCpaServicesTable([]);
      exported.renderSub2ApiServices([]);
      return {{
        tm_html: getElement('tm-services-table').innerHTML,
        cpa_html: getElement('cpa-services-table').innerHTML,
        sub2api_html: getElement('sub2api-services-table').innerHTML,
      }};
    }}
    case 'managed_service_error_states': {{
      if (
        typeof exported.loadTmServices !== 'function'
        || typeof exported.loadCpaServices !== 'function'
        || typeof exported.loadSub2ApiServices !== 'function'
      ) {{
        throw new Error('managed service loaders are not implemented');
      }}
      apiGetErrors['/tm-services'] = 'tm unavailable';
      apiGetErrors['/cpa-services'] = 'cpa unavailable';
      apiGetErrors['/sub2api-services'] = 'sub2api unavailable';
      await exported.loadTmServices();
      await exported.loadCpaServices();
      await exported.loadSub2ApiServices();
      return {{
        tm_html: getElement('tm-services-table').innerHTML,
        cpa_html: getElement('cpa-services-table').innerHTML,
        sub2api_html: getElement('sub2api-services-table').innerHTML,
      }};
    }}
    case 'save_email_suffix_blacklist_empty_suffix': {{
      if (typeof exported.handleSaveEmailSuffixBlacklist !== 'function') {{
        throw new Error('handleSaveEmailSuffixBlacklist is not implemented');
      }}
      getElement('email-suffix-blacklist-id').value = '';
      getElement('email-suffix-blacklist-suffix').value = '   @@@   ';
      getElement('email-suffix-blacklist-enabled').checked = true;
      getElement('email-suffix-blacklist-reason').value = 'x';
      await exported.handleSaveEmailSuffixBlacklist({{ preventDefault() {{}} }});
      return {{
        post_called: logs.apiPosts.length > 0,
        patch_called: logs.apiPatches.length > 0,
        error_toasts: logs.toasts
          .filter(([level]) => level === 'error')
          .map(([, message]) => message),
      }};
    }}
    case 'edit_email_suffix_blacklist': {{
      if (typeof exported.handleSaveEmailSuffixBlacklist !== 'function') {{
        throw new Error('handleSaveEmailSuffixBlacklist is not implemented');
      }}
      getElement('email-suffix-blacklist-id').value = '42';
      getElement('email-suffix-blacklist-suffix').value = '  @Example.COM ';
      getElement('email-suffix-blacklist-enabled').checked = false;
      getElement('email-suffix-blacklist-reason').value = 'manual';
      await exported.handleSaveEmailSuffixBlacklist({{ preventDefault() {{}} }});
      const patch = logs.apiPatches.at(-1) || [null, null];
      return {{
        patch_path: patch[0],
        patch_payload: patch[1],
      }};
    }}
    case 'normalize_email_suffix_input_edge_cases': {{
      if (typeof exported.normalizeEmailSuffixInput !== 'function') {{
        throw new Error('normalizeEmailSuffixInput is not implemented');
      }}
      return {{
        null_value: exported.normalizeEmailSuffixInput(null),
        number_value: exported.normalizeEmailSuffixInput(123),
        mixed_case_with_at: exported.normalizeEmailSuffixInput('  @BadMail.COM '),
      }};
    }}
    case 'render_email_suffix_blacklist_escape_and_invalid_id': {{
      if (typeof exported.renderEmailSuffixBlacklist !== 'function') {{
        throw new Error('renderEmailSuffixBlacklist is not implemented');
      }}
      exported.renderEmailSuffixBlacklist([
        {{ id: 'bad-id', suffix: '<script>alert(1)</script>', enabled: true, reason: '<b>bad\"&</b>' }},
      ]);
      return {{
        html: getElement('email-suffix-blacklist-table').innerHTML,
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
