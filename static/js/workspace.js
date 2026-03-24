const WORKSPACE_SIDEBAR_STORAGE_KEY = 'codex-console.workspace.sidebar';

function applyWorkspaceSidebarState(isCollapsed) {
  document.body.classList.toggle('workspace-sidebar-collapsed', Boolean(isCollapsed));
}

function toggleWorkspaceSidebar() {
  const next = !document.body.classList.contains('workspace-sidebar-collapsed');
  localStorage.setItem(
    WORKSPACE_SIDEBAR_STORAGE_KEY,
    next ? 'collapsed' : 'expanded',
  );
  applyWorkspaceSidebarState(next);
}

function restoreWorkspaceSidebarState() {
  const value = localStorage.getItem(WORKSPACE_SIDEBAR_STORAGE_KEY);
  applyWorkspaceSidebarState(value === 'collapsed');
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    restoreWorkspaceSidebarState();
  } catch (error) {
    console.warn('restoreWorkspaceSidebarState failed', error);
    applyWorkspaceSidebarState(false);
  }

  const toggleButton = document.getElementById('workspace-sidebar-toggle');
  if (!toggleButton) {
    return;
  }

  toggleButton.addEventListener('click', () => {
    try {
      toggleWorkspaceSidebar();
    } catch (error) {
      console.warn('toggleWorkspaceSidebar failed', error);
    }
  });
});
