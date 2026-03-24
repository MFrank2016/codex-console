from pathlib import Path
import importlib
import re

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


def _assert_versioned_asset(response_text: str, asset_path: str) -> None:
    pattern = re.compile(rf'{re.escape(asset_path)}\?v=([^"\s<>]+)')
    match = pattern.search(response_text)
    assert match is not None, f"missing versioned asset for {asset_path}"
    assert match.group(1), f"empty asset version for {asset_path}"


def test_email_services_page_uses_versioned_static_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/email-services")
        response = client.get("/email-services")

    assert response.status_code == 200
    _assert_versioned_asset(response.text, "/static/css/style.css")
    _assert_versioned_asset(response.text, "/static/js/workspace.js")
    _assert_versioned_asset(response.text, "/static/js/utils.js")
    _assert_versioned_asset(response.text, "/static/js/email_services.js")


def test_registration_workbench_page_uses_versioned_static_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/registration-workbench")
        response = client.get("/registration-workbench")

    assert response.status_code == 200
    _assert_versioned_asset(response.text, "/static/css/style.css")
    _assert_versioned_asset(response.text, "/static/js/workspace.js")
    _assert_versioned_asset(response.text, "/static/js/utils.js")
    _assert_versioned_asset(response.text, "/static/js/app.js")


def test_dashboard_and_registration_pages_render_versioned_shared_assets():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/")
        response = client.get("/")
        assert response.status_code == 200
        _assert_versioned_asset(response.text, "/static/js/workspace.js")
        _assert_versioned_asset(response.text, "/static/js/dashboard.js")

        response = client.get("/registration-workbench")
        assert response.status_code == 200
        _assert_versioned_asset(response.text, "/static/js/workspace.js")
        _assert_versioned_asset(response.text, "/static/js/app.js")


def test_workspace_routes_render_after_login_with_page_specific_scripts():
    app = create_app()
    with TestClient(app) as client:
        _login(client, "/")

        for path, page_key, script_path in [
            ("/accounts", "accounts", "/static/js/accounts.js"),
            ("/scheduled-tasks", "scheduled_tasks", "/static/js/scheduled_tasks.js"),
            ("/email-services", "email_services", "/static/js/email_services.js"),
            ("/settings", "settings", "/static/js/settings.js"),
            ("/registration-experiments", "registration_experiments", "/static/js/registration_experiments.js"),
            ("/registration-batch-stats", "registration_batch_stats", "/static/js/registration_batch_stats.js"),
            ("/payment", "payment", "/static/js/payment.js"),
        ]:
            response = client.get(path)
            assert response.status_code == 200
            assert f'data-page-key="{page_key}"' in response.text
            _assert_versioned_asset(response.text, "/static/js/workspace.js")
            _assert_versioned_asset(response.text, script_path)
