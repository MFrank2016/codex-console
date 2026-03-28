from pathlib import Path

from tests_runtime.settings_js_harness import run_settings_js_scenario


def test_settings_template_contains_proxy_batch_import_controls():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'id="proxy-batch-import-form"' in template
    assert 'id="proxy-import-default-type"' in template
    assert 'id="proxy-filter-keyword"' in template
    assert 'id="batch-delete-proxies-btn"' in template


def test_settings_template_uses_shared_table_shell_for_management_lists():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert template.count("table-shell") >= 4


def test_settings_js_contains_proxy_batch_handlers():
    script = Path("static/js/settings.js").read_text(encoding="utf-8")
    assert "handleProxyBatchImport" in script
    assert "handleApplyProxyFilters" in script
    assert "handleBatchDeleteProxies" in script


def test_settings_js_avoids_inline_proxy_row_handlers():
    script = Path("static/js/settings.js").read_text(encoding="utf-8")

    assert 'onclick="handleSetProxyDefault(' not in script
    assert 'onclick="editProxyItem(' not in script
    assert 'onclick="toggleSettingsMoreMenu(' not in script
    assert 'onclick="testProxyItem(' not in script
    assert 'onclick="toggleProxyItem(' not in script
    assert 'onclick="deleteProxyItem(' not in script


def test_settings_js_generates_proxy_filter_query_from_form_state():
    result = run_settings_js_scenario("apply_proxy_filters")

    assert result["api_path"] == "/settings/proxies?keyword=us-west&type=http&enabled=true&is_default=false&location=Seattle"
    assert result["filters"] == {
        "keyword": "us-west",
        "type": "http",
        "enabled": "true",
        "is_default": "false",
        "location": "Seattle",
    }


def test_settings_js_updates_proxy_selection_ui_based_on_selected_rows():
    result = run_settings_js_scenario("proxy_selection_ui")

    assert result["empty_state"] == {
        "select_all_disabled": True,
        "select_all_checked": False,
        "select_all_indeterminate": False,
        "batch_delete_disabled": True,
        "batch_delete_text": "🗑️ 批量删除",
    }
    assert result["after_render"] == {
        "select_all_disabled": False,
        "select_all_checked": False,
        "select_all_indeterminate": False,
        "batch_delete_disabled": True,
        "batch_delete_text": "🗑️ 批量删除",
    }
    assert result["after_one_selected"] == {
        "select_all_disabled": False,
        "select_all_checked": False,
        "select_all_indeterminate": True,
        "batch_delete_disabled": False,
        "batch_delete_text": "🗑️ 批量删除 (1)",
        "selected_ids": [1],
    }
    assert result["after_all_selected"] == {
        "select_all_disabled": False,
        "select_all_checked": True,
        "select_all_indeterminate": False,
        "batch_delete_disabled": False,
        "batch_delete_text": "🗑️ 批量删除 (2)",
        "selected_ids": [1, 2],
    }


def test_settings_js_renders_proxy_import_result_summary_and_details():
    result = run_settings_js_scenario("proxy_import_result")

    assert result["display"] == "block"
    assert 'style=' not in result["html"]
    assert "成功导入" in result["html"]
    assert "跳过" in result["html"]
    assert "失败" in result["html"]
    assert "第 2 行" in result["html"]
    assert "duplicate" in result["html"]
    assert "美国-西雅图-001" in result["html"]


def test_settings_js_proxy_import_result_item_helper_formats_success_row():
    result = run_settings_js_scenario("render_proxy_import_result_item")
    html = result["html"]

    assert "settings-import-result-item" in html
    assert "settings-import-result-status" in html
    assert "settings-import-result-detail" in html
    assert "第 3 行" in html
    assert "✅ 成功" in html
    assert "美国-西雅图-003" in html
    assert "style=" not in html


def test_settings_js_proxy_import_result_details_helper_wraps_list_without_inline_styles():
    result = run_settings_js_scenario("render_proxy_import_result_details")
    html = result["html"]

    assert "settings-import-errors" in html
    assert "settings-import-errors-list" in html
    assert "处理结果" in html
    assert "第 4 行" in html
    assert "timeout" in html
    assert "style=" not in html


def test_settings_js_rendered_proxy_rows_use_delegated_single_item_actions():
    result = run_settings_js_scenario("proxy_row_actions")
    html = result["html"]

    assert 'data-proxy-action="edit"' in html
    assert 'data-proxy-action="test"' in html
    assert 'data-proxy-action="toggle"' in html
    assert 'data-proxy-action="set-default"' in html
    assert 'data-proxy-action="delete"' in html
    assert 'data-proxy-action="toggle-more"' in html
    assert 'data-proxy-id="7"' in html
    assert 'data-next-enabled="false"' in html
    assert 'onclick=' not in html
    assert 'style=' not in html


