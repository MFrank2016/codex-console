const WORKSPACE_SIDEBAR_STORAGE_KEY = 'codex-console.workspace.sidebar';
const WORKSPACE_THEME_STORAGE_KEY = 'theme';

function applyWorkspaceSidebarState(isCollapsed) {
  document.body.classList.toggle('workspace-sidebar-collapsed', Boolean(isCollapsed));
}

function updateWorkspaceThemeButtons(themeName) {
  const buttons = document.querySelectorAll('.theme-toggle');
  buttons.forEach((button) => {
    button.textContent = themeName === 'dark' ? '☀️' : '🌙';
    button.title = themeName === 'dark' ? '切换到亮色模式' : '切换到暗色模式';
  });
}

function applyWorkspaceTheme(themeName) {
  document.documentElement.setAttribute('data-theme', themeName);
  updateWorkspaceThemeButtons(themeName);
}

function getStoredWorkspaceTheme() {
  return localStorage.getItem(WORKSPACE_THEME_STORAGE_KEY) || 'light';
}

function restoreWorkspaceTheme() {
  applyWorkspaceTheme(getStoredWorkspaceTheme());
}

function toggleWorkspaceTheme() {
  const currentTheme = getStoredWorkspaceTheme();
  const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
  localStorage.setItem(WORKSPACE_THEME_STORAGE_KEY, nextTheme);
  applyWorkspaceTheme(nextTheme);
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

  try {
    restoreWorkspaceTheme();
  } catch (error) {
    console.warn('restoreWorkspaceTheme failed', error);
    applyWorkspaceTheme('light');
  }

  const toggleButton = document.getElementById('workspace-sidebar-toggle');
  const themeButton = document.getElementById('workspace-theme-toggle');

  if (toggleButton) {
    toggleButton.addEventListener('click', () => {
      try {
        toggleWorkspaceSidebar();
      } catch (error) {
        console.warn('toggleWorkspaceSidebar failed', error);
      }
    });
  }

  if (themeButton) {
    themeButton.addEventListener('click', () => {
      try {
        toggleWorkspaceTheme();
      } catch (error) {
        console.warn('toggleWorkspaceTheme failed', error);
      }
    });
  }
});
