function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeHref(rawHref) {
  const href = String(rawHref ?? '').trim();
  if (href.startsWith('//')) return '#';
  if (href.startsWith('/')) return href;
  if (/^https?:\/\//i.test(href)) return href;
  return '#';
}

function normalizeToneToken(value) {
  const token = String(value ?? '').trim().toLowerCase();
  return /^[a-z0-9-]+$/.test(token) ? token : '';
}

function renderMetricCard(label, value, hint = '', tone = '') {
  const hintHtml = hint ? `<p class="dashboard-metric-hint">${escapeHtml(hint)}</p>` : '';
  const toneKey = normalizeToneToken(tone);
  const toneClass = toneKey ? ` dashboard-metric-card--${toneKey}` : '';
  const badgeToneClass = toneKey ? ` dashboard-metric-value-badge--${toneKey}` : '';
  return `
    <article class="dashboard-metric-card${toneClass}">
      <p class="dashboard-metric-label">${escapeHtml(label)}</p>
      <p class="dashboard-metric-value">
        <span class="dashboard-metric-value-badge${badgeToneClass}">${escapeHtml(value)}</span>
      </p>
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

  return [
    renderMetricCard('注册任务', totalTasks, `运行中 ${registration.running ?? 0}`, 'registration'),
    renderMetricCard('成功率', successRate, `失败 ${registration.failed ?? 0}`, 'success-rate'),
    renderMetricCard('账号', accounts.total ?? 0, `活跃 ${accounts.active ?? 0}`, 'accounts'),
    renderMetricCard('定时计划', scheduled.plans_total ?? 0, `启用 ${scheduled.plans_enabled ?? 0}`, 'scheduled'),
  ].join('');
}

function renderRecentActivity(items) {
  const normalized = Array.isArray(items) ? items : [];
  if (!normalized.length) {
    return '<li class="dashboard-empty">暂无最近活动。</li>';
  }

  return normalized
    .map((item) => `
      <li class="dashboard-activity-item">
        <a href="${escapeHtml(safeHref(item?.href))}">${escapeHtml(item?.title || '未命名活动')}</a>
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
    .map((link, index) => {
      const variant = index === 0 ? 'primary' : 'secondary';
      return `
      <a class="dashboard-quick-action dashboard-quick-action--${variant}" href="${escapeHtml(safeHref(link?.href))}">
        <p class="dashboard-quick-action-title">${escapeHtml(link?.label || '未命名动作')}</p>
        <p class="dashboard-quick-action-desc">${escapeHtml(link?.description || '')}</p>
      </a>
    `;
    })
    .join('');
}

function renderDashboardError(error) {
  const message = error instanceof Error ? error.message : '加载失败';
  const metricHtml = `<p class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</p>`;
  const listHtml = `<li class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</li>`;
  const actionHtml = `<p class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</p>`;

  const metricGrid = document.getElementById('dashboard-metric-grid');
  const activity = document.getElementById('dashboard-activity-feed');
  const actions = document.getElementById('dashboard-quick-actions');

  if (metricGrid) metricGrid.innerHTML = metricHtml;
  if (activity) activity.innerHTML = listHtml;
  if (actions) actions.innerHTML = actionHtml;
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
  const metricGrid = document.getElementById('dashboard-metric-grid');
  if (metricGrid) {
    metricGrid.innerHTML = renderDashboardHero(summary);
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
