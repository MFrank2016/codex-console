from pathlib import Path

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app


SUPPORT_TEMPLATES = [
    "templates/scheduled_tasks.html",
    "templates/email_services.html",
    "templates/settings.html",
    "templates/payment.html",
]


def _login(client: TestClient, *, next_path: str) -> None:
    password = get_settings().webui_access_password.get_secret_value()
    response = client.post(
        "/login",
        data={"password": password, "next": next_path},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _assert_uses_shared_workspace_assets(html: str) -> None:
    assert "/static/css/style.css?v=" in html
    assert "/static/css/workspace_shell.css?v=" in html
    assert "/static/css/workspace_components.css?v=" in html
    assert html.index("/static/css/style.css?v=") < html.index("/static/css/workspace_shell.css?v=")
    assert html.index("/static/css/workspace_shell.css?v=") < html.index(
        "/static/css/workspace_components.css?v="
    )
    assert 'class="workspace-rail"' in html
    assert 'class="workspace-main"' in html
    assert "workspace-sidebar-footer" in html


def test_support_templates_do_not_redeclare_workspace_shared_stylesheet_links():
    for template_path in SUPPORT_TEMPLATES:
        template = Path(template_path).read_text(encoding="utf-8")
        assert '{% extends "_workspace_base.html" %}' in template
        assert 'href="/static/css/style.css' not in template
        assert 'href="/static/css/workspace_shell.css' not in template
        assert 'href="/static/css/workspace_components.css' not in template


def test_support_pages_render_with_workspace_shell_and_components_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, next_path="/scheduled-tasks")
        for path in ["/scheduled-tasks", "/email-services", "/settings", "/payment"]:
            response = client.get(path)
            assert response.status_code == 200
            _assert_uses_shared_workspace_assets(response.text)


def test_support_pages_use_shared_page_header_and_panel_shell():
    for path in ["templates/email_services.html", "templates/settings.html", "templates/payment.html"]:
        template = Path(path).read_text(encoding="utf-8")
        assert "workspace-panel" in template
        assert "page-head" in template or "page-header" in template
        assert "support-page-shell" in template


def test_support_page_danger_modal_defaults_focus_to_cancel():
    template = Path("templates/settings.html").read_text(encoding="utf-8")
    assert 'data-danger-default="cancel"' in template
