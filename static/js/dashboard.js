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

function renderSummaryCard(label, value, hint = '') {
  return `
    <article class="dashboard-summary-card">
      <p class="dashboard-summary-label">${escapeHtml(label)}</p>
      <p class="dashboard-summary-value">${escapeHtml(value)}</p>
      <p class="dashboard-summary-hint">${escapeHtml(hint)}</p>
    </article>
  `;
}

function renderOverviewSummary(summary) {
  const registration = summary?.registration || {};
  const accounts = summary?.accounts || {};
  const scheduled = summary?.scheduled || {};
  const successRate = registration.success_rate == null ? '—' : `${registration.success_rate}%`;

  return [
    renderSummaryCard(
      '注册任务',
      registration.total_tasks ?? registration.total ?? 0,
      `运行中 ${registration.running ?? 0}`,
    ),
    renderSummaryCard('成功率', successRate, `失败 ${registration.failed ?? 0}`),
    renderSummaryCard('账号总数', accounts.total ?? 0, `活跃 ${accounts.active ?? 0}`),
    renderSummaryCard('计划任务', scheduled.plans_total ?? 0, `启用 ${scheduled.plans_enabled ?? 0}`),
  ].join('');
}

function renderOverviewAlerts(items) {
  const normalized = Array.isArray(items) ? items : [];
  if (!normalized.length) {
    return '<li class="dashboard-empty">暂无提醒。</li>';
  }

  return normalized
    .map((item) => `
      <li class="dashboard-alert-item">
        <a class="dashboard-alert-link" href="${escapeHtml(safeHref(item?.href))}">${escapeHtml(item?.title || '未命名动态')}</a>
        <span class="dashboard-alert-meta">${escapeHtml(item?.status || 'unknown')}</span>
      </li>
    `)
    .join('');
}

function renderOverviewLaunchpad(links) {
  const normalized = Array.isArray(links) ? links : [];
  if (!normalized.length) {
    return '<p class="dashboard-empty">暂无启动台入口。</p>';
  }

  return normalized
    .map((link, index) => {
      const variant = index === 0 ? ' dashboard-launchpad-card--primary' : '';
      return `
        <a class="dashboard-launchpad-card${variant}" href="${escapeHtml(safeHref(link?.href))}">
          <p class="dashboard-launchpad-title">${escapeHtml(link?.label || '未命名入口')}</p>
          <p class="dashboard-launchpad-desc">${escapeHtml(link?.description || '')}</p>
        </a>
      `;
    })
    .join('');
}

function getOverviewContainers() {
  return {
    summary: document.getElementById('dashboard-overview-summary'),
    alerts: document.getElementById('dashboard-overview-alerts'),
    launchpad: document.getElementById('dashboard-overview-launchpad'),
  };
}

function renderDashboardLoadingState() {
  const containers = getOverviewContainers();
  if (containers.summary) {
    containers.summary.innerHTML = '<p class="dashboard-loading">加载中...</p>';
  }
  if (containers.alerts) {
    containers.alerts.innerHTML = '<li class="dashboard-loading">加载中...</li>';
  }
  if (containers.launchpad) {
    containers.launchpad.innerHTML = '<p class="dashboard-loading">加载中...</p>';
  }
}

function renderDashboardError(error) {
  const message = error instanceof Error ? error.message : '加载失败';
  const containers = getOverviewContainers();
  if (containers.summary) {
    containers.summary.innerHTML = `<p class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</p>`;
  }
  if (containers.alerts) {
    containers.alerts.innerHTML = `<li class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</li>`;
  }
  if (containers.launchpad) {
    containers.launchpad.innerHTML = `<p class="dashboard-empty">Dashboard 加载失败：${escapeHtml(message)}</p>`;
  }
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
  const containers = getOverviewContainers();
  if (containers.summary) {
    containers.summary.innerHTML = renderOverviewSummary(summary);
  }
  if (containers.alerts) {
    containers.alerts.innerHTML = renderOverviewAlerts(summary?.recent_activity);
  }
  if (containers.launchpad) {
    containers.launchpad.innerHTML = renderOverviewLaunchpad(summary?.quick_links);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  renderDashboardLoadingState();
  try {
    const summary = await loadDashboardSummary();
    mountDashboard(summary);
  } catch (error) {
    console.error('Failed to load dashboard summary', error);
    renderDashboardError(error);
  }
});
