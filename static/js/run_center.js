(function initRunCenterPage() {
    const runCenterElements = {
        root: document.getElementById('run-center-page'),
        scopeInput: document.getElementById('run-center-control-scope'),
        contextLink: document.getElementById('run-center-context-link'),
        openContextBtn: document.getElementById('run-center-open-context-btn'),
        retryBtn: document.getElementById('run-center-retry-btn'),
        summaryScope: document.getElementById('run-center-summary-scope'),
        summarySource: document.getElementById('run-center-summary-source'),
        runsBody: document.getElementById('scheduled-runs-table-body'),
        filterTaskTypeInput: document.getElementById('scheduled-run-filter-task-type'),
        filterStatusInput: document.getElementById('scheduled-run-filter-status'),
        filterStartedFromInput: document.getElementById('scheduled-run-filter-started-from'),
        filterStartedToInput: document.getElementById('scheduled-run-filter-started-to'),
        filterApplyBtn: document.getElementById('scheduled-run-filter-apply-btn'),
        filterResetBtn: document.getElementById('scheduled-run-filter-reset-btn'),
        paginationSummary: document.getElementById('scheduled-run-pagination-summary'),
        prevPageBtn: document.getElementById('scheduled-run-prev-page'),
        nextPageBtn: document.getElementById('scheduled-run-next-page'),
        pageJumpInput: document.getElementById('scheduled-run-page-jump-input'),
        pageJumpBtn: document.getElementById('scheduled-run-page-jump-btn'),
        runLogModal: document.getElementById('run-log-modal'),
        runLogStatusBar: document.getElementById('run-log-status-bar'),
        runLogRefreshBtn: document.getElementById('run-log-refresh-btn'),
        runLogStopBtn: document.getElementById('run-log-stop-btn'),
        runLogConsole: document.getElementById('run-log-console'),
    };

    const pageState = {
        context: { scope: 'scheduled', source: 'scheduled-tasks', plan_id: '' },
        filters: {
            taskType: '',
            status: '',
            startedFrom: '',
            startedTo: '',
            page: 1,
            pageSize: 20,
        },
        pagination: {
            total: 0,
            page: 1,
            pageSize: 20,
        },
        runsCache: [],
        activeRunId: null,
        activeRunDetail: null,
        currentLogOffset: 0,
        logPollingTimer: null,
        logPollingInFlight: false,
        logLoadToken: 0,
        logLines: [],
        pendingLineText: '',
    };

    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isPlainObject(value) {
        return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
    }

    function withButtonBusy(button, action) {
        if (!button || typeof action !== 'function') {
            return Promise.resolve(action ? action() : undefined);
        }
        const wasDisabled = Boolean(button.disabled);
        button.disabled = true;
        return Promise.resolve()
            .then(() => action())
            .finally(() => {
                button.disabled = wasDisabled;
            });
    }

    function getShared() {
        return window.runCenterShared || {};
    }

    function getScopeLabel(controlScope) {
        if (controlScope === 'task') return '单任务上下文';
        if (controlScope === 'batch') return '批量上下文';
        return '计划上下文';
    }

    function getTaskTypeText(type) {
        if (type === 'cpa_cleanup') return 'CPA 清理';
        if (type === 'cpa_refill') return 'CPA 补量';
        if (type === 'account_refresh') return '账号刷新';
        return escapeHtml(type || '-');
    }

    function getRunStatusText(status) {
        const normalized = String(status || '').trim().toLowerCase();
        if (normalized === 'pending') return '待执行';
        if (normalized === 'running') return '运行中';
        if (normalized === 'success' || normalized === 'completed') return '成功';
        if (normalized === 'failed' || normalized === 'error') return '失败';
        if (normalized === 'cancelled') return '已取消';
        if (normalized === 'stopping') return '停止中';
        if (normalized === 'skipped') return '已跳过';
        return normalized ? escapeHtml(normalized) : '-';
    }

    function getScheduledRunUiStatus(run) {
        if (!run) return 'pending';
        if (run.stop_requested_at && String(run.status || '').toLowerCase() === 'running') {
            return 'stopping';
        }
        return String(run.status || 'pending').trim().toLowerCase() || 'pending';
    }

    function toSummaryCount(value) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return 0;
        return Math.max(0, Math.floor(parsed));
    }

    function formatSummaryCountOrDash(value) {
        if (value === null || value === undefined || value === '') return '-';
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) return '-';
        return String(Math.max(0, Math.floor(parsed)));
    }

    function formatScheduledRunReason(run) {
        const rawReason = String(run?.error_message || '').trim();
        if (rawReason) {
            return rawReason.length > 32 ? `${rawReason.slice(0, 32)}…` : rawReason;
        }
        const uiStatus = getScheduledRunUiStatus(run);
        if (uiStatus === 'cancelled') return '用户停止';
        if (uiStatus === 'stopping') return '停止中';
        if (uiStatus === 'failed') return '执行失败';
        return '';
    }

    function buildScheduledRunSummaryBase(run) {
        const summary = isPlainObject(run?.summary) ? run.summary : {};
        const taskType = run?.task_type;

        if (taskType === 'cpa_refill') {
            return `补号 ${toSummaryCount(summary.uploaded_success)}`;
        }
        if (taskType === 'cpa_cleanup') {
            const detectedCount = summary.probe_items_scanned
                ?? summary.probe_items_selected
                ?? summary.invalid_items_considered
                ?? summary.invalid_items_found;
            return (
                `扫描 ${formatSummaryCountOrDash(detectedCount)} · ` +
                `清理 ${formatSummaryCountOrDash(summary.remote_deleted)} · ` +
                `剩余 ${formatSummaryCountOrDash(summary.remaining_valid_count)}`
            );
        }
        if (taskType === 'account_refresh') {
            return (
                `处理 ${toSummaryCount(summary.processed)} · ` +
                `刷新 ${toSummaryCount(summary.refreshed_success)} · ` +
                `上传 ${toSummaryCount(summary.uploaded_success)}`
            );
        }
        if (run?.summary && Object.keys(run.summary).length > 0) {
            try {
                return JSON.stringify(run.summary);
            } catch (error) {
                return String(run.summary);
            }
        }
        return '-';
    }

    function summarizeScheduledRun(run) {
        const baseSummary = buildScheduledRunSummaryBase(run);
        const uiStatus = getScheduledRunUiStatus(run);
        if (['failed', 'cancelled', 'stopping'].includes(uiStatus)) {
            const reason = formatScheduledRunReason(run);
            if (reason) {
                return `${baseSummary} · 原因：${reason}`;
            }
        }
        return baseSummary;
    }

    function highlightScheduledRunSummaryNumbers(summaryText) {
        const safeSummaryText = escapeHtml(summaryText || '-');
        return safeSummaryText.replace(/\d+(?:\.\d+)?/g, (matched) => (
            `<span class="scheduled-run-summary-number">${matched}</span>`
        ));
    }

    function renderScheduledRunSummaryHtml(run) {
        const uiStatus = getScheduledRunUiStatus(run);
        const summaryText = summarizeScheduledRun(run);
        const safeSummaryText = escapeHtml(summaryText || '-');
        return `
            <div
                class="scheduled-run-summary"
                data-summary-state="${escapeHtml(uiStatus || 'default')}"
                data-summary-text="${safeSummaryText}"
                title="${safeSummaryText}"
            >${highlightScheduledRunSummaryNumbers(summaryText)}</div>
        `;
    }

    function syncFiltersToInputs() {
        if (runCenterElements.filterTaskTypeInput) {
            runCenterElements.filterTaskTypeInput.value = pageState.filters.taskType || '';
        }
        if (runCenterElements.filterStatusInput) {
            runCenterElements.filterStatusInput.value = pageState.filters.status || '';
        }
        if (runCenterElements.filterStartedFromInput) {
            runCenterElements.filterStartedFromInput.value = pageState.filters.startedFrom || '';
        }
        if (runCenterElements.filterStartedToInput) {
            runCenterElements.filterStartedToInput.value = pageState.filters.startedTo || '';
        }
    }

    function updateFiltersFromInputs() {
        pageState.filters = {
            ...pageState.filters,
            taskType: runCenterElements.filterTaskTypeInput?.value || '',
            status: runCenterElements.filterStatusInput?.value || '',
            startedFrom: runCenterElements.filterStartedFromInput?.value || '',
            startedTo: runCenterElements.filterStartedToInput?.value || '',
            page: 1,
        };
    }

    function getTotalPages(total = pageState.pagination.total, pageSize = pageState.filters.pageSize || 20) {
        const safeTotal = Number.isFinite(Number(total)) ? Math.max(0, Number(total)) : 0;
        const safePageSize = Number.isFinite(Number(pageSize)) ? Math.max(1, Number(pageSize)) : 20;
        return Math.max(1, Math.ceil(safeTotal / safePageSize));
    }

    function updatePaginationControls() {
        const total = Number.isFinite(Number(pageState.pagination.total))
            ? Math.max(0, Number(pageState.pagination.total))
            : 0;
        const hasData = total > 0;
        const pageSize = Number.isFinite(Number(pageState.filters.pageSize))
            ? Math.max(1, Number(pageState.filters.pageSize))
            : 20;
        const totalPages = getTotalPages(total, pageSize);
        const currentPage = Math.min(Math.max(1, Number(pageState.filters.page) || 1), totalPages);

        pageState.filters = {
            ...pageState.filters,
            page: currentPage,
            pageSize,
        };
        pageState.pagination = {
            ...pageState.pagination,
            total,
            page: currentPage,
            pageSize,
        };

        if (runCenterElements.paginationSummary) {
            runCenterElements.paginationSummary.textContent = `第 ${currentPage} / ${totalPages} 页 · 共 ${total} 条`;
        }
        if (runCenterElements.pageJumpInput) {
            runCenterElements.pageJumpInput.max = String(totalPages);
            runCenterElements.pageJumpInput.disabled = !hasData;
            if (document.activeElement !== runCenterElements.pageJumpInput) {
                runCenterElements.pageJumpInput.value = String(currentPage);
            }
        }
        if (runCenterElements.prevPageBtn) {
            runCenterElements.prevPageBtn.disabled = !hasData || currentPage <= 1;
        }
        if (runCenterElements.nextPageBtn) {
            runCenterElements.nextPageBtn.disabled = !hasData || currentPage >= totalPages;
        }
        if (runCenterElements.pageJumpBtn) {
            runCenterElements.pageJumpBtn.disabled = !hasData;
        }
    }

    function resolveTargetPage(rawValue, totalPages = getTotalPages()) {
        const normalized = String(rawValue ?? '').trim();
        if (!/^\d+$/.test(normalized)) {
            return { valid: false, page: pageState.filters.page, clamped: false };
        }
        const requested = Number.parseInt(normalized, 10);
        const clamped = Math.min(Math.max(requested, 1), totalPages);
        return { valid: true, page: clamped, clamped: clamped !== requested };
    }

    function buildRunsPath() {
        const shared = getShared();
        if (typeof shared.buildRunsPath === 'function') {
            return shared.buildRunsPath(pageState.context, {
                task_type: pageState.filters.taskType,
                status: pageState.filters.status,
                started_from: pageState.filters.startedFrom,
                started_to: pageState.filters.startedTo,
                page: pageState.filters.page,
                page_size: pageState.filters.pageSize,
            });
        }
        return '/scheduled-runs?page=1&page_size=20';
    }

    function renderRuns(runs) {
        const tbody = runCenterElements.runsBody;
        if (!tbody) return;
        const rows = Array.isArray(runs) ? runs : [];
        if (rows.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9">
                        <div class="empty-state">
                            <div class="empty-state-icon">📭</div>
                            <div class="empty-state-title">暂无运行记录</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = rows.map((run) => {
            const uiStatus = getScheduledRunUiStatus(run);
            const stopAction = run.can_stop
                ? `<button class="btn btn-secondary btn-sm" data-run-action="stop-run" data-run-id="${escapeHtml(run.id)}" type="button">停止</button>`
                : '';
            return `
                <tr class="scheduled-run-row" data-run-id="${escapeHtml(run.id)}" data-run-state="${escapeHtml(uiStatus)}">
                    <td>${escapeHtml(run.id ?? '-')}</td>
                    <td>${escapeHtml(run.plan_name || `计划 #${run.plan_id || '-'}`)}</td>
                    <td>${getTaskTypeText(run.task_type)}</td>
                    <td>${escapeHtml(run.trigger_source || '-')}</td>
                    <td><span class="status-badge ${escapeHtml(uiStatus)}">${getRunStatusText(uiStatus)}</span></td>
                    <td class="scheduled-time-cell">${escapeHtml(format.date(run.started_at))}</td>
                    <td class="scheduled-time-cell">${escapeHtml(format.date(run.finished_at))}</td>
                    <td class="scheduled-run-summary-cell">${renderScheduledRunSummaryHtml(run)}</td>
                    <td>
                        <div class="table-actions table-actions--compact">
                            <button class="btn btn-secondary btn-sm" data-run-action="view-run-log" data-run-id="${escapeHtml(run.id)}" type="button">日志</button>
                            ${stopAction}
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    async function loadRuns() {
        const tbody = runCenterElements.runsBody;
        if (!tbody) return;
        try {
            const payload = await api.get(buildRunsPath());
            pageState.runsCache = Array.isArray(payload?.items) ? payload.items : [];
            const total = Number.isFinite(Number(payload?.total)) ? Math.max(0, Number(payload.total)) : 0;
            const pageSize = Number.isFinite(Number(payload?.page_size))
                ? Math.max(1, Number(payload.page_size))
                : Math.max(1, Number(pageState.filters.pageSize) || 20);
            const totalPages = getTotalPages(total, pageSize);
            const pageFromResponse = Number.isFinite(Number(payload?.page)) ? Number(payload.page) : Number(pageState.filters.page) || 1;
            const nextPage = Math.min(Math.max(1, pageFromResponse), totalPages);
            pageState.filters = { ...pageState.filters, page: nextPage, pageSize };
            pageState.pagination = { total, page: nextPage, pageSize };
            renderRuns(pageState.runsCache);
            updatePaginationControls();
        } catch (error) {
            pageState.pagination = { ...pageState.pagination, total: 0 };
            updatePaginationControls();
            tbody.innerHTML = `
                <tr>
                    <td colspan="9">
                        <div class="empty-state">
                            <div class="empty-state-icon">❌</div>
                            <div class="empty-state-title">运行记录加载失败</div>
                            <div class="empty-state-description">${escapeHtml(error?.message || '请求失败')}</div>
                        </div>
                    </td>
                </tr>
            `;
        }
    }

    async function applyFilters() {
        updateFiltersFromInputs();
        await loadRuns();
    }

    async function resetFilters() {
        pageState.filters = {
            ...pageState.filters,
            taskType: '',
            status: '',
            startedFrom: '',
            startedTo: '',
            page: 1,
        };
        syncFiltersToInputs();
        await loadRuns();
    }

    async function jumpToPage(rawValue, { showWarnings = true } = {}) {
        const result = resolveTargetPage(rawValue);
        if (!result.valid) {
            if (showWarnings) {
                toast.warning?.('请输入有效页码');
            }
            return;
        }
        if (result.clamped && showWarnings) {
            toast.warning?.(`页码已自动调整到 ${result.page}`);
        }
        if (result.page === pageState.filters.page) {
            updatePaginationControls();
            return;
        }
        pageState.filters = {
            ...pageState.filters,
            page: result.page,
        };
        await loadRuns();
    }

    function stopLogPolling() {
        if (pageState.logPollingTimer) {
            clearTimeout(pageState.logPollingTimer);
            pageState.logPollingTimer = null;
        }
    }

    function isActiveLogRequest(runId, token) {
        return token === pageState.logLoadToken && pageState.activeRunId === Number(runId);
    }

    function parseLogLines(text) {
        const normalized = String(text || '').replace(/\r\n/g, '\n');
        if (!normalized) return [];
        return normalized
            .split('\n')
            .filter((line, index, lines) => line !== '' || index < lines.length - 1)
            .map((line) => {
                const match = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3})?) \[(INFO|WARN|ERROR)\]\s?(.*)$/);
                if (!match) {
                    return { raw: line, timestamp: '', level: '', message: line };
                }
                return { raw: line, timestamp: match[1], level: match[2], message: match[3] || '' };
            });
    }

    function renderLogConsole() {
        if (!runCenterElements.runLogConsole) return;
        if (pageState.logLines.length === 0 && !pageState.pendingLineText) {
            runCenterElements.runLogConsole.innerHTML = '暂无记录';
            return;
        }
        const lines = [...pageState.logLines];
        if (pageState.pendingLineText) {
            const pending = parseLogLines(pageState.pendingLineText)[0];
            if (pending) {
                lines.push(pending);
            }
        }
        runCenterElements.runLogConsole.innerHTML = lines.map((line) => {
            if (!line.level) {
                return `<div class="scheduled-run-log-line"><span>${escapeHtml(line.raw || '')}</span></div>`;
            }
            return `
                <div class="scheduled-run-log-line">
                    <span class="scheduled-run-log-timestamp">${escapeHtml(String(line.timestamp || '').slice(0, 19))}</span>
                    <span class="scheduled-run-log-level-badge scheduled-run-log-level-${escapeHtml(String(line.level).toLowerCase())}">${escapeHtml(line.level)}</span>
                    <span class="scheduled-run-log-message">${escapeHtml(line.message)}</span>
                </div>
            `;
        }).join('');
    }

    function appendLogChunk(chunk, { reset = false } = {}) {
        if (reset) {
            pageState.logLines = [];
            pageState.pendingLineText = '';
        }
        const incomingText = String(chunk || '').replace(/\r\n/g, '\n');
        if (!incomingText) {
            renderLogConsole();
            return;
        }
        const combinedText = `${pageState.pendingLineText}${incomingText}`;
        const parts = combinedText.split('\n');
        const endsWithNewline = combinedText.endsWith('\n');
        pageState.pendingLineText = endsWithNewline ? '' : (parts.pop() ?? '');
        const parsedLines = parts.length ? parseLogLines(parts.join('\n')) : [];
        if (parsedLines.length) {
            pageState.logLines.push(...parsedLines);
        }
        renderLogConsole();
    }

    function renderLogStatusBar(detail) {
        if (!runCenterElements.runLogStatusBar) return;
        if (!detail) {
            runCenterElements.runLogStatusBar.innerHTML = '<span>未选择运行记录</span>';
            return;
        }
        const uiStatus = getScheduledRunUiStatus(detail);
        runCenterElements.runLogStatusBar.innerHTML = `
            <div class="scheduled-run-meta-bar">
                <span><strong>Run #${escapeHtml(detail.id)}</strong> · ${escapeHtml(detail.plan_name || `计划 #${detail.plan_id || '-'}`)}</span>
                <span>状态：<strong>${getRunStatusText(uiStatus)}</strong></span>
                <span>最后日志：${escapeHtml(format.date(detail.last_log_at))}</span>
            </div>
        `;
    }

    function setStopButtonState(detail) {
        const button = runCenterElements.runLogStopBtn;
        if (!button) return;
        if (!detail || (!detail.is_running && !detail.stop_requested_at)) {
            button.style.display = 'none';
            button.disabled = false;
            button.textContent = '停止';
            delete button.dataset.runId;
            return;
        }
        button.style.display = '';
        button.dataset.runId = String(detail.id);
        if (detail.stop_requested_at) {
            button.textContent = '停止中';
            button.disabled = true;
            return;
        }
        button.textContent = '停止';
        button.disabled = false;
    }

    async function loadRunLogChunk(runId, { reset = false, token = pageState.logLoadToken } = {}) {
        const targetId = Number(runId);
        if (!Number.isInteger(targetId) || targetId <= 0) return null;
        const offset = reset ? 0 : pageState.currentLogOffset;
        const data = await api.get(`/scheduled-runs/${targetId}/logs?offset=${offset}`);
        if (!isActiveLogRequest(targetId, token)) {
            return null;
        }
        pageState.currentLogOffset = Number(data?.next_offset || 0);
        if (pageState.activeRunDetail && Number(pageState.activeRunDetail.id) === targetId) {
            pageState.activeRunDetail = {
                ...pageState.activeRunDetail,
                status: data?.status || pageState.activeRunDetail.status,
                stop_requested_at: data?.stop_requested_at || pageState.activeRunDetail.stop_requested_at || null,
                last_log_at: data?.last_log_at || pageState.activeRunDetail.last_log_at || null,
                is_running: Boolean(data?.is_running),
                can_stop: Boolean(data?.is_running) && !data?.stop_requested_at,
            };
            renderLogStatusBar(pageState.activeRunDetail);
            setStopButtonState(pageState.activeRunDetail);
        }
        appendLogChunk(data?.chunk || '', { reset });
        return data;
    }

    function resetLogState() {
        pageState.logLoadToken += 1;
        pageState.activeRunId = null;
        pageState.activeRunDetail = null;
        pageState.currentLogOffset = 0;
        pageState.logLines = [];
        pageState.pendingLineText = '';
        pageState.logPollingInFlight = false;
        stopLogPolling();
        renderLogStatusBar(null);
        renderLogConsole();
        setStopButtonState(null);
    }

    function scheduleLogPolling(runId, token) {
        pageState.logPollingTimer = setTimeout(async () => {
            if (!isActiveLogRequest(runId, token)) {
                stopLogPolling();
                return;
            }
            if (pageState.logPollingInFlight) {
                scheduleLogPolling(runId, token);
                return;
            }
            pageState.logPollingInFlight = true;
            try {
                const data = await loadRunLogChunk(runId, { token });
                if (data?.is_running && isActiveLogRequest(runId, token)) {
                    scheduleLogPolling(runId, token);
                } else {
                    stopLogPolling();
                }
            } catch (error) {
                stopLogPolling();
            } finally {
                pageState.logPollingInFlight = false;
            }
        }, 2000);
        if (typeof pageState.logPollingTimer?.unref === 'function') {
            pageState.logPollingTimer.unref();
        }
    }

    async function openRunLog(runId) {
        const targetId = Number(runId);
        if (!Number.isInteger(targetId) || targetId <= 0) return;
        resetLogState();
        pageState.activeRunId = targetId;
        const token = pageState.logLoadToken;
        if (runCenterElements.runLogModal) {
            runCenterElements.runLogModal.classList.add('active');
        }
        try {
            const detail = await api.get(`/scheduled-runs/${targetId}`);
            if (!isActiveLogRequest(targetId, token)) {
                return;
            }
            pageState.activeRunDetail = detail;
            renderLogStatusBar(detail);
            setStopButtonState(detail);
            const logChunk = await loadRunLogChunk(targetId, { reset: true, token });
            if (!isActiveLogRequest(targetId, token)) {
                return;
            }
            if (logChunk?.is_running) {
                scheduleLogPolling(targetId, token);
            }
        } catch (error) {
            if (!isActiveLogRequest(targetId, token)) {
                return;
            }
            renderLogStatusBar(null);
            if (runCenterElements.runLogConsole) {
                runCenterElements.runLogConsole.innerHTML = `<div style="color: var(--danger-color, #d9534f);">${escapeHtml(error?.message || '加载运行日志失败')}</div>`;
            }
            toast.error?.(`加载运行日志失败: ${error?.message || '请求失败'}`);
        }
    }

    async function stopRun(runId) {
        const targetId = Number(runId);
        if (!Number.isInteger(targetId) || targetId <= 0) return;
        try {
            await api.post(`/scheduled-runs/${targetId}/stop`, {});
            const optimisticStopRequestedAt = new Date().toISOString();
            pageState.runsCache = pageState.runsCache.map((run) => (
                Number(run.id) === targetId
                    ? { ...run, stop_requested_at: optimisticStopRequestedAt, can_stop: false }
                    : run
            ));
            renderRuns(pageState.runsCache);
            if (pageState.activeRunDetail && Number(pageState.activeRunDetail.id) === targetId) {
                pageState.activeRunDetail = {
                    ...pageState.activeRunDetail,
                    stop_requested_at: optimisticStopRequestedAt,
                    can_stop: false,
                    is_running: true,
                };
                renderLogStatusBar(pageState.activeRunDetail);
                setStopButtonState(pageState.activeRunDetail);
            }
            toast.success?.('已发送停止请求');
        } catch (error) {
            toast.error?.(`停止失败: ${error?.message || '请求失败'}`);
        }
    }

    function closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;
        if (modalId === 'run-log-modal') {
            resetLogState();
        }
        modal.classList.remove('active');
    }

    function resolveActionButton(target) {
        if (!target) return null;
        if (typeof target.closest === 'function') {
            return target.closest('[data-run-action]');
        }
        return target.dataset?.runAction ? target : null;
    }

    function bindEvents() {
        if (runCenterElements.openContextBtn) {
            runCenterElements.openContextBtn.addEventListener('click', (event) => {
                event.preventDefault();
                const href = runCenterElements.contextLink?.href || '#';
                if (href && window.location && typeof window.location.assign === 'function') {
                    window.location.assign(href);
                }
            });
        }
        if (runCenterElements.retryBtn) {
            runCenterElements.retryBtn.addEventListener('click', (event) => {
                event.preventDefault();
                const shared = getShared();
                const href = typeof shared.buildRetryHref === 'function'
                    ? shared.buildRetryHref(pageState.context)
                    : '/scheduled-tasks?retry=1';
                if (href && window.location && typeof window.location.assign === 'function') {
                    window.location.assign(href);
                }
            });
        }
        if (runCenterElements.filterApplyBtn) {
            runCenterElements.filterApplyBtn.addEventListener('click', (event) => {
                void withButtonBusy(event.currentTarget, () => applyFilters());
            });
        }
        if (runCenterElements.filterResetBtn) {
            runCenterElements.filterResetBtn.addEventListener('click', (event) => {
                void withButtonBusy(event.currentTarget, () => resetFilters());
            });
        }
        if (runCenterElements.prevPageBtn) {
            runCenterElements.prevPageBtn.addEventListener('click', (event) => {
                event.preventDefault();
                void withButtonBusy(event.currentTarget, () => jumpToPage(String((pageState.filters.page || 1) - 1)));
            });
        }
        if (runCenterElements.nextPageBtn) {
            runCenterElements.nextPageBtn.addEventListener('click', (event) => {
                event.preventDefault();
                void withButtonBusy(event.currentTarget, () => jumpToPage(String((pageState.filters.page || 1) + 1)));
            });
        }
        if (runCenterElements.pageJumpBtn) {
            runCenterElements.pageJumpBtn.addEventListener('click', (event) => {
                event.preventDefault();
                void withButtonBusy(event.currentTarget, () => jumpToPage(runCenterElements.pageJumpInput?.value || ''));
            });
        }
        if (runCenterElements.pageJumpInput) {
            runCenterElements.pageJumpInput.addEventListener('keydown', (event) => {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                void jumpToPage(runCenterElements.pageJumpInput?.value || '');
            });
        }
        if (runCenterElements.runsBody) {
            runCenterElements.runsBody.addEventListener('click', (event) => {
                const button = resolveActionButton(event.target);
                if (!button) return;
                const action = button.dataset?.runAction;
                const runId = Number.parseInt(button.dataset?.runId || '', 10);
                if (action === 'view-run-log') {
                    void withButtonBusy(button, () => openRunLog(runId));
                }
                if (action === 'stop-run') {
                    void withButtonBusy(button, () => stopRun(runId));
                }
            });
        }
        if (runCenterElements.runLogRefreshBtn) {
            runCenterElements.runLogRefreshBtn.addEventListener('click', (event) => {
                if (!pageState.activeRunId) return;
                void withButtonBusy(event.currentTarget, () => openRunLog(pageState.activeRunId));
            });
        }
        if (runCenterElements.runLogStopBtn) {
            runCenterElements.runLogStopBtn.addEventListener('click', (event) => {
                const runId = Number.parseInt(runCenterElements.runLogStopBtn?.dataset?.runId || '', 10);
                void withButtonBusy(event.currentTarget, () => stopRun(runId));
            });
        }
        if (typeof document.querySelectorAll === 'function') {
            document.querySelectorAll('[data-close-modal]').forEach((btn) => {
                btn.addEventListener('click', (event) => {
                    void withButtonBusy(event.currentTarget, () => closeModal(btn.dataset.closeModal));
                });
            });
        }
        [runCenterElements.runLogModal].forEach((modal) => {
            if (!modal) return;
            modal.addEventListener('click', (event) => {
                if (event.target === modal) {
                    closeModal(modal.id);
                }
            });
        });
    }

    async function bootstrap() {
        const root = runCenterElements.root;
        if (!root || root.dataset.initialized === 'true') {
            return;
        }
        root.dataset.initialized = 'true';

        const shared = getShared();
        const parseContext = typeof shared.parseContext === 'function'
            ? shared.parseContext
            : (() => ({ scope: 'scheduled', source: 'scheduled-tasks', plan_id: '' }));
        const buildContextHref = typeof shared.buildContextHref === 'function'
            ? shared.buildContextHref
            : (() => '/scheduled-tasks');

        pageState.context = parseContext(window.location?.search || '');
        const contextHref = buildContextHref(pageState.context);

        if (runCenterElements.scopeInput) {
            runCenterElements.scopeInput.value = pageState.context.scope || 'scheduled';
            runCenterElements.scopeInput.dataset.scope = pageState.context.scope || 'scheduled';
        }
        if (runCenterElements.contextLink) {
            runCenterElements.contextLink.href = contextHref;
            runCenterElements.contextLink.textContent = pageState.context.scope === 'scheduled' ? '返回计划管理' : '返回注册工作台';
        }
        if (runCenterElements.summaryScope) {
            runCenterElements.summaryScope.textContent = getScopeLabel(pageState.context.scope);
        }
        if (runCenterElements.summarySource) {
            runCenterElements.summarySource.textContent = pageState.context.source || 'run-center';
        }
        syncFiltersToInputs();
        updatePaginationControls();
        bindEvents();
        await loadRuns();
        root.dataset.pageReady = 'true';
    }

    window.runCenterPage = {
        bootstrap,
        applyFilters,
        resetFilters,
        jumpToPage,
        loadRuns,
        openRunLog,
        stopRun,
        closeModal,
    };

    document.addEventListener('DOMContentLoaded', () => {
        void bootstrap();
    });
    void bootstrap();
})();
