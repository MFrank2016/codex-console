function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderMetricCard(label, value, hint = '') {
  const hintHtml = hint ? `<p class="dashboard-metric-hint">${escapeHtml(hint)}</p>` : '';
  return `
    <article class="dashboard-metric-card">
      <p class="dashboard-metric-label">${escapeHtml(label)}</p>
      <p class="dashboard-metric-value">${escapeHtml(value)}</p>
      ${hintHtml}
    </article>
  `;
}

function renderDashboardHero(summary) {
  const registration = summary.registration || {};
  const accounts = summary.accounts || {};
  const scheduled = summary.scheduled || {};
  const successRate = registration.success_rate == null ? '—' : `${registration.success_rate}%`;
  const totalTasks = registration.total_tasks ?? registration.total ?? 0;

  const metrics = [
    renderMetricCard('注册任务', totalTasks, `运行中 ${registration.running ?? 0}`),
    renderMetricCard('成功率', successRate, `失败 ${registration.failed ?? 0}`),
    renderMetricCard('账号', accounts.total ?? 0, `活跃 ${accounts.active ?? 0}`),
    renderMetricCard('定时计划', scheduled.plans_total ?? 0, `启用 ${scheduled.plans_enabled ?? 0}`),
  ].join('');

  return `
    <div class="dashboard-hero-copy">
      <h2 class="dashboard-hero-title">总览</h2>
      <p class="dashboard-hero-subtitle">快速了解当前运行状态与最近活动。</p>
    </div>
    <div id="dashboard-metric-grid" class="dashboard-metric-grid">
      ${metrics}
    </div>
  `;
}

function renderRecentActivity(items) {
  const normalized = Array.isArray(items) ? items : [];
  if (!normalized.length) {
    return '<li class="dashboard-activity-item"><span>暂无最近活动。</span></li>';
  }

  return normalized
    .map((item) => `
      <li class="dashboard-activity-item">
        <a href="${escapeHtml(item?.href || '#')}">${escapeHtml(item?.title || '未命名活动')}</a>
        <span class="dashboard-activity-status">${escapeHtml(item?.status || 'unknown')}</span>
      </li>
    `)
    .join('');
}

function renderQuickActions(links) {
  const normalized = Array.isArray(links) ? links : [];
  if (!normalized.length) {
    return '<p class="dashboard-empty">暂无快捷动作。</p>';
  }

  return normalized
    .map((link) => `
      <a class="dashboard-quick-action" href="${escapeHtml(link?.href || '#')}">
        <p class="dashboard-quick-action-title">${escapeHtml(link?.label || '未命名动作')}</p>
        <p class="dashboard-quick-action-desc">${escapeHtml(link?.description || '')}</p>
      </a>
    `)
    .join('');
}

function renderDashboardError(error) {
  const message = error instanceof Error ? error.message : '加载失败';
  const html = `<p>Dashboard 加载失败：${escapeHtml(message)}</p>`;

  const hero = document.getElementById('dashboard-hero-primary');
  const activity = document.getElementById('dashboard-activity-feed');
  const actions = document.getElementById('dashboard-quick-actions');

  if (hero) hero.innerHTML = html;
  if (activity) activity.innerHTML = html;
  if (actions) actions.innerHTML = html;
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

function mountDashboard(summary) {
  const hero = document.getElementById('dashboard-hero-primary');
  if (hero) {
    hero.innerHTML = renderDashboardHero(summary);
  }

  const activity = document.getElementById('dashboard-activity-feed');
  if (activity) {
    activity.innerHTML = renderRecentActivity(summary?.recent_activity);
  }

  const actions = document.getElementById('dashboard-quick-actions');
  if (actions) {
    actions.innerHTML = renderQuickActions(summary?.quick_links);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const summary = await loadDashboardSummary();
    mountDashboard(summary);
  } catch (error) {
    console.error('Failed to load dashboard summary', error);
    renderDashboardError(error);
  }
});
