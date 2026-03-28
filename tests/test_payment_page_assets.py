from pathlib import Path

from fastapi.testclient import TestClient

from src.web.app import create_app
from tests_runtime.payment_js_harness import run_payment_js_scenario


def test_payment_page_renders_and_loads_utils_before_page_script():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/payment")

    assert response.status_code == 200
    assert "/static/js/utils.js?v=" in response.text
    assert "/static/js/payment.js?v=" in response.text
    assert response.text.index("/static/js/utils.js?v=") < response.text.index("/static/js/payment.js?v=")


def test_payment_template_has_no_inline_event_handlers():
    template = Path("templates/payment.html").read_text(encoding="utf-8")
    assert "onclick=" not in template
    assert "onchange=" not in template


def test_payment_template_reduces_inline_style_hotspots():
    template = Path("templates/payment.html").read_text(encoding="utf-8")
    assert 'style="width:100%"' not in template
    assert 'style="background:var(--surface-hover);cursor:default"' not in template
    assert 'style="margin-top:10px"' not in template



def test_payment_script_uses_api_client_instead_of_direct_fetch():
    script = Path("static/js/payment.js").read_text(encoding="utf-8")
    assert "fetch(" not in script
    assert "api.get(" in script
    assert script.count("api.post(") >= 2


def test_payment_js_binds_plan_switch_country_change_and_submit_actions():
    result = run_payment_js_scenario("event_binding_matrix")
    assert result["selected_plan"] == "team"
    assert result["currency"] == "USD"
    assert result["api_get_paths"] == ["/accounts?page=1&page_size=100&status=active"]
    assert result["api_post_paths"] == ["/payment/generate-link", "/payment/open-incognito"]
