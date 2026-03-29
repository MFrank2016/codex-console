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


def test_settings_delegated_custom_service_actions_still_work():
    result = run_settings_js_scenario("delegated_custom_service_test")
    assert result["api_post_paths"] == ["/email-services/7/test"]


def test_settings_delegated_blacklist_actions_still_work():
    result = run_settings_js_scenario("delegated_blacklist_toggle")
    assert result["api_patch_paths"] == ["/settings/email-suffix-blacklist/12"]


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
