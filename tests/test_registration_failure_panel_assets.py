from pathlib import Path

from tests_runtime.app_js_harness import run_app_js_scenario


def test_registration_template_contains_failure_analysis_panel_hooks():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-failure-summary"' in template
    assert 'id="registration-failure-filter-form"' in template
    assert 'id="registration-failure-table-body"' in template
    assert 'id="registration-failure-detail-dialog"' in template



def test_registration_workbench_stylesheet_contains_failure_analysis_layout_rules():
    stylesheet = Path("static/css/registration_workbench.css").read_text(encoding="utf-8")
    assert ".failure-summary-grid" in stylesheet
    assert ".failure-analysis-table" in stylesheet



def test_app_js_loads_failure_summary_and_table_with_current_filters():
    result = run_app_js_scenario("load_registration_failures")
    assert "/registration/failures/summary" in result["api_get_paths"][0]
    assert "pipeline_key=codexgen_pipeline" in result["api_get_paths"][0]
    assert result["summary_total_text"] == "12"
    assert "blocked.test" in result["table_html"]



def test_app_js_failure_table_escapes_html_and_opens_detail_dialog():
    result = run_app_js_scenario("render_registration_failure_rows")
    assert "<script>" not in result["table_html"]
    assert "&lt;script&gt;" in result["table_html"] or result["detail_uses_text_content"] is True
    assert result["detail_dialog_open"] is True
