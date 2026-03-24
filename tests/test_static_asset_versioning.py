from pathlib import Path
import importlib

from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.web.app import create_app

web_app = importlib.import_module("src.web.app")


def test_static_asset_version_is_non_empty_string():
    version = web_app._build_static_asset_version(web_app.STATIC_DIR)

    assert isinstance(version, str)
    assert version
    assert version.isdigit()


def _login(client: TestClient, next_path: str = "/") -> None:
    password = get_settings().webui_access_password.get_secret_value()
    response = client.post(
        "/login",
        data={"password": password, "next": next_path},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_email_services_page_uses_versioned_static_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/email-services")
        response = client.get("/email-services")

    assert response.status_code == 200
    assert "/static/css/style.css?v=" in response.text
    assert "/static/js/workspace.js?v=" in response.text
    assert "/static/js/utils.js?v=" in response.text
    assert "/static/js/email_services.js?v=" in response.text


def test_registration_workbench_page_uses_versioned_static_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/registration-workbench")
        response = client.get("/registration-workbench")

    assert response.status_code == 200
    assert "/static/css/style.css?v=" in response.text
    assert "/static/js/workspace.js?v=" in response.text
    assert "/static/js/utils.js?v=" in response.text
    assert "/static/js/app.js?v=" in response.text


def test_dashboard_and_registration_pages_render_versioned_shared_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/")
        response = client.get("/")
        assert response.status_code == 200
        assert "/static/js/workspace.js?v=" in response.text
        assert "/static/js/dashboard.js?v=" in response.text

        response = client.get("/registration-workbench")
        assert response.status_code == 200
        assert "/static/js/workspace.js?v=" in response.text
        assert "/static/js/app.js?v=" in response.text


def test_workspace_routes_render_after_login():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/")

        for path, page_key in [
            ("/accounts", "accounts"),
            ("/scheduled-tasks", "scheduled_tasks"),
            ("/email-services", "email_services"),
            ("/settings", "settings"),
            ("/registration-experiments", "registration_experiments"),
            ("/registration-batch-stats", "registration_batch_stats"),
        ]:
            response = client.get(path)
            assert response.status_code == 200
            assert f'data-page-key="{page_key}"' in response.text
            assert "/static/js/workspace.js?v=" in response.text
