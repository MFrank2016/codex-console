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
