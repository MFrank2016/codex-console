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
