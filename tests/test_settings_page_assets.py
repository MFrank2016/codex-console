from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app


def test_settings_page_requires_auth_and_loads_utils_before_page_script():
    app = create_app()
    with TestClient(app) as client:
        unauthenticated = client.get("/settings", follow_redirects=False)
        assert unauthenticated.status_code == 302
        assert unauthenticated.headers["location"] == "/login?next=/settings"

        password = get_settings().webui_access_password.get_secret_value()
        login_response = client.post(
            "/login",
            data={"password": password, "next": "/settings"},
            follow_redirects=False,
        )
        assert login_response.status_code == 302

        response = client.get("/settings")

    assert response.status_code == 200
    assert "/static/js/utils.js?v=" in response.text
    assert "/static/js/settings.js?v=" in response.text
    assert response.text.index("/static/js/utils.js?v=") < response.text.index("/static/js/settings.js?v=")


def test_settings_template_has_no_inline_event_handlers_in_template_layer():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert "onclick=" not in template
    assert "onchange=" not in template
    assert "onsubmit=" not in template


def test_settings_template_reduces_high_frequency_inline_style_hotspots():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'style="' not in template
    assert 'style="margin-top: var(--spacing-lg);"' not in template
    assert (
        'style="display: flex; justify-content: space-between; align-items: center; '
        'gap: var(--spacing-sm); flex-wrap: wrap;"'
    ) not in template
    assert (
        'style="margin-top: var(--spacing-md); display: flex; gap: var(--spacing-sm); '
        'flex-wrap: wrap; align-items: end;"'
    ) not in template
    assert 'style="display: block;"' not in template
    assert 'style="display: flex; gap: var(--spacing-sm); flex-wrap: wrap;"' not in template
    assert 'style="margin: 0; min-width: 180px; flex: 1 1 180px;"' not in template
    assert 'style="margin: 0; min-width: 120px;"' not in template
    assert 'style="margin: 0; min-width: 160px; flex: 1 1 160px;"' not in template
    assert 'style="margin: 0; padding: 0; border: 0; gap: var(--spacing-sm);"' not in template
    assert 'style="padding: 0;"' not in template
    assert 'style="color: var(--text-muted);"' not in template
    assert 'style="margin-top: var(--spacing-xs);"' not in template
    assert 'style="display: none; margin-top: var(--spacing-md);"' not in template
    assert 'style="max-width: 500px;"' not in template
    assert 'style="max-width: 520px;"' not in template
    assert 'style="max-width: 420px;"' not in template
    assert 'style="margin-top:10px;display:flex;align-items:center;gap:8px;"' not in template
    assert 'style="display:flex;align-items:center;gap:8px;"' not in template
    assert 'style="margin-bottom: var(--spacing-lg);"' not in template
    assert 'style="margin-top: 0; color: var(--text-secondary);"' not in template
    assert 'style="text-align:center;color:var(--text-muted);padding:20px;"' not in template


def test_settings_script_replaces_inline_handlers_for_settings_service_tables():
    script = Path("static/js/settings.js").read_text(encoding="utf-8")
    assert 'style="' not in script
    assert 'onclick="testService(' not in script
    assert 'onclick="toggleService(' not in script
    assert 'onclick="deleteService(' not in script
    assert 'onclick="openEmailSuffixBlacklistModalById(' not in script
    assert 'onclick="toggleEmailSuffixBlacklistItem(' not in script
    assert 'onclick="deleteEmailSuffixBlacklistItem(' not in script
    assert 'onchange="updateSelectedServices()"' not in script
    assert 'onclick="editTmService(' not in script
    assert 'onclick="testTmServiceById(' not in script
    assert 'onclick="deleteTmService(' not in script
    assert 'onclick="editCpaService(' not in script
    assert 'onclick="testCpaServiceById(' not in script
    assert 'onclick="deleteCpaService(' not in script
    assert 'onclick="editSub2ApiService(' not in script
    assert 'onclick="testSub2ApiServiceById(' not in script
    assert 'onclick="deleteSub2ApiService(' not in script
