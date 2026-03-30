from tests_runtime.settings_js_harness import run_settings_js_scenario


def test_settings_render_email_service_rows_uses_delegated_action_attributes():
    result = run_settings_js_scenario("render_email_service_rows")
    html = result["html"]

    assert 'data-email-service-action="test"' in html
    assert 'data-email-service-action="toggle"' in html
    assert 'data-email-service-action="delete"' in html
    assert 'data-service-id="7"' in html
    assert 'onclick=' not in html
    assert 'onchange=' not in html
    assert 'style=' not in html


def test_settings_email_service_row_helper_keeps_delegated_actions_without_inline_styles():
    result = run_settings_js_scenario("render_email_service_row_helper")
    html = result["html"]

    assert 'data-email-service-action="test"' in html
    assert 'data-email-service-action="toggle"' in html
    assert 'data-email-service-action="delete"' in html
    assert 'data-service-id="17"' in html
    assert 'Service-17' in html
    assert 'onclick=' not in html
    assert 'onchange=' not in html
    assert 'style=' not in html


def test_settings_email_services_empty_state_helper_uses_shared_empty_state_markup():
    result = run_settings_js_scenario("render_email_services_empty_state_helper")
    html = result["html"]

    assert 'empty-state' in html
    assert 'empty-state-icon' in html
    assert 'empty-state-title' in html
    assert '📭' in html
    assert '暂无配置' in html
    assert 'style=' not in html


def test_settings_email_services_error_state_helper_uses_shared_empty_state_markup():
    result = run_settings_js_scenario("render_email_services_error_state_helper")
    html = result["html"]

    assert 'empty-state' in html
    assert 'empty-state-icon' in html
    assert 'empty-state-title' in html
    assert '❌' in html
    assert '加载失败' in html
    assert 'style=' not in html


def test_settings_managed_service_connection_test_helper_uses_saved_test_endpoint():
    result = run_settings_js_scenario("managed_service_connection_test_helper_saved")

    assert result["api_post_paths"] == ["/tm-services/12/test"]
    assert result["button_disabled"] is False
    assert result["button_text"] == "🔌 测试连接"


def test_settings_managed_service_connection_test_helper_uses_connection_endpoint_payload():
    result = run_settings_js_scenario("managed_service_connection_test_helper_new")

    assert result["api_post_paths"] == ["/tm-services/test-connection"]
    assert result["api_post_payloads"] == [
        {"api_url": "https://tm.example.com", "api_key": "secret-123"}
    ]
    assert result["button_disabled"] is False
    assert result["button_text"] == "🔌 测试连接"


def test_settings_managed_service_saved_test_helper_posts_and_reports_success():
    result = run_settings_js_scenario("managed_service_saved_test_helper")

    assert result["api_post_paths"] == ["/tm-services/15/test"]
    assert result["success_toasts"] == ["连接正常"]


def test_settings_managed_service_form_test_helper_requires_secret_for_new_service():
    result = run_settings_js_scenario("managed_service_form_test_helper_requires_secret")

    assert result["api_post_paths"] == []
    assert result["error_toasts"] == ["请先填写 API Token"]


def test_settings_managed_service_form_test_helper_uses_connection_payload_for_new_service():
    result = run_settings_js_scenario("managed_service_form_test_helper_new_connection")

    assert result["api_post_paths"] == ["/cpa-services/test-connection"]
    assert result["api_post_payloads"] == [
        {"api_url": "https://cpa.example.com", "api_token": "token-88"}
    ]
    assert result["button_disabled"] is False
    assert result["button_text"] == "🔌 测试连接"


def test_settings_managed_service_form_test_helper_uses_saved_test_for_existing_service():
    result = run_settings_js_scenario("managed_service_form_test_helper_existing_saved")

    assert result["api_post_paths"] == ["/tm-services/88/test"]
    assert result["button_disabled"] is False
    assert result["button_text"] == "🔌 测试连接"


def test_settings_managed_service_load_helper_fetches_and_renders_items():
    result = run_settings_js_scenario("managed_service_load_helper_success")

    assert result["api_get_paths"] == ["/tm-services"]
    assert result["rendered_items"] == [
        {
            "id": 51,
            "name": "TM-51",
            "api_url": "https://tm-51.example.com",
            "enabled": True,
            "priority": 5,
        }
    ]