def test_settings_js_delegated_proxy_edit_action_still_works():
    result = run_settings_js_scenario("delegated_proxy_edit")
    assert result["api_get_paths"] == ["/settings/proxies/7"]


def test_settings_js_delegated_proxy_test_action_still_works():
    result = run_settings_js_scenario("delegated_proxy_test")
    assert result["api_post_paths"] == ["/settings/proxies/7/test"]


def test_settings_js_delegated_proxy_toggle_action_still_works():
    result = run_settings_js_scenario("delegated_proxy_toggle")
    assert result["api_post_paths"][0] == "/settings/proxies/7/disable"


def test_settings_js_delegated_proxy_set_default_action_still_works():
    result = run_settings_js_scenario("delegated_proxy_set_default")
    assert result["api_post_paths"][0] == "/settings/proxies/7/set-default"


def test_settings_js_delegated_proxy_delete_action_still_works():
    result = run_settings_js_scenario("delegated_proxy_delete")
    assert result["api_delete_paths"] == ["/settings/proxies/7"]


def test_settings_js_delegated_proxy_more_toggle_still_works():
    result = run_settings_js_scenario("delegated_proxy_toggle_more")
    assert result["menu_active"] is True


def test_settings_template_contains_advanced_dynamic_proxy_controls():
    template = Path("templates/settings.html").read_text(encoding="utf-8")

    assert 'id="dynamic-proxy-request-method"' in template
    assert 'id="dynamic-proxy-request-url"' in template
    assert 'id="dynamic-proxy-curl-input"' in template
    assert 'id="dynamic-proxy-request-headers"' in template
    assert 'id="dynamic-proxy-request-body"' in template
    assert 'id="dynamic-proxy-response-item-mode"' in template
    assert 'data-task-group="single_registration"' in template
    assert 'data-task-group="batch_registration"' in template
    assert 'data-task-group="unlimited_registration"' in template
    assert 'data-task-group="outlook_batch"' in template
    assert 'data-task-group="generic_single"' in template


def test_settings_js_can_parse_dynamic_proxy_curl_input_into_form_fields():
    result = run_settings_js_scenario("parse_dynamic_proxy_curl")

    assert result == {
        "request_method": "POST",
        "request_url": "https://proxy.example.com/fetch",
        "request_headers": '{\n  "Authorization": "Bearer token-123",\n  "Content-Type": "application/json"\n}',
        "request_body": '{\n  "region": "us",\n  "count": 5\n}',
    }


def test_settings_js_builds_dynamic_proxy_payload_with_advanced_fields():
    result = run_settings_js_scenario("build_dynamic_proxy_payload")

    assert result["api_url"] == "https://api.example.com/get_proxy"
    assert result["request_method"] == "POST"
    assert result["request_url"] == "https://proxy.example.com/fetch"
    assert result["response_item_mode"] == "object_list"
    assert result["response_field_mapping"] == {
        "proxy_url": "proxy",
        "username": "auth.username",
        "password": "auth.password",
    }
    assert result["task_defaults"] == {
        "single_registration": {
            "allocation_strategy": "round_robin",
        },
        "batch_registration": {
            "allocation_strategy": "exclusive",
        },
        "unlimited_registration": {
            "allocation_strategy": "sticky",
        },
        "outlook_batch": {
            "allocation_strategy": "exclusive",
        },
        "generic_single": {
            "allocation_strategy": "round_robin",
        },
    }


def test_settings_js_load_settings_round_trips_distinct_request_url_and_advanced_payload():
    result = run_settings_js_scenario("load_and_save_dynamic_proxy_settings")

    assert result["api_gets"] == [
        "/settings",
        "/settings/proxy/dynamic",
        "/settings/outlook",
    ]
    assert result["after_load"] == {
        "api_url": "https://api.example.com/get_proxy",
        "request_url": "https://proxy.example.com/fetch",
        "request_method": "POST",
        "response_item_mode": "object_list",
        "batch_registration_allocation_strategy": "exclusive",
    }
    assert result["saved_payload"]["api_url"] == "https://api.example.com/get_proxy"
    assert result["saved_payload"]["request_url"] == "https://proxy.example.com/fetch"
    assert result["saved_payload"]["response_item_mode"] == "object_list"
    assert result["saved_payload"]["task_defaults"]["batch_registration"] == {
        "allocation_strategy": "exclusive",
    }


def test_settings_js_blocks_dynamic_proxy_save_when_advanced_config_load_fails():
    result = run_settings_js_scenario("load_dynamic_proxy_settings_failure_blocks_save")

    assert result["api_gets"] == [
        "/settings",
        "/settings/proxy/dynamic",
        "/settings/outlook",
    ]
    assert result["save_post_attempted"] is False
    assert result["error_toasts"] == [
        "动态代理高级配置加载失败，已禁止保存以避免覆盖服务器配置",
    ]
