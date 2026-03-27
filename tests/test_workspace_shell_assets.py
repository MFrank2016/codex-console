from pathlib import Path
import re

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
    assert ".theme-toggle.workspace-theme-toggle" in stylesheet


def test_workspace_script_defines_sidebar_and_theme_helpers():
    script = Path("static/js/workspace.js").read_text(encoding="utf-8")
    assert "WORKSPACE_SIDEBAR_STORAGE_KEY" in script
    assert "toggleWorkspaceSidebar" in script
    assert "WORKSPACE_THEME_STORAGE_KEY" in script
    assert "toggleWorkspaceTheme" in script


def test_dark_theme_defines_warm_surface_tokens_for_workspace_cards():
    stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
    match = re.search(r'\[data-theme="dark"]\s*\{(?P<body>.*?)\n\}', stylesheet, re.S)
    assert match is not None
    dark_block = match.group("body")
    assert "--warm-background:" in dark_block
    assert "--warm-surface:" in dark_block
    assert "--warm-surface-strong:" in dark_block
    assert "--warm-border:" in dark_block


def test_workspace_base_template_wires_sidebar_shell_actions_and_rendered_workspace_script_version():
    base_template = Path("templates/_workspace_base.html").read_text(encoding="utf-8")
    assert '{% include "_workspace_sidebar.html" %}' in base_template
    assert 'id="workspace-sidebar-toggle"' not in base_template
    assert 'id="workspace-theme-toggle"' in base_template
    assert 'href="/logout"' not in base_template
    assert 'data-page-key="{{ page_key }}"' in base_template
    assert "/static/js/workspace.js?v={{ static_version }}" not in base_template
    assert "codex-console.workspace.sidebar" in base_template
    assert "localStorage.getItem('theme')" in base_template
    assert base_template.index("codex-console.workspace.sidebar") < base_template.index(
        "/static/css/style.css?v={{ static_version }}"
    )
    assert base_template.index("codex-console.workspace.sidebar") < base_template.index(
        "/static/js/workspace.js?v="
    )

    environment = Environment(loader=FileSystemLoader("templates"))
    rendered_html = environment.get_template("_workspace_base.html").render(
        page_key="dashboard",
        page_title="控制台总览",
        page_subtitle="测试页面",
        static_version="123",
        workspace_nav=[
            {
                "group": "总览",
                "items": [
                    {
                        "key": "dashboard",
                        "label": "控制台总览",
                        "href": "/",
                        "icon": "dashboard",
                    }
                ],
            }
        ],
    )
    assert "/static/js/workspace.js?v=" in rendered_html
    assert 'id="workspace-theme-toggle"' in rendered_html
    assert 'id="workspace-sidebar-toggle"' in rendered_html
    assert 'href="/logout"' in rendered_html
    assert rendered_html.index("codex-console.workspace.sidebar") < rendered_html.index(
        "/static/js/workspace.js?v="
    )
    assert re.search(r'<header class="page-head">[\s\S]*id="workspace-theme-toggle"', rendered_html)
    assert re.search(
        r'<footer class="workspace-sidebar-footer">[\s\S]*href="/logout"',
        rendered_html,
    )


def test_workspace_sidebar_template_contains_sidebar_controls_and_nav_icon_label_structure():
    sidebar = Path("templates/_workspace_sidebar.html").read_text(encoding="utf-8")
    assert 'id="workspace-sidebar-toggle"' in sidebar
    assert 'id="workspace-theme-toggle"' not in sidebar
    assert "workspace-nav-icon" in sidebar
    assert "workspace-nav-label" in sidebar
    assert 'aria-label="{{ nav_item["label"] }}"' in sidebar
    assert '{% from "_workspace_icons.html" import workspace_icon %}' in sidebar
    assert 'workspace_icon(nav_item["icon"])' in sidebar
    assert "workspace-sidebar-footer" in sidebar
    assert 'href="/logout"' in sidebar
    for structural_emoji in ["🏠", "🧪", "👤", "🗓️", "💳", "📊", "📈", "✉️", "⚙️"]:
        assert structural_emoji not in sidebar


def test_workspace_icons_template_centralizes_workspace_shell_svg_icon_markup():
    icon_template = Path("templates/_workspace_icons.html").read_text(encoding="utf-8")
    assert "{% macro workspace_icon(icon_key) %}" in icon_template
    for icon_key in [
        "dashboard",
        "registration_workbench",
        "run_center",
        "accounts",
        "registration_experiments",
        "registration_batch_stats",
        "scheduled_tasks",
        "email_services",
        "settings",
        "payment",
        "sidebar_toggle",
        "theme_dark",
        "theme_light",
        "logout",
    ]:
        assert f'"{icon_key}"' in icon_template


def test_workspace_js_harness_toggles_collapsed_state_and_storage_contract():
    result = run_workspace_js_scenario("sidebar_toggle_flow")
    assert result == {
        "preflight_collapsed": True,
        "preflight_theme": "dark",
        "after_restore_collapsed": True,
        "after_restore_toggle_title": "展开侧边栏",
        "after_restore_toggle_pressed": "true",
        "after_restore_theme": "dark",
        "after_restore_theme_title": "切换到亮色模式",
        "after_restore_theme_icon": "theme-light",
        "after_click_collapsed": False,
        "after_click_toggle_title": "折叠侧边栏",
        "after_click_toggle_pressed": "false",
        "after_theme_click_theme": "light",
        "after_theme_click_title": "切换到暗色模式",
        "after_theme_click_icon": "theme-dark",
        "stored_sidebar_value": "expanded",
        "stored_theme_value": "light",
    }


def test_page_shell_navigation_groups_match_approved_workspace_map():
    expected_nav = {
        "总览": ["dashboard"],
        "执行": ["registration_workbench", "run_center", "accounts"],
        "复盘": ["registration_experiments", "registration_batch_stats"],
        "支撑": ["scheduled_tasks", "email_services", "settings", "payment"],
    }
    actual_nav = {
        group["group"]: [item["key"] for item in group["items"]]
        for group in WORKSPACE_NAV
    }
    assert actual_nav == expected_nav
    assert all("icon" in item for group in WORKSPACE_NAV for item in group["items"])

    page_shell = build_page_shell(
        page_key="dashboard",
        page_title="控制台总览",
        page_subtitle="测试页面",
    )
    assert page_shell["workspace_nav"] == WORKSPACE_NAV