def test_settings_managed_service_load_helper_sets_shared_error_feedback():
    result = run_settings_js_scenario("managed_service_load_helper_error")

    assert "settings-table-feedback-cell--danger" in result["html"]
    assert "service unavailable" in result["html"]


def test_settings_managed_service_save_form_helper_requires_name_and_url_when_enabled():
    result = run_settings_js_scenario("managed_service_save_form_helper_requires_name_url")

    assert result["result"] is None
    assert result["error_toasts"] == ["名称和 API URL 不能为空"]


def test_settings_managed_service_save_form_helper_returns_trimmed_payload():
    result = run_settings_js_scenario("managed_service_save_form_helper_success")

    assert result["result"] == {
        "id": "41",
        "payload": {
            "name": "TM-41",
            "api_url": "https://tm-41.example.com",
            "priority": 7,
            "enabled": False,
        },
        "secret_value": "",
    }


def test_settings_managed_service_save_form_helper_can_skip_name_url_validation():
    result = run_settings_js_scenario("managed_service_save_form_helper_skip_name_url")

    assert result["result"] == {
        "id": "",
        "payload": {
            "name": "",
            "api_url": "",
            "priority": 0,
            "enabled": True,
        },
        "secret_value": "key-51",
    }


def test_settings_managed_service_close_helper_runs_remove_reset_and_after_close():
    result = run_settings_js_scenario("managed_service_close_helper")

    assert result == {
        "remove_calls": 1,
        "reset_calls": 1,
        "after_close_calls": 1,
    }


def test_settings_sub2api_close_modal_still_resets_form_and_hides_modal():
    result = run_settings_js_scenario("sub2api_close_modal")

    assert result == {
        "remove_calls": 1,
        "reset_calls": 1,
    }


def test_settings_sub2api_modal_add_mode_clears_stale_values_and_restores_defaults():
    result = run_settings_js_scenario("sub2api_modal_add_mode")

    assert result == {
        "id_value": "",
        "name_value": "",
        "url_value": "",
        "key_value": "",
        "key_placeholder": "请输入 API Key",
        "priority_value": 0,
        "enabled_checked": True,
        "title_text": "添加 Sub2API 服务",
    }


def test_settings_delegated_custom_service_actions_still_work():
    result = run_settings_js_scenario("delegated_custom_service_test")
    assert result["api_post_paths"] == ["/email-services/7/test"]


def test_settings_delegated_blacklist_actions_still_work():
    result = run_settings_js_scenario("delegated_blacklist_toggle")
    assert result["api_patch_paths"] == ["/settings/email-suffix-blacklist/12"]


def test_settings_managed_service_edit_helper_fetches_details_and_opens_modal():
    result = run_settings_js_scenario("managed_service_edit_helper_success")

    assert result["api_get_paths"] == ["/tm-services/21"]
    assert result["captured_service"] == {
        "id": 21,
        "name": "TM-21",
        "api_url": "https://tm-21.example.com",
        "enabled": True,
        "priority": 6,
        "has_key": True,
    }


def test_settings_managed_service_edit_helper_uses_custom_error_prefix():
    result = run_settings_js_scenario("managed_service_edit_helper_error")

    assert result["error_toasts"] == ["加载失败: service unavailable"]


def test_settings_managed_service_save_helper_creates_with_secret_and_runs_followups():
    result = run_settings_js_scenario("managed_service_save_helper_create")

    assert result["api_post_paths"] == ["/tm-services"]
    assert result["api_post_payloads"] == [
        {
            "name": "TM-31",
            "api_url": "https://tm-31.example.com",
            "priority": 3,
            "enabled": True,
            "api_key": "secret-31",
        }
    ]
    assert result["api_patch_paths"] == []
    assert result["success_toasts"] == ["服务已添加"]
    assert result["close_calls"] == 1
    assert result["reload_calls"] == 1


def test_settings_managed_service_save_helper_updates_without_empty_secret():
    result = run_settings_js_scenario("managed_service_save_helper_update")

    assert result["api_patch_paths"] == ["/tm-services/31"]
    assert result["api_patch_payloads"] == [
        {
            "name": "TM-31",
            "api_url": "https://tm-31.example.com",
            "priority": 4,
            "enabled": False,
        }
    ]
    assert result["api_post_paths"] == []
    assert result["success_toasts"] == ["服务已更新"]
    assert result["close_calls"] == 1
    assert result["reload_calls"] == 1


