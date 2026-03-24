function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function metricCard(title, value, hint = '') {
  return `
    <article class="workspace-panel">
      <h3>${escapeHtml(title)}</h3>
      <p class="metric-value">${escapeHtml(value)}</p>
      <p class="metric-hint">${escapeHtml(hint)}</p>
    </article>
  `;
}

function renderDashboardHero(summary) {
  const container = document.getElementById('dashboard-hero');
  if (!container) return;

  const registration = summary.registration || {};
  const accounts = summary.accounts || {};
  const scheduled = summary.scheduled || {};
  const successRate = registration.success_rate == null ? '—' : `${registration.success_rate}%`;

  container.innerHTML = [
    metricCard('注册任务总数', registration.total ?? 0, `运行中 ${registration.running ?? 0}`),
    metricCard('注册成功率', successRate, `失败 ${registration.failed ?? 0}`),
    metricCard('账号总数', accounts.total ?? 0, `活跃 ${accounts.active ?? 0}`),
    metricCard('定时计划', scheduled.plans_total ?? 0, `启用 ${scheduled.plans_enabled ?? 0}`),
  ].join('');
}

function renderDashboardTaskHealth(summary) {
  const container = document.getElementById('dashboard-task-health');
  if (!container) return;

  const registration = summary.registration || {};
  const scheduled = summary.scheduled || {};

  container.innerHTML = `
    <h3>任务健康</h3>
    <ul>
      <li>待执行注册：${escapeHtml(registration.pending ?? 0)}</li>
      <li>执行中注册：${escapeHtml(registration.running ?? 0)}</li>
      <li>今日定时运行：${escapeHtml(scheduled.runs_today ?? 0)}</li>
      <li>运行中定时任务：${escapeHtml(scheduled.runs_running ?? 0)}</li>
      <li>失败定时任务：${escapeHtml(scheduled.runs_failed ?? 0)}</li>
    </ul>
  `;
}

function renderDashboardQuickLinks(summary) {
  const container = document.getElementById('dashboard-quick-links');
  if (!container) return;

  const links = Array.isArray(summary.quick_links) ? summary.quick_links : [];
  if (!links.length) {
    container.innerHTML = '<h3>快捷入口</h3><p>暂无可用入口。</p>';
    return;
  }

  const rows = links
    .map((link) => `
      <li>
        <a href="${escapeHtml(link.href || '#')}">${escapeHtml(link.label || '未命名入口')}</a>
        <p>${escapeHtml(link.description || '')}</p>
      </li>
    `)
    .join('');

  container.innerHTML = `<h3>快捷入口</h3><ul>${rows}</ul>`;
}

function renderDashboardRecentActivity(summary) {
  const container = document.getElementById('dashboard-recent-activity');
  if (!container) return;

  const items = Array.isArray(summary.recent_activity) ? summary.recent_activity : [];
  if (!items.length) {
    container.innerHTML = '<h3>最近活动</h3><p>暂无最近活动。</p>';
    return;
  }

  const listHtml = items
    .map((item) => `
      <li>
        <a href="${escapeHtml(item.href || '#')}">${escapeHtml(item.title || '未命名活动')}</a>
        <span>${escapeHtml(item.status || 'unknown')}</span>
        <small>${escapeHtml(item.description || '')}</small>
      </li>
    `)
    .join('');

  container.innerHTML = `<h3>最近活动</h3><ul>${listHtml}</ul>`;
}

function renderDashboardError(error) {
  const message = error instanceof Error ? error.message : '加载失败';
  const html = `<p>Dashboard 加载失败：${escapeHtml(message)}</p>`;

  const hero = document.getElementById('dashboard-hero');
  const taskHealth = document.getElementById('dashboard-task-health');
  const quickLinks = document.getElementById('dashboard-quick-links');
  const recentActivity = document.getElementById('dashboard-recent-activity');

  if (hero) hero.innerHTML = html;
  if (taskHealth) taskHealth.innerHTML = html;
  if (quickLinks) quickLinks.innerHTML = html;
  if (recentActivity) recentActivity.innerHTML = html;
}

async function loadDashboardSummary() {
  const response = await fetch('/api/dashboard/summary', {
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json();
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const summary = await loadDashboardSummary();
    renderDashboardHero(summary);
    renderDashboardTaskHealth(summary);
    renderDashboardQuickLinks(summary);
    renderDashboardRecentActivity(summary);
  } catch (error) {
    console.error('Failed to load dashboard summary', error);
    renderDashboardError(error);
  }
});
