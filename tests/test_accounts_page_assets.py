from pathlib import Path

from tests_runtime.accounts_js_harness import run_accounts_js_scenario


def test_accounts_template_contains_asset_toolbar_table_and_detail_drawer():
    template = Path("templates/accounts.html").read_text(encoding="utf-8")
    assert 'id="accounts-asset-toolbar"' in template
    assert 'id="accounts-detail-drawer"' in template
    assert 'id="accounts-table"' in template


def test_accounts_drawer_accessibility_contract():
    result = run_accounts_js_scenario("drawer_focus_contract")
    assert result == {
        "focus_moved_into_drawer": True,
        "escape_closes_drawer": True,
        "focus_returned_to_trigger": True,
    }


def test_accounts_actions_reload_stats_list_and_open_drawer_views():
    result = run_accounts_js_scenario("refresh_action_reloads_account_views")
    assert "/accounts/1/refresh" in result["api_post_paths"]
    assert result["api_get_paths"].count("/accounts/stats/summary") >= 2
    assert any(path.startswith("/accounts?page=1&page_size=20") for path in result["api_get_paths"])
    assert result["api_get_paths"].count("/accounts/1") >= 2
    assert result["api_get_paths"].count("/accounts/1/tokens") >= 2


def test_accounts_batch_subscription_check_reloads_stats_list_and_drawer_views():
    result = run_accounts_js_scenario("batch_subscription_check_reloads_account_views")
    assert result["api_post_paths"] == ["/payment/accounts/batch-check-subscription"]
    assert result["api_get_paths"].count("/accounts/stats/summary") >= 2
    assert any(path.startswith("/accounts?page=1&page_size=20") for path in result["api_get_paths"])
    assert result["api_get_paths"].count("/accounts/1") >= 2
    assert result["api_get_paths"].count("/accounts/1/tokens") >= 2
