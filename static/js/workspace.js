const WORKSPACE_SIDEBAR_STORAGE_KEY = 'codex-console.workspace.sidebar';
const WORKSPACE_THEME_STORAGE_KEY = 'theme';
const WORKSPACE_SIDEBAR_COLLAPSED_CLASS = 'workspace-sidebar-collapsed';
const WORKSPACE_THEME_DARK = 'dark';
const WORKSPACE_THEME_LIGHT = 'light';
const WORKSPACE_THEME_ICON_DARK = '<svg class="workspace-icon-svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M14 2a8 8 0 108 8 7 7 0 01-8-8z" fill="currentColor"></path></svg>';
const WORKSPACE_THEME_ICON_LIGHT = '<svg class="workspace-icon-svg" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path d="M12 4V2M12 22v-2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4M12 7a5 5 0 100 10 5 5 0 000-10z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path></svg>';

function isWorkspaceSidebarCollapsed() {
  const rootCollapsed = document.documentElement.classList.contains(
    WORKSPACE_SIDEBAR_COLLAPSED_CLASS,
  );
  const bodyCollapsed = Boolean(
    document.body && document.body.classList.contains(WORKSPACE_SIDEBAR_COLLAPSED_CLASS),
  );
  return rootCollapsed || bodyCollapsed;
}

function updateWorkspaceSidebarToggleButton(isCollapsed) {
  const toggleButton = document.getElementById('workspace-sidebar-toggle');
  if (!toggleButton) {
    return;
  }

  toggleButton.setAttribute('aria-pressed', isCollapsed ? 'true' : 'false');
  toggleButton.title = isCollapsed ? '展开侧边栏' : '折叠侧边栏';
}

function applyWorkspaceSidebarState(isCollapsed) {
  const collapsed = Boolean(isCollapsed);
  document.body.classList.toggle(WORKSPACE_SIDEBAR_COLLAPSED_CLASS, collapsed);
  document.documentElement.classList.toggle(WORKSPACE_SIDEBAR_COLLAPSED_CLASS, collapsed);
  updateWorkspaceSidebarToggleButton(collapsed);
}

function updateWorkspaceThemeButtons(themeName) {
  const useLightIcon = themeName === WORKSPACE_THEME_DARK;
  const iconMarkup = useLightIcon ? WORKSPACE_THEME_ICON_LIGHT : WORKSPACE_THEME_ICON_DARK;
  const iconName = useLightIcon ? 'theme-light' : 'theme-dark';
  const buttons = document.querySelectorAll('.theme-toggle');
  buttons.forEach((button) => {
    button.innerHTML = iconMarkup;
    button.setAttribute('data-theme-icon', iconName);
    button.title = useLightIcon ? '切换到亮色模式' : '切换到暗色模式';
  });
}

function applyWorkspaceTheme(themeName) {
  const normalizedTheme = themeName === WORKSPACE_THEME_DARK
    ? WORKSPACE_THEME_DARK
    : WORKSPACE_THEME_LIGHT;
  document.documentElement.setAttribute('data-theme', normalizedTheme);
  updateWorkspaceThemeButtons(normalizedTheme);
}

function getStoredWorkspaceTheme() {
  const theme = localStorage.getItem(WORKSPACE_THEME_STORAGE_KEY);
  if (theme === WORKSPACE_THEME_DARK || theme === WORKSPACE_THEME_LIGHT) {
    return theme;
  }
  return null;
}

function getCurrentWorkspaceTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme');
  if (currentTheme === WORKSPACE_THEME_DARK || currentTheme === WORKSPACE_THEME_LIGHT) {
    return currentTheme;
  }
  return WORKSPACE_THEME_LIGHT;
}

function restoreWorkspaceTheme() {
  applyWorkspaceTheme(getStoredWorkspaceTheme() || getCurrentWorkspaceTheme());
}

function toggleWorkspaceTheme() {
  const currentTheme = getCurrentWorkspaceTheme();
  const nextTheme = currentTheme === WORKSPACE_THEME_DARK
    ? WORKSPACE_THEME_LIGHT
    : WORKSPACE_THEME_DARK;
  localStorage.setItem(WORKSPACE_THEME_STORAGE_KEY, nextTheme);
  applyWorkspaceTheme(nextTheme);
}

function toggleWorkspaceSidebar() {
  const next = !isWorkspaceSidebarCollapsed();
  localStorage.setItem(
    WORKSPACE_SIDEBAR_STORAGE_KEY,
    next ? 'collapsed' : 'expanded',
  );
  applyWorkspaceSidebarState(next);
}

function restoreWorkspaceSidebarState() {
  const value = localStorage.getItem(WORKSPACE_SIDEBAR_STORAGE_KEY);
  if (value === 'collapsed') {
    applyWorkspaceSidebarState(true);
    return;
  }
  if (value === 'expanded') {
    applyWorkspaceSidebarState(false);
    return;
  }
  applyWorkspaceSidebarState(isWorkspaceSidebarCollapsed());
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    restoreWorkspaceSidebarState();
  } catch (error) {
    console.warn('restoreWorkspaceSidebarState failed', error);
    applyWorkspaceSidebarState(isWorkspaceSidebarCollapsed());
  }

  try {
    restoreWorkspaceTheme();
  } catch (error) {
    console.warn('restoreWorkspaceTheme failed', error);
    applyWorkspaceTheme(getCurrentWorkspaceTheme());
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
