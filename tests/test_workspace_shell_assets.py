from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from src.web.page_shell import WORKSPACE_NAV, build_page_shell
from tests_runtime.workspace_js_harness import run_workspace_js_scenario


def test_shared_stylesheet_defines_workspace_shell_selectors():
    stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".workspace-shell" in stylesheet
    assert ".workspace-sidebar" in stylesheet
    assert ".workspace-rail" in stylesheet
    assert ".workspace-sidebar-toggle" in stylesheet
    assert ".workspace-brand-link" in stylesheet
    assert ".workspace-nav" in stylesheet
    assert ".workspace-nav-group" in stylesheet
    assert ".workspace-nav-link" in stylesheet
    assert ".page-head" in stylesheet
    assert ".workspace-grid" in stylesheet
    assert ".metric-value" in stylesheet
    assert ".metric-hint" in stylesheet
    assert ".workspace-sidebar-collapsed .workspace-rail" in stylesheet
    assert ".workspace-sidebar-collapsed .workspace-main" in stylesheet
    assert ".workspace-sidebar-collapsed .workspace-nav-label" in stylesheet
    assert ".workspace-sidebar-collapsed .workspace-nav-link" in stylesheet


def test_workspace_script_defines_sidebar_and_theme_helpers():
    script = Path("static/js/workspace.js").read_text(encoding="utf-8")
    assert "WORKSPACE_SIDEBAR_STORAGE_KEY" in script
    assert "toggleWorkspaceSidebar" in script
    assert "WORKSPACE_THEME_STORAGE_KEY" in script
    assert "toggleWorkspaceTheme" in script


def test_workspace_base_template_wires_sidebar_shell_actions_and_rendered_workspace_script_version():
    base_template = Path("templates/_workspace_base.html").read_text(encoding="utf-8")
    assert '{% include "_workspace_sidebar.html" %}' in base_template
    assert 'id="workspace-sidebar-toggle"' not in base_template
    assert 'id="workspace-theme-toggle"' not in base_template
    assert 'href="/logout"' in base_template
    assert 'data-page-key="{{ page_key }}"' in base_template
    assert "/static/js/workspace.js?v={{ static_version }}" not in base_template

    environment = Environment(loader=FileSystemLoader("templates"))
    rendered_html = environment.get_template("_workspace_base.html").render(
        page_key="dashboard",
        page_title="控制台总览",
        page_subtitle="测试页面",
        static_version="123",
        workspace_nav=[
            {
                "group": "总览",
                "items": [{"key": "dashboard", "label": "控制台总览", "href": "/"}],
            }
        ],
    )
    assert "/static/js/workspace.js?v=" in rendered_html
    assert 'id="workspace-theme-toggle"' in rendered_html
    assert 'id="workspace-sidebar-toggle"' in rendered_html
    assert 'href="/logout"' in rendered_html


def test_workspace_sidebar_template_contains_sidebar_controls_and_nav_icon_label_structure():
    sidebar = Path("templates/_workspace_sidebar.html").read_text(encoding="utf-8")
    assert 'id="workspace-sidebar-toggle"' in sidebar
    assert 'id="workspace-theme-toggle"' in sidebar
    assert "workspace-nav-icon" in sidebar
    assert "workspace-nav-label" in sidebar


def test_workspace_js_harness_toggles_collapsed_state_and_storage_contract():
    result = run_workspace_js_scenario("sidebar_toggle_flow")
    assert result == {
        "after_restore_collapsed": True,
        "after_click_collapsed": False,
        "stored_sidebar_value": "expanded",
    }


def test_page_shell_navigation_groups_match_approved_workspace_map():
    expected_nav = {
        "总览": ["dashboard"],
        "执行": ["registration_workbench", "accounts", "scheduled_tasks", "payment"],
        "复盘": ["registration_experiments", "registration_batch_stats"],
        "配置": ["email_services", "settings"],
    }
    actual_nav = {
        group["group"]: [item["key"] for item in group["items"]]
        for group in WORKSPACE_NAV
    }
    assert actual_nav == expected_nav

    page_shell = build_page_shell(
        page_key="dashboard",
        page_title="控制台总览",
        page_subtitle="测试页面",
    )
    assert page_shell["workspace_nav"] == WORKSPACE_NAV