def test_settings_render_tm_service_rows_uses_delegated_action_attributes():
    result = run_settings_js_scenario("render_tm_service_rows")
    html = result["html"]

    assert 'data-managed-service-action="edit"' in html
    assert 'data-managed-service-action="test"' in html
    assert 'data-managed-service-action="delete"' in html
    assert 'data-managed-service-type="tm"' in html
    assert 'data-service-id="11"' in html
    assert 'onclick=' not in html
    assert 'style=' not in html


def test_settings_delegated_tm_service_edit_still_works():
    result = run_settings_js_scenario("delegated_tm_service_edit")
    assert result["api_get_paths"] == ["/tm-services/11"]


def test_settings_render_cpa_service_rows_uses_delegated_action_attributes():
    result = run_settings_js_scenario("render_cpa_service_rows")
    html = result["html"]

    assert 'data-managed-service-action="edit"' in html
    assert 'data-managed-service-action="test"' in html
    assert 'data-managed-service-action="delete"' in html
    assert 'data-managed-service-type="cpa"' in html
    assert 'data-service-id="12"' in html
    assert 'onclick=' not in html
    assert 'style=' not in html


def test_settings_delegated_cpa_service_test_still_works():
    result = run_settings_js_scenario("delegated_cpa_service_test")
    assert result["api_post_paths"] == ["/cpa-services/12/test"]


def test_settings_cpa_modal_add_mode_clears_stale_values_and_restores_defaults():
    result = run_settings_js_scenario("cpa_modal_add_mode")

    assert result == {
        "id_value": "",
        "name_value": "",
        "url_value": "",
        "token_value": "",
        "token_placeholder": "请输入 API Token",
        "priority_value": 0,
        "enabled_checked": True,
        "title_text": "添加 CPA 服务",
    }


def test_settings_render_sub2api_service_rows_uses_delegated_action_attributes():
    result = run_settings_js_scenario("render_sub2api_service_rows")
    html = result["html"]

    assert 'data-managed-service-action="edit"' in html
    assert 'data-managed-service-action="test"' in html
    assert 'data-managed-service-action="delete"' in html
    assert 'data-managed-service-type="sub2api"' in html
    assert 'data-service-id="13"' in html
    assert 'onclick=' not in html
    assert 'style=' not in html


def test_settings_delegated_sub2api_service_delete_still_works():
    result = run_settings_js_scenario("delegated_sub2api_service_delete")
    assert result["api_delete_paths"] == ["/sub2api-services/13"]


def test_settings_delegated_sub2api_service_delete_respects_cancelled_confirm():
    result = run_settings_js_scenario("delegated_sub2api_service_delete_cancelled")
    assert result["api_delete_paths"] == []


def test_settings_managed_service_empty_states_use_shared_feedback_row_classes():
    result = run_settings_js_scenario("managed_service_empty_states")

    for key in ("tm_html", "cpa_html", "sub2api_html"):
        html = result[key]
        assert "settings-table-feedback-cell" in html
        assert "settings-table-feedback-cell--muted" in html
        assert "style=" not in html


def test_settings_managed_service_error_states_use_shared_feedback_row_classes():
    result = run_settings_js_scenario("managed_service_error_states")

    for key in ("tm_html", "cpa_html", "sub2api_html"):
        html = result[key]
        assert "settings-table-feedback-cell" in html
        assert "settings-table-feedback-cell--danger" in html
        assert "style=" not in html


def test_settings_blacklist_row_helper_keeps_delegated_actions_without_inline_styles():
    result = run_settings_js_scenario("render_blacklist_row_helper")
    html = result["html"]

    assert 'data-blacklist-action="edit"' in html
    assert 'data-blacklist-action="toggle"' in html
    assert 'data-blacklist-action="delete"' in html
    assert 'data-blacklist-id="42"' in html
    assert 'style=' not in html


def test_settings_proxy_row_helper_keeps_delegated_actions_without_inline_styles():
    result = run_settings_js_scenario("render_proxy_row_helper")
    html = result["html"]

    assert 'data-proxy-action="edit"' in html
    assert 'data-proxy-action="test"' in html
    assert 'data-proxy-action="toggle"' in html
    assert 'data-proxy-action="set-default"' in html
    assert 'data-proxy-action="delete"' in html
    assert 'data-proxy-id="21"' in html
    assert 'style=' not in html
