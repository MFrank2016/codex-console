from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def test_shared_stylesheet_defines_workspace_shell_selectors():
    stylesheet = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".workspace-shell" in stylesheet
    assert ".workspace-sidebar" in stylesheet
    assert ".workspace-rail" in stylesheet
    assert ".page-head" in stylesheet


def test_workspace_script_defines_sidebar_storage_and_toggle_helpers():
    script = Path("static/js/workspace.js").read_text(encoding="utf-8")
    assert "WORKSPACE_SIDEBAR_STORAGE_KEY" in script
    assert "toggleWorkspaceSidebar" in script


def test_workspace_base_template_wires_sidebar_and_rendered_workspace_script_version():
    base_template = Path("templates/_workspace_base.html").read_text(encoding="utf-8")
    assert '{% include "_workspace_sidebar.html" %}' in base_template
    assert 'id="workspace-sidebar-toggle"' in base_template
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


def test_page_shell_source_defines_grouped_navigation_keys():
    source = Path("src/web/page_shell.py").read_text(encoding="utf-8")
    assert "WORKSPACE_NAV" in source
    for key in (
        "dashboard",
        "registration_workbench",
        "accounts",
        "scheduled_tasks",
        "registration_experiments",
        "settings",
    ):
        assert key in source
