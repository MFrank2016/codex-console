from pathlib import Path

from tests_runtime.settings_js_harness import run_settings_js_scenario


def test_settings_template_contains_email_suffix_blacklist_hooks():
    template = Path("templates/settings.html").read_text(encoding="utf-8")

    assert 'id="email-suffix-blacklist-table"' in template
    assert 'id="add-email-suffix-blacklist-btn"' in template
    assert 'id="email-suffix-blacklist-modal"' in template


def test_settings_js_save_email_suffix_blacklist_normalizes_suffix_payload():
    result = run_settings_js_scenario("save_email_suffix_blacklist")

    assert result["post_path"] == "/settings/email-suffix-blacklist"
    assert result["payload"] == {
        "suffix": "badmail.com",
        "enabled": True,
        "reason": "临时封禁",
    }


def test_settings_js_render_email_suffix_blacklist_rows_contains_action_hooks():
    result = run_settings_js_scenario("render_email_suffix_blacklist_rows")
    html = result["html"]

    assert "badmail.com" in html
    assert "toggleEmailSuffixBlacklistItem(5, false)" in html
    assert "deleteEmailSuffixBlacklistItem(5)" in html


def test_settings_js_save_email_suffix_blacklist_rejects_empty_suffix_without_request():
    result = run_settings_js_scenario("save_email_suffix_blacklist_empty_suffix")

    assert result["post_called"] is False
    assert result["patch_called"] is False
    assert result["error_toasts"] == ["邮箱后缀不能为空"]


def test_settings_js_save_email_suffix_blacklist_edit_uses_patch():
    result = run_settings_js_scenario("edit_email_suffix_blacklist")

    assert result["patch_path"] == "/settings/email-suffix-blacklist/42"
    assert result["patch_payload"] == {
        "suffix": "example.com",
        "enabled": False,
        "reason": "manual",
    }


def test_settings_js_normalize_email_suffix_input_handles_non_string_values():
    result = run_settings_js_scenario("normalize_email_suffix_input_edge_cases")

    assert result == {
        "null_value": "",
        "number_value": "123",
        "mixed_case_with_at": "badmail.com",
    }


def test_settings_js_render_email_suffix_blacklist_escapes_html_and_invalid_id_actions():
    result = run_settings_js_scenario("render_email_suffix_blacklist_escape_and_invalid_id")
    html = result["html"]

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;bad&quot;&amp;&lt;/b&gt;" in html
    assert "openEmailSuffixBlacklistModalById(" not in html
    assert "toggleEmailSuffixBlacklistItem(" not in html
    assert "deleteEmailSuffixBlacklistItem(" not in html
