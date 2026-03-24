from pathlib import Path


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
