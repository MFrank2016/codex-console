/**
 * 注册页面 JavaScript
 * 使用 utils.js 中的工具库
 */

// 状态
let currentTask = null;
let currentBatch = null;
let logPollingInterval = null;
let streamPollingInterval = null;
let streamPollingInFlight = false;
let batchPollingInterval = null;
let accountsPollingInterval = null;
let isBatchMode = false;
let isOutlookBatchMode = false;
let outlookAccounts = [];
let taskCompleted = false;  // 标记任务是否已完成
let batchCompleted = false;  // 标记批量任务是否已完成
let taskFinalStatus = null;  // 保存任务的最终状态
let batchFinalStatus = null;  // 保存批量任务的最终状态
let singleTaskStartedAtMs = null;
let batchTaskStartedAtMs = null;
let registrationRuntimeTicker = null;
let displayedLogs = new Set();  // 用于日志去重
let toastShown = false;  // 标记是否已显示过 toast
let availableServices = {
    tempmail: { available: true, services: [] },
    outlook: { available: false, services: [] },
    moe_mail: { available: false, services: [] },
    temp_mail: { available: false, services: [] },
    duck_mail: { available: false, services: [] },
    freemail: { available: false, services: [] }
};
const registrationFailureState = {
    page: 1,
    pageSize: 20,
    total: 0,
    filters: {},
    items: [],
};

// WebSocket 相关变量
let webSocket = null;
let batchWebSocket = null;  // 批量任务 WebSocket
let useWebSocket = true;  // 是否使用 WebSocket
let wsHeartbeatInterval = null;  // 心跳定时器
let batchWsHeartbeatInterval = null;  // 批量任务心跳定时器
let wsHandshakeTimeout = null;  // 单任务 WebSocket 握手超时
let batchWsHandshakeTimeout = null;  // 批量任务 WebSocket 握手超时
let activeTaskUuid = null;   // 当前活跃的单任务 UUID（用于页面重新可见时重连）
let activeBatchId = null;    // 当前活跃的批量任务 ID（用于页面重新可见时重连）
let registrationSharedConsoleController = null;
let registrationSharedStreamClient = null;
let registrationSharedPendingEvent = null;
let registrationLocalEventSeq = 0;
let activeWorkbenchView = 'config';
const REGISTRATION_WS_HANDSHAKE_TIMEOUT_MS = 2500;

function parseRegistrationTimestampMs(value) {
    if (!value) return null;
    const raw = String(value).trim();
    const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(raw)
        ? raw
        : (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw) ? `${raw}Z` : raw);
    const timestamp = Date.parse(normalized);
    return Number.isFinite(timestamp) ? timestamp : null;
}

function isBatchRegistrationModeSelected() {
    const mode = elements?.regMode?.value;
    return mode === 'batch' || mode === 'unlimited';
}

function normalizeTaskProxyIp(task) {
    const proxyIp = String(task?.proxy_ip || task?.result?.metadata?.proxy_ip || '').trim();
    return proxyIp || '—';
}

function isRateLimitText(value) {
    const text = String(value || '').toLowerCase();
    return text.includes('http 429')
        || text.includes('rate limit exceeded')
        || text.includes('rate_limit')
        || text.includes('too many requests')
        || text.includes('限流');
}

function isRateLimitFailureItem(item) {
    return isRateLimitText(item?.error_code) || isRateLimitText(item?.error_detail);
}

function buildRunCenterHref(context = {}) {
    const params = new URLSearchParams();
    const scope = String(context.scope || '').trim();
    const source = String(context.source || '').trim();

    if (scope) {
        params.set('scope', scope);
    }
    if (scope === 'task' && context.task_uuid) {
        params.set('task_uuid', String(context.task_uuid));
    }
    if (scope === 'batch' && context.batch_id) {
        params.set('batch_id', String(context.batch_id));
    }
    if (scope === 'scheduled') {
        if (context.plan_id) {
            params.set('plan_id', String(context.plan_id));
        }
        if (context.run_id) {
            params.set('run_id', String(context.run_id));
        }
    }
    if (source) {
        params.set('source', source);
    }

    const query = params.toString();
    return query ? `/run-center?${query}` : '/run-center';
}

if (typeof window !== 'undefined') {
    window.buildRunCenterHref = buildRunCenterHref;
}

function formatElapsedMsToClock(elapsedMs) {
    const safeMs = Number.isFinite(Number(elapsedMs)) ? Math.max(0, Number(elapsedMs)) : 0;
    const totalSeconds = Math.floor(safeMs / 1000);
    const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

function setSingleTaskElapsedText(value) {
    if (elements.singleProgressElapsed) {
        elements.singleProgressElapsed.textContent = value;
    }
}

function setBatchElapsedTexts(totalText, averageText) {
    if (elements.batchProgressElapsed) {
        elements.batchProgressElapsed.textContent = totalText;
    }
    if (elements.batchProgressAvgElapsed) {
        elements.batchProgressAvgElapsed.textContent = averageText;
    }
}

function rememberSingleTaskStart(task, taskProgress) {
    const startedAtMs = parseRegistrationTimestampMs(task?.started_at || registrationStreamState?.task?.started_at);
    if (startedAtMs !== null) {
        singleTaskStartedAtMs = startedAtMs;
        return;
    }
    const elapsedMs = Number(taskProgress?.elapsed_ms);
    if (Number.isFinite(elapsedMs) && elapsedMs >= 0) {
        singleTaskStartedAtMs = Date.now() - elapsedMs;
    }
}

function rememberBatchTaskStart(batch) {
    const startedAtMs = parseRegistrationTimestampMs(batch?.started_at);
    if (startedAtMs !== null) {
        batchTaskStartedAtMs = startedAtMs;
    }
}

function renderSingleTaskElapsedClock() {
    const isVisible = elements.singleProgressCard && elements.singleProgressCard.style.display !== 'none';
    if (!isVisible) {
        return;
    }
    if (!Number.isFinite(singleTaskStartedAtMs)) {
        setSingleTaskElapsedText('00:00:00');
        return;
    }
    setSingleTaskElapsedText(formatElapsedMsToClock(Date.now() - singleTaskStartedAtMs));
}

function renderBatchRuntimeMetrics() {
    const isVisible = elements.batchProgressSection && elements.batchProgressSection.style.display !== 'none';
    if (!isVisible) {
        return;
    }
    if (!Number.isFinite(batchTaskStartedAtMs)) {
        setBatchElapsedTexts('00:00:00', '—');
        return;
    }
    const elapsedMs = Math.max(0, Date.now() - batchTaskStartedAtMs);
    const successCount = Number(currentBatch?.success);
    const averageText = Number.isFinite(successCount) && successCount > 0
        ? formatElapsedMsToClock(elapsedMs / successCount)
        : '—';
    setBatchElapsedTexts(formatElapsedMsToClock(elapsedMs), averageText);
}

function renderRegistrationRuntimeMetrics() {
    renderSingleTaskElapsedClock();
    renderBatchRuntimeMetrics();
}

function ensureRegistrationRuntimeTicker() {
    if (registrationRuntimeTicker) {
        renderRegistrationRuntimeMetrics();
        return registrationRuntimeTicker;
    }
    registrationRuntimeTicker = setInterval(() => {
        renderRegistrationRuntimeMetrics();
    }, 1000);
    renderRegistrationRuntimeMetrics();
    return registrationRuntimeTicker;
}

function stopRegistrationRuntimeTicker() {
    if (registrationRuntimeTicker) {
        clearInterval(registrationRuntimeTicker);
        registrationRuntimeTicker = null;
    }
}

// ============== Registration shared realtime console 主链路 ==============

function hasRegistrationSharedRuntime() {
    return Boolean(
        window?.realtimeLogStore?.createState
        && window?.realtimeLogClient?.createStreamClient
        && window?.realtimeLogConsole?.mountRealtimeLogConsole
    );
}

function createRegistrationInitialStreamState() {
    const seed = {
        cursors: {},
        task: {},
        taskProgress: null,
        currentStep: null,
        steps: [],
        batch: {},
        logs: [],
        connection: { status: 'disconnected' },
    };
    if (window?.realtimeLogStore?.createState) {
        return window.realtimeLogStore.createState(seed);
    }
    return seed;
}

let registrationStreamState = createRegistrationInitialStreamState();
let registrationStreamRenderedLogCount = 0;

function getRegistrationConsoleDistanceFromBottom(root) {
    if (!root) return 0;
    const scrollHeight = Number(root.scrollHeight || 0);
    const scrollTop = Number(root.scrollTop || 0);
    const clientHeight = Number(root.clientHeight || 0);
    return Math.max(0, scrollHeight - (scrollTop + clientHeight));
}

function handleRegistrationConsoleScroll() {
    const controller = registrationSharedConsoleController;
    if (!controller || controller.root !== elements.consoleLog) {
        return;
    }

    const currentScrollTop = Number(controller.root.scrollTop || 0);
    controller.rememberManualScroll(currentScrollTop);

    if (controller.ui.autoScrollPinned === false) {
        syncRegistrationLogAutoScrollInput(controller);
        return;
    }

    const nearBottom = getRegistrationConsoleDistanceFromBottom(controller.root) <= 24;
    if (nearBottom) {
        if (controller.ui.autoScroll === false) {
            controller.toggleAutoScroll(true);
        }
        syncRegistrationLogAutoScrollInput(controller);
        return;
    }

    if (controller.ui.autoScroll !== false) {
        controller.toggleAutoScroll(false);
    }
    syncRegistrationLogAutoScrollInput(controller);
}

function syncRegistrationLogAutoScrollInput(controller = registrationSharedConsoleController) {
    if (!elements.registrationLogAutoScrollInput) {
        return;
    }
    elements.registrationLogAutoScrollInput.checked = controller
        ? controller.ui.autoScroll !== false
        : true;
}

function handleRegistrationLogAutoScrollChange() {
    const enabled = Boolean(elements.registrationLogAutoScrollInput?.checked);
    const controller = ensureRegistrationSharedConsoleMounted();
    if (!controller) {
        if (enabled && elements.consoleLog) {
            elements.consoleLog.scrollTop = elements.consoleLog.scrollHeight || 0;
        }
        syncRegistrationLogAutoScrollInput(null);
        return;
    }

    controller.ui.autoScrollPinned = enabled;
    if (enabled) {
        controller.rememberManualScroll(controller.root.scrollHeight || 0);
        controller.toggleAutoScroll(true);
        controller.root.scrollTop = controller.root.scrollHeight || 0;
    } else {
        controller.rememberManualScroll(controller.root.scrollTop || 0);
        controller.toggleAutoScroll(false);
    }
    syncRegistrationLogAutoScrollInput(controller);
}

function ensureRegistrationSharedConsoleMounted() {
    if (!hasRegistrationSharedRuntime() || !elements.consoleLog) {
        return null;
    }
    if (!registrationSharedConsoleController || registrationSharedConsoleController.root !== elements.consoleLog) {
        registrationSharedConsoleController = window.realtimeLogConsole.mountRealtimeLogConsole(elements.consoleLog, {
            state: registrationStreamState,
        });
        registrationSharedConsoleController.ui.autoScrollPinned = true;
        if (!elements.consoleLog.dataset.registrationScrollBound) {
            elements.consoleLog.addEventListener('scroll', handleRegistrationConsoleScroll);
            elements.consoleLog.dataset.registrationScrollBound = 'true';
        }
    }
    syncRegistrationLogAutoScrollInput(registrationSharedConsoleController);
    return registrationSharedConsoleController;
}

function applyRegistrationStreamState(nextState, event) {
    const previous = registrationStreamState;
    if (window?.realtimeLogStore?.createState) {
        registrationStreamState = window.realtimeLogStore.createState(nextState || {});
    } else {
        registrationStreamState = nextState || createRegistrationInitialStreamState();
    }
    registrationStreamRenderedLogCount = Array.isArray(registrationStreamState?.logs)
        ? registrationStreamState.logs.length
        : 0;

    const controller = ensureRegistrationSharedConsoleMounted();
    if (controller) {
        controller.setState(registrationStreamState);
        syncRegistrationLogAutoScrollInput(controller);
    }

    syncRegistrationStreamPanels(previous, registrationStreamState, event);
    return registrationStreamState;
}

function ensureRegistrationStreamClient() {
    if (!hasRegistrationSharedRuntime()) {
        return null;
    }
    if (registrationSharedStreamClient) {
        return registrationSharedStreamClient;
    }
    ensureRegistrationSharedConsoleMounted();
    registrationSharedStreamClient = window.realtimeLogClient.createStreamClient({
        initialState: registrationStreamState,
        onStateChange(nextState) {
            applyRegistrationStreamState(nextState, registrationSharedPendingEvent);
        },
    });
    applyRegistrationStreamState(registrationSharedStreamClient.getState(), null);
    return registrationSharedStreamClient;
}

function dispatchRegistrationStreamEvent(event) {
    const client = ensureRegistrationStreamClient();
    if (client) {
        registrationSharedPendingEvent = event;
        try {
            return client.dispatchEvent(event);
        } finally {
            registrationSharedPendingEvent = null;
        }
    }

    const reducer = window?.registrationStream?.reduce;
    if (typeof reducer !== 'function') {
        return registrationStreamState;
    }
    const nextState = reducer(registrationStreamState, event);
    if (nextState !== registrationStreamState) {
        applyRegistrationStreamState(nextState, event);
    }
    return nextState;
}

function applyRegistrationStreamSnapshot(snapshot) {
    const client = ensureRegistrationStreamClient();
    if (client) {
        registrationSharedPendingEvent = snapshot;
        try {
            return client.applySnapshot(snapshot);
        } finally {
            registrationSharedPendingEvent = null;
        }
    }
    return dispatchRegistrationStreamEvent(snapshot);
}

function reduceRegistrationStream(event) {
    if (!event || typeof event.kind !== 'string') {
        return registrationStreamState;
    }
    if (event.kind === 'snapshot') {
        return applyRegistrationStreamSnapshot(event);
    }
    return dispatchRegistrationStreamEvent(event);
}

function emitConnectionStateChanged(status) {
    reduceRegistrationStream({
        kind: 'connection_state_changed',
        payload: { status },
        meta: { local: true },
    });
}

function renderRegistrationStreamStatus() {
    const panel = document.getElementById('registration-stream-status');
    if (!panel) return;
    const rawStatus = registrationStreamState?.connection?.status || '';
    const statusText = {
        connected: '已连接',
        reconnecting: '重连中',
        polling: '轮询中',
        disconnected: '已断开',
    }[rawStatus] || rawStatus;
    panel.textContent = statusText;
}

function syncRegistrationStreamPanels(previous, next, event) {
    renderRegistrationStreamStatus();

    // 单任务进度摘要：仅在相关事件时刷新
    if (event?.kind === 'snapshot' || event?.kind === 'task_step_updated') {
        rememberSingleTaskStart(next?.task, next?.taskProgress);
        renderSingleTaskProgressSummary(next?.taskProgress, next?.currentStep);
    }

    // 任务状态：仅在相关事件时刷新（保持最小侵入，避免影响旧逻辑）
    if (event?.kind === 'snapshot' || event?.kind === 'task_status_changed') {
        const status = next?.task?.status;
        rememberSingleTaskStart(next?.task, next?.taskProgress);
        if (status) {
            updateTaskStatus(status);
        }
        if (next?.task?.email && elements.taskEmail) {
            elements.taskEmail.textContent = next.task.email;
        }
        if (next?.task?.email_service && elements.taskService) {
            elements.taskService.textContent = getServiceTypeText(next.task.email_service);
        }
    }

    // 批量进度：仅在相关事件时刷新
    if (event?.kind === 'snapshot' || event?.kind === 'batch_progress_updated' || event?.kind === 'stream_closed') {
        const batch = next?.batch;
        rememberBatchTaskStart(batch);
        const hasUnlimited = !!(batch && batch.is_unlimited);
        const hasFiniteTotal = Number.isFinite(batch?.total) && batch.total > 0;
        const hasCompleted = Number.isFinite(batch?.completed);
        if (hasUnlimited || (hasFiniteTotal && hasCompleted)) {
            updateBatchProgress(batch);
        }
    }

    renderRegistrationRuntimeMetrics();
}

function resetConsoleLogDom() {
    const controller = ensureRegistrationSharedConsoleMounted();
    if (controller) {
        controller.setState(createRegistrationInitialStreamState());
    } else if (elements.consoleLog) {
        elements.consoleLog.innerHTML = '';
    }
    displayedLogs.clear();
}

function resetRegistrationStreamViewState() {
    registrationSharedStreamClient = null;
    registrationSharedPendingEvent = null;
    registrationStreamState = createRegistrationInitialStreamState();
    registrationStreamRenderedLogCount = 0;
    singleTaskStartedAtMs = null;
    batchTaskStartedAtMs = null;
    const controller = ensureRegistrationSharedConsoleMounted();
    if (controller) {
        controller.ui.viewCleared = false;
        controller.ui.clearedAfterSeq = 0;
        controller.ui.autoScrollPinned = true;
        controller.ui.autoScroll = true;
        controller.ui.manualScrollTop = 0;
        controller.setState(registrationStreamState);
        syncRegistrationLogAutoScrollInput(controller);
    } else if (elements.consoleLog) {
        elements.consoleLog.innerHTML = '';
    }
    renderRegistrationStreamStatus();
    syncRegistrationLogAutoScrollInput(null);
    setSingleTaskElapsedText('00:00:00');
    setBatchElapsedTexts('00:00:00', '—');
    stopRegistrationRuntimeTicker();
}

// DOM 元素
const elements = {
    workbenchShell: document.getElementById('registration-workbench-shell'),
    workbenchTabs: document.getElementById('registration-workbench-tabs'),
    workbenchTabConfig: document.getElementById('registration-workbench-tab-config'),
    workbenchTabRunning: document.getElementById('registration-workbench-tab-running'),
    workbenchTabRecent: document.getElementById('registration-workbench-tab-recent'),
    workbenchViewConfig: document.getElementById('registration-workbench-view-config'),
    workbenchViewRunning: document.getElementById('registration-workbench-view-running'),
    workbenchViewRecent: document.getElementById('registration-workbench-view-recent'),

    // 新版工作台布局挂点（用于保持 DOM 结构可读、便于后续扩展；不改变现有渲染逻辑）
    registrationConfigPanel: document.getElementById('registration-config-panel'),
    registrationSingleProgress: document.getElementById('registration-single-progress'),
    registrationBatchSummary: document.getElementById('registration-batch-summary'),
    registrationFailureSummary: document.getElementById('registration-failure-summary'),
    registrationLogConsole: document.getElementById('registration-log-console'),

    form: document.getElementById('registration-form'),
    emailService: document.getElementById('email-service'),
    pipelineKey: document.getElementById('pipeline-key'),
    useProxy: document.getElementById('use-proxy'),
    proxy: document.getElementById('proxy'),
    regMode: document.getElementById('reg-mode'),
    regModeGroup: document.getElementById('reg-mode-group'),
    batchCountGroup: document.getElementById('batch-count-group'),
    batchCount: document.getElementById('batch-count'),
    batchOptions: document.getElementById('batch-options'),
    intervalMin: document.getElementById('interval-min'),
    intervalMax: document.getElementById('interval-max'),
    startBtn: document.getElementById('start-btn'),
    cancelBtn: document.getElementById('cancel-btn'),
    taskStatusRow: document.getElementById('task-status-row'),
    singleProgressCard: document.getElementById('single-progress-card'),
    singleProgressCurrentStep: document.getElementById('single-progress-current-step'),
    singleProgressStepText: document.getElementById('single-progress-step-text'),
    singleProgressElapsed: document.getElementById('single-progress-elapsed'),
    singleProgressBar: document.getElementById('single-progress-bar'),
    batchProgressSection: document.getElementById('batch-progress-section'),
    batchProgressElapsed: document.getElementById('batch-progress-elapsed'),
    batchProgressAvgElapsed: document.getElementById('batch-progress-avg-elapsed'),
    consoleLog: document.getElementById('console-log'),
    registrationLogAutoScrollInput: document.getElementById('registration-log-auto-scroll'),
    clearLogBtn: document.getElementById('clear-log-btn'),
    // 任务状态
    taskId: document.getElementById('task-id'),
    taskEmail: document.getElementById('task-email'),
    taskStatus: document.getElementById('task-status'),
    taskService: document.getElementById('task-service'),
    taskProxyIp: document.getElementById('task-proxy-ip'),
    taskStatusBadge: document.getElementById('task-status-badge'),
    // 批量状态
    batchProgressText: document.getElementById('batch-progress-text'),
    batchProgressPercent: document.getElementById('batch-progress-percent'),
    progressBar: document.getElementById('progress-bar'),
    batchSuccess: document.getElementById('batch-success'),
    batchFailed: document.getElementById('batch-failed'),
    batchRemaining: document.getElementById('batch-remaining'),
    batchConsecutiveFailures: document.getElementById('batch-consecutive-failures'),
    batchDomainStats: document.getElementById('batch-domain-stats'),
    // 失败分析
    refreshFailureAnalysisBtn: document.getElementById('refresh-failure-analysis-btn'),
    registrationFailureFilterForm: document.getElementById('registration-failure-filter-form'),
    failureFilterPipelineKey: document.getElementById('failure-filter-pipeline-key'),
    failureFilterRegistrationMode: document.getElementById('failure-filter-registration-mode'),
    failureFilterEmailSuffix: document.getElementById('failure-filter-email-suffix'),
    failureFilterEmailServiceId: document.getElementById('failure-filter-email-service-id'),
    failureFilterProxyIp: document.getElementById('failure-filter-proxy-ip'),
    failureFilterFailureStage: document.getElementById('failure-filter-failure-stage'),
    failureFilterStepKey: document.getElementById('failure-filter-step-key'),
    failureFilterRetryable: document.getElementById('failure-filter-retryable'),
    failureFilterErrorKeyword: document.getElementById('failure-filter-error-keyword'),
    failureFilterFailedFrom: document.getElementById('failure-filter-failed-from'),
    failureFilterFailedTo: document.getElementById('failure-filter-failed-to'),
    failureTotalAttempts: document.getElementById('failure-total-attempts'),
    failureTodayAttempts: document.getElementById('failure-today-attempts'),
    failureTopEmailSuffixes: document.getElementById('failure-top-email-suffixes'),
    failureTopErrorCodes: document.getElementById('failure-top-error-codes'),
    failureTopProxyIps: document.getElementById('failure-top-proxy-ips'),
    failureTopFailureStages: document.getElementById('failure-top-failure-stages'),
    failureTopStepKeys: document.getElementById('failure-top-step-keys'),
    failureRetryableBreakdown: document.getElementById('failure-retryable-breakdown'),
    registrationFailureTableBody: document.getElementById('registration-failure-table-body'),
    failurePrevPageBtn: document.getElementById('failure-prev-page-btn'),
    failureNextPageBtn: document.getElementById('failure-next-page-btn'),
    failurePageIndicator: document.getElementById('failure-page-indicator'),
    registrationFailureDetailDialog: document.getElementById('registration-failure-detail-dialog'),
    registrationFailureDetailTitle: document.getElementById('registration-failure-detail-title'),
    registrationFailureDetailMeta: document.getElementById('registration-failure-detail-meta'),
    registrationFailureDetailText: document.getElementById('registration-failure-detail-text'),
    registrationFailureDetailCloseBtn: document.getElementById('registration-failure-detail-close-btn'),
    recentRegistrationTasksTable: document.getElementById('recent-registration-tasks-table'),
    refreshTasksBtn: document.getElementById('refresh-tasks-btn'),
    // 已注册账号
    recentAccountsTable: document.getElementById('recent-accounts-table'),
    refreshAccountsBtn: document.getElementById('refresh-accounts-btn'),
    // Outlook 批量注册
    outlookBatchSection: document.getElementById('outlook-batch-section'),
    outlookAccountsContainer: document.getElementById('outlook-accounts-container'),
    outlookIntervalMin: document.getElementById('outlook-interval-min'),
    outlookIntervalMax: document.getElementById('outlook-interval-max'),
    outlookSkipRegistered: document.getElementById('outlook-skip-registered'),
    outlookConcurrencyMode: document.getElementById('outlook-concurrency-mode'),
    outlookConcurrencyCount: document.getElementById('outlook-concurrency-count'),
    outlookConcurrencyHint: document.getElementById('outlook-concurrency-hint'),
    outlookIntervalGroup: document.getElementById('outlook-interval-group'),
    // 批量并发控件
    concurrencyMode: document.getElementById('concurrency-mode'),
    concurrencyCount: document.getElementById('concurrency-count'),
    concurrencyHint: document.getElementById('concurrency-hint'),
    intervalGroup: document.getElementById('interval-group'),
    // 注册后自动操作
    autoUploadCpa: document.getElementById('auto-upload-cpa'),
    cpaServiceSelectGroup: document.getElementById('cpa-service-select-group'),
    cpaServiceSelect: document.getElementById('cpa-service-select'),
    autoUploadSub2api: document.getElementById('auto-upload-sub2api'),
    sub2apiServiceSelectGroup: document.getElementById('sub2api-service-select-group'),
    sub2apiServiceSelect: document.getElementById('sub2api-service-select'),
    autoUploadTm: document.getElementById('auto-upload-tm'),
    tmServiceSelectGroup: document.getElementById('tm-service-select-group'),
    tmServiceSelect: document.getElementById('tm-service-select'),
};

function switchWorkbenchView(nextView = 'config') {
    const allowedViews = ['config', 'running', 'recent'];
    const normalizedView = allowedViews.includes(nextView) ? nextView : 'config';
    activeWorkbenchView = normalizedView;

    if (elements.workbenchShell) {
        elements.workbenchShell.dataset.activeView = normalizedView;
    }

    const panels = {
        config: elements.workbenchViewConfig,
        running: elements.workbenchViewRunning,
        recent: elements.workbenchViewRecent,
    };

    Object.entries(panels).forEach(([viewKey, panel]) => {
        if (!panel) return;
        panel.hidden = viewKey !== normalizedView;
    });

    const tabs = {
        config: elements.workbenchTabConfig,
        running: elements.workbenchTabRunning,
        recent: elements.workbenchTabRecent,
    };

    Object.entries(tabs).forEach(([viewKey, button]) => {
        if (!button) return;
        const isActive = viewKey === normalizedView;
        button.classList.toggle('is-active', isActive);
        if (typeof button.setAttribute === 'function') {
            button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        } else {
            button.ariaSelected = isActive ? 'true' : 'false';
        }
    });

    return normalizedView;
}

function setRunningWorkbenchMode(nextMode = 'idle') {
    const allowedModes = ['idle', 'single', 'batch'];
    const normalizedMode = allowedModes.includes(nextMode) ? nextMode : 'idle';

    if (elements.workbenchShell) {
        elements.workbenchShell.dataset.runningMode = normalizedMode;
    }
    if (elements.registrationSingleProgress) {
        elements.registrationSingleProgress.hidden = normalizedMode === 'batch';
    }
    if (elements.registrationBatchSummary) {
        elements.registrationBatchSummary.hidden = normalizedMode === 'single';
    }
    if (elements.registrationLogConsole) {
        elements.registrationLogConsole.classList.toggle(
            'registration-log-console--immersive',
            normalizedMode !== 'idle',
        );
    }

    return normalizedMode;
}

function initWorkbenchTabs() {
    [
        ['config', elements.workbenchTabConfig],
        ['running', elements.workbenchTabRunning],
        ['recent', elements.workbenchTabRecent],
    ].forEach(([viewKey, button]) => {
        if (!button) return;
        button.addEventListener('click', () => {
            switchWorkbenchView(viewKey);
        });
    });

    setRunningWorkbenchMode('idle');
    switchWorkbenchView(activeWorkbenchView);
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    const root = document.body?.dataset?.pageKey;
    if (root !== 'registration_workbench') {
        return;
    }

    initWorkbenchTabs();
    initEventListeners();
    ensureRegistrationSharedConsoleMounted();
    renderRegistrationStreamStatus();
    loadAvailableServices();
    loadRecentAccounts();
    loadRecentRegistrationTasks();
    initRegistrationFailureAnalysis();
    startAccountsPolling();
    initVisibilityReconnect();
    restoreActiveTask();
    initAutoUploadOptions();
});

// 初始化注册后自动操作选项（CPA / Sub2API / TM）
async function initAutoUploadOptions() {
    await Promise.all([
        loadServiceSelect('/cpa-services?enabled=true', elements.cpaServiceSelect, elements.autoUploadCpa, elements.cpaServiceSelectGroup),
        loadServiceSelect('/sub2api-services?enabled=true', elements.sub2apiServiceSelect, elements.autoUploadSub2api, elements.sub2apiServiceSelectGroup),
        loadServiceSelect('/tm-services?enabled=true', elements.tmServiceSelect, elements.autoUploadTm, elements.tmServiceSelectGroup),
    ]);
}

// 通用：构建自定义多选下拉组件并处理联动
async function loadServiceSelect(apiPath, container, checkbox, selectGroup) {
    if (!checkbox || !container) return;
    let services = [];
    try {
        services = await api.get(apiPath);
    } catch (e) {}

    if (!services || services.length === 0) {
        checkbox.disabled = true;
        checkbox.title = '请先在设置中添加对应服务';
        const label = checkbox.closest('label');
        if (label) label.style.opacity = '0.5';
        container.innerHTML = '<div class="msd-empty">暂无可用服务</div>';
    } else {
        const items = services.map(s =>
            `<label class="msd-item">
                <input type="checkbox" value="${s.id}" checked>
                <span>${escapeHtml(s.name)}</span>
            </label>`
        ).join('');
        container.innerHTML = `
            <div class="msd-dropdown" id="${container.id}-dd">
                <div class="msd-trigger" onclick="toggleMsd('${container.id}-dd')">
                    <span class="msd-label">全部 (${services.length})</span>
                    <span class="msd-arrow">▼</span>
                </div>
                <div class="msd-list">${items}</div>
            </div>`;
        // 监听 checkbox 变化，更新触发器文字
        container.querySelectorAll('.msd-item input').forEach(cb => {
            cb.addEventListener('change', () => updateMsdLabel(container.id + '-dd'));
        });
        // 点击外部关闭
        document.addEventListener('click', (e) => {
            const dd = document.getElementById(container.id + '-dd');
            if (dd && !dd.contains(e.target)) dd.classList.remove('open');
        }, true);
    }

    // 联动显示/隐藏服务选择区
    checkbox.addEventListener('change', () => {
        if (selectGroup) selectGroup.style.display = checkbox.checked ? 'block' : 'none';
    });
}

function toggleMsd(ddId) {
    const dd = document.getElementById(ddId);
    if (dd) dd.classList.toggle('open');
}

function updateMsdLabel(ddId) {
    const dd = document.getElementById(ddId);
    if (!dd) return;
    const all = dd.querySelectorAll('.msd-item input');
    const checked = dd.querySelectorAll('.msd-item input:checked');
    const label = dd.querySelector('.msd-label');
    if (!label) return;
    if (checked.length === 0) label.textContent = '未选择';
    else if (checked.length === all.length) label.textContent = `全部 (${all.length})`;
    else label.textContent = Array.from(checked).map(c => c.nextElementSibling.textContent).join(', ');
}

// 获取自定义多选下拉中选中的服务 ID 列表
function getSelectedServiceIds(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('.msd-item input:checked')).map(cb => parseInt(cb.value));
}

// 事件监听
function initEventListeners() {
    // 注册表单提交
    elements.form.addEventListener('submit', handleStartRegistration);

    // 注册模式切换
    elements.regMode.addEventListener('change', handleModeChange);

    // 邮箱服务切换
    elements.emailService.addEventListener('change', handleServiceChange);

    // 取消按钮
    elements.cancelBtn.addEventListener('click', handleCancelTask);

    // 清空日志
    elements.clearLogBtn.addEventListener('click', () => {
        displayedLogs.clear();
        const controller = ensureRegistrationSharedConsoleMounted();
        if (controller) {
            controller.clearView();
            return;
        }
        elements.consoleLog.innerHTML = '<div class="log-line info">[系统] 日志已清空</div>';
        resetRegistrationStreamViewState();
    });

    if (elements.registrationLogAutoScrollInput) {
        elements.registrationLogAutoScrollInput.addEventListener('change', handleRegistrationLogAutoScrollChange);
    }

    // 刷新账号列表
    elements.refreshAccountsBtn.addEventListener('click', () => {
        loadRecentAccounts();
        toast.info('已刷新');
    });

    if (elements.refreshTasksBtn) {
        elements.refreshTasksBtn.addEventListener('click', () => {
            loadRecentRegistrationTasks();
            toast.info('已刷新');
        });
    }

    if (elements.refreshFailureAnalysisBtn) {
        elements.refreshFailureAnalysisBtn.addEventListener('click', () => {
            loadRegistrationFailureAnalysis();
        });
    }

    if (elements.registrationFailureFilterForm) {
        elements.registrationFailureFilterForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            registrationFailureState.page = 1;
            await loadRegistrationFailureAnalysis();
        });
    }

    if (elements.failurePrevPageBtn) {
        elements.failurePrevPageBtn.addEventListener('click', async () => {
            if (registrationFailureState.page <= 1) return;
            registrationFailureState.page -= 1;
            await loadRegistrationFailureList();
        });
    }

    if (elements.failureNextPageBtn) {
        elements.failureNextPageBtn.addEventListener('click', async () => {
            const totalPages = getRegistrationFailureTotalPages();
            if (registrationFailureState.page >= totalPages) return;
            registrationFailureState.page += 1;
            await loadRegistrationFailureList();
        });
    }

    if (elements.registrationFailureDetailCloseBtn) {
        elements.registrationFailureDetailCloseBtn.addEventListener('click', closeRegistrationFailureDetail);
    }

    // 并发模式切换
    elements.concurrencyMode.addEventListener('change', () => {
        handleConcurrencyModeChange(elements.concurrencyMode, elements.concurrencyHint, elements.intervalGroup);
    });
    elements.outlookConcurrencyMode.addEventListener('change', () => {
        handleConcurrencyModeChange(elements.outlookConcurrencyMode, elements.outlookConcurrencyHint, elements.outlookIntervalGroup);
    });
}

function initRegistrationFailureAnalysis() {
    if (!elements.registrationFailureSummary) {
        return;
    }
    updateRegistrationFailurePagination();
    loadRegistrationFailureAnalysis();
}

function normalizeRegistrationFailureFilterValue(value) {
    const text = String(value ?? '').trim();
    return text || '';
}

function collectRegistrationFailureFilters() {
    return {
        pipeline_key: normalizeRegistrationFailureFilterValue(elements.failureFilterPipelineKey?.value),
        registration_mode: normalizeRegistrationFailureFilterValue(elements.failureFilterRegistrationMode?.value),
        email_suffix: normalizeRegistrationFailureFilterValue(elements.failureFilterEmailSuffix?.value),
        email_service_id: normalizeRegistrationFailureFilterValue(elements.failureFilterEmailServiceId?.value),
        proxy_ip: normalizeRegistrationFailureFilterValue(elements.failureFilterProxyIp?.value),
        failure_stage: normalizeRegistrationFailureFilterValue(elements.failureFilterFailureStage?.value),
        step_key: normalizeRegistrationFailureFilterValue(elements.failureFilterStepKey?.value),
        retryable: normalizeRegistrationFailureFilterValue(elements.failureFilterRetryable?.value),
        error_keyword: normalizeRegistrationFailureFilterValue(elements.failureFilterErrorKeyword?.value),
        failed_from: normalizeRegistrationFailureFilterValue(elements.failureFilterFailedFrom?.value),
        failed_to: normalizeRegistrationFailureFilterValue(elements.failureFilterFailedTo?.value),
    };
}

function appendRegistrationFailureQueryParam(params, key, value) {
    const normalized = normalizeRegistrationFailureFilterValue(value);
    if (!normalized) {
        return;
    }
    params.set(key, normalized);
}

function buildRegistrationFailureQueryParams(options = {}) {
    const includePage = options.includePage !== false;
    const params = new URLSearchParams();
    const filters = collectRegistrationFailureFilters();
    registrationFailureState.filters = { ...filters };

    appendRegistrationFailureQueryParam(params, 'pipeline_key', filters.pipeline_key);
    appendRegistrationFailureQueryParam(params, 'registration_mode', filters.registration_mode);
    appendRegistrationFailureQueryParam(params, 'email_suffix', filters.email_suffix);
    appendRegistrationFailureQueryParam(params, 'email_service_id', filters.email_service_id);
    appendRegistrationFailureQueryParam(params, 'proxy_ip', filters.proxy_ip);
    appendRegistrationFailureQueryParam(params, 'failure_stage', filters.failure_stage);
    appendRegistrationFailureQueryParam(params, 'step_key', filters.step_key);
    appendRegistrationFailureQueryParam(params, 'retryable', filters.retryable);
    appendRegistrationFailureQueryParam(params, 'error_keyword', filters.error_keyword);
    appendRegistrationFailureQueryParam(params, 'failed_from', filters.failed_from);
    appendRegistrationFailureQueryParam(params, 'failed_to', filters.failed_to);

    if (includePage) {
        params.set('page', String(registrationFailureState.page || 1));
        params.set('page_size', String(registrationFailureState.pageSize || 20));
    }
    return params.toString();
}

function getRegistrationFailureTotalPages() {
    const total = Number(registrationFailureState.total || 0);
    const pageSize = Number(registrationFailureState.pageSize || 20);
    if (!Number.isFinite(total) || total <= 0) {
        return 1;
    }
    return Math.max(1, Math.ceil(total / pageSize));
}

function renderRegistrationFailureTopList(element, rows) {
    if (!element) {
        return;
    }
    const items = Array.isArray(rows) ? rows : [];
    if (items.length === 0) {
        element.innerHTML = '<li>—</li>';
        return;
    }
    element.innerHTML = items.map((row) => `
        <li>${escapeHtml(row?.value || 'unknown')} · ${Number.isFinite(Number(row?.count)) ? Number(row.count) : 0}</li>
    `).join('');
}

function renderRegistrationFailureSummary(summary) {
    const payload = summary || {};
    if (elements.failureTotalAttempts) {
        elements.failureTotalAttempts.textContent = String(payload.total_failed_attempts ?? 0);
    }
    if (elements.failureTodayAttempts) {
        elements.failureTodayAttempts.textContent = String(payload.today_failed_attempts ?? 0);
    }
    renderRegistrationFailureTopList(elements.failureTopEmailSuffixes, payload.top_email_suffixes);
    renderRegistrationFailureTopList(elements.failureTopErrorCodes, payload.top_error_codes);
    renderRegistrationFailureTopList(elements.failureTopProxyIps, payload.top_proxy_ips);
    renderRegistrationFailureTopList(elements.failureTopFailureStages, payload.top_failure_stages);
    renderRegistrationFailureTopList(elements.failureTopStepKeys, payload.top_step_keys);
    renderRegistrationFailureTopList(elements.failureRetryableBreakdown, payload.retryable_breakdown);
}

function updateRegistrationFailurePagination() {
    const totalPages = getRegistrationFailureTotalPages();
    const currentPage = Math.min(Math.max(1, Number(registrationFailureState.page || 1)), totalPages);
    registrationFailureState.page = currentPage;
    if (elements.failurePageIndicator) {
        elements.failurePageIndicator.textContent = `${currentPage} / ${totalPages}`;
    }
    if (elements.failurePrevPageBtn) {
        elements.failurePrevPageBtn.disabled = currentPage <= 1;
    }
    if (elements.failureNextPageBtn) {
        elements.failureNextPageBtn.disabled = currentPage >= totalPages;
    }
}

function formatRegistrationFailureTimestamp(value) {
    if (!value) {
        return '—';
    }
    const formatted = typeof format?.date === 'function' ? format.date(value) : String(value);
    return escapeHtml(formatted || '—');
}

function buildRegistrationFailureDetailMeta(item) {
    const parts = [
        item?.email || '—',
        item?.email_service_id != null ? `service:${item.email_service_id}` : 'service:—',
        item?.proxy_ip || item?.proxy || '—',
        item?.failure_stage ? `stage:${item.failure_stage}` : 'stage:—',
        item?.failed_at || item?.created_at || '—',
    ];
    return parts.join(' · ');
}

function buildRegistrationFailureDetailText(item) {
    const detail = String(item?.error_detail || '—');
    const sections = [
        `结构化上下文\nstage=${item?.failure_stage || '—'}\nstep_key=${item?.step_key || '—'}\nretryable=${item?.retryable === true ? 'true' : 'false'}`,
        `错误详情\n${detail}`,
    ];
    if (item?.extra_json && Object.keys(item.extra_json).length > 0) {
        sections.push(`扩展上下文\n${JSON.stringify(item.extra_json, null, 2)}`);
    }
    return sections.join('\n\n');
}

function formatRegistrationFailureStructuredCell(item) {
    const stage = escapeHtml(item?.failure_stage || '—');
    const stepKey = escapeHtml(item?.step_key || '—');
    return `
        <div class="failure-structured-cell">
            <strong>${stage}</strong>
            <span>${stepKey}</span>
        </div>
    `;
}

function formatRegistrationFailureRetryable(item) {
    if (item?.retryable === true) {
        return '<span class="failure-retryable-badge failure-retryable-badge--true">可重试</span>';
    }
    return '<span class="failure-retryable-badge failure-retryable-badge--false">不可重试</span>';
}

function openRegistrationFailureDetail(detail) {
    if (!elements.registrationFailureDetailDialog || !elements.registrationFailureDetailText) {
        return;
    }
    const item = typeof detail === 'string' ? { error_detail: detail } : (detail || {});
    if (elements.registrationFailureDetailTitle) {
        elements.registrationFailureDetailTitle.textContent = `失败详情 · ${item.error_code || 'unknown'}${isRateLimitFailureItem(item) ? ' · 限流' : ''}`;
    }
    if (elements.registrationFailureDetailMeta) {
        elements.registrationFailureDetailMeta.textContent = buildRegistrationFailureDetailMeta(item);
    }
    elements.registrationFailureDetailText.dataset.renderMode = 'textContent';
    elements.registrationFailureDetailText.textContent = buildRegistrationFailureDetailText(item);
    if (elements.registrationFailureDetailDialog.open === true) {
        return;
    }
    if (typeof elements.registrationFailureDetailDialog.showModal === 'function') {
        elements.registrationFailureDetailDialog.showModal();
    } else {
        elements.registrationFailureDetailDialog.open = true;
    }
}

function closeRegistrationFailureDetail() {
    if (!elements.registrationFailureDetailDialog) {
        return;
    }
    if (typeof elements.registrationFailureDetailDialog.close === 'function') {
        elements.registrationFailureDetailDialog.close();
    } else {
        elements.registrationFailureDetailDialog.open = false;
    }
}

function openRegistrationFailureDetailByIndex(index) {
    const numericIndex = Number(index);
    if (!Number.isInteger(numericIndex) || numericIndex < 0) {
        return;
    }
    const item = Array.isArray(registrationFailureState.items) ? registrationFailureState.items[numericIndex] : null;
    if (!item) {
        return;
    }
    openRegistrationFailureDetail(item);
}

function renderRegistrationFailureRows(items) {
    if (!elements.registrationFailureTableBody) {
        return;
    }
    const rows = Array.isArray(items) ? items : [];
    registrationFailureState.items = rows;
    if (rows.length === 0) {
        elements.registrationFailureTableBody.innerHTML = `
            <tr>
                <td colspan="10">暂无失败记录</td>
            </tr>
        `;
        return;
    }
    elements.registrationFailureTableBody.innerHTML = rows.map((item, index) => `
        <tr class="${isRateLimitFailureItem(item) ? 'failure-row-rate-limit' : ''}">
            <td>${formatRegistrationFailureTimestamp(item.failed_at || item.created_at)}</td>
            <td>${escapeHtml(item.email || '—')}</td>
            <td>${escapeHtml(item.email_suffix || '—')}</td>
            <td>${escapeHtml(item.registration_mode || '—')}</td>
            <td>${escapeHtml(item.email_service_id != null ? String(item.email_service_id) : '—')}</td>
            <td>${escapeHtml(item.proxy_ip || '—')}</td>
            <td>${formatRegistrationFailureStructuredCell(item)}</td>
            <td>${formatRegistrationFailureRetryable(item)}</td>
            <td>
                <span>${escapeHtml(item.error_code || 'unknown')}</span>
                ${isRateLimitFailureItem(item) ? '<span class="failure-badge failure-badge-rate-limit">限流</span>' : ''}
            </td>
            <td class="failure-detail-cell">
                <button type="button" class="btn btn-ghost btn-sm" onclick="openRegistrationFailureDetailByIndex(${index})">查看详情</button>
            </td>
        </tr>
    `).join('');
}

async function loadRegistrationFailureSummary() {
    if (!elements.registrationFailureSummary) {
        return null;
    }
    const query = buildRegistrationFailureQueryParams({ includePage: false });
    const path = query ? `/registration/failures/summary?${query}` : '/registration/failures/summary';
    const summary = await api.get(path);
    renderRegistrationFailureSummary(summary);
    return summary;
}

async function loadRegistrationFailureList() {
    if (!elements.registrationFailureSummary) {
        return null;
    }
    const query = buildRegistrationFailureQueryParams();
    const path = query ? `/registration/failures?${query}` : '/registration/failures';
    const payload = await api.get(path);
    registrationFailureState.total = Number(payload?.total || 0);
    renderRegistrationFailureRows(payload?.items || []);
    updateRegistrationFailurePagination();
    return payload;
}

async function loadRegistrationFailureAnalysis() {
    if (!elements.registrationFailureSummary) {
        return;
    }
    try {
        await Promise.all([
            loadRegistrationFailureSummary(),
            loadRegistrationFailureList(),
        ]);
    } catch (error) {
        console.error('加载失败分析面板失败:', error);
        if (elements.registrationFailureTableBody) {
            elements.registrationFailureTableBody.innerHTML = `
                <tr>
                    <td colspan="10">加载失败：${escapeHtml(error?.message || 'unknown error')}</td>
                </tr>
            `;
        }
    }
}

// 加载可用的邮箱服务
async function loadAvailableServices() {
    try {
        const data = await api.get('/registration/available-services');
        availableServices = data;

        // 更新邮箱服务选择框
        updateEmailServiceOptions();

        addLog('info', '[系统] 邮箱服务列表已加载');
    } catch (error) {
        console.error('加载邮箱服务列表失败:', error);
        addLog('warning', '[警告] 加载邮箱服务列表失败');
    }
}

// 更新邮箱服务选择框
function updateEmailServiceOptions() {
    const select = elements.emailService;
    select.innerHTML = '';

    // Tempmail
    if (availableServices.tempmail.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '🌐 临时邮箱';

        availableServices.tempmail.services.forEach(service => {
            const option = document.createElement('option');
            option.value = `tempmail:${service.id || 'default'}`;
            option.textContent = service.name;
            option.dataset.type = 'tempmail';
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    }

    // Outlook
    if (availableServices.outlook.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `📧 Outlook (${availableServices.outlook.count} 个账户)`;

        // Outlook 批量注册选项
        const batchOption = document.createElement('option');
        batchOption.value = 'outlook_batch:all';
        batchOption.textContent = `📋 Outlook 批量注册 (${availableServices.outlook.count} 个账户)`;
        batchOption.dataset.type = 'outlook_batch';
        optgroup.appendChild(batchOption);

        select.appendChild(optgroup);
    } else {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '📧 Outlook (未配置)';

        const option = document.createElement('option');
        option.value = '';
        option.textContent = '请先在邮箱服务页面导入账户';
        option.disabled = true;
        optgroup.appendChild(option);

        select.appendChild(optgroup);
    }

    // 自定义域名
    if (availableServices.moe_mail.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `🔗 自定义域名 (${availableServices.moe_mail.count} 个服务)`;

        availableServices.moe_mail.services.forEach(service => {
            const option = document.createElement('option');
            option.value = `moe_mail:${service.id || 'default'}`;
            option.textContent = service.name + (service.default_domain ? ` (@${service.default_domain})` : '');
            option.dataset.type = 'moe_mail';
            if (service.id) {
                option.dataset.serviceId = service.id;
            }
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    } else {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '🔗 自定义域名 (未配置)';

        const option = document.createElement('option');
        option.value = '';
        option.textContent = '请先在邮箱服务页面添加服务';
        option.disabled = true;
        optgroup.appendChild(option);

        select.appendChild(optgroup);
    }

    // Temp-Mail（自部署）
    if (availableServices.temp_mail && availableServices.temp_mail.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `📮 Temp-Mail 自部署 (${availableServices.temp_mail.count} 个服务)`;

        availableServices.temp_mail.services.forEach(service => {
            const option = document.createElement('option');
            option.value = `temp_mail:${service.id}`;
            option.textContent = service.name + (service.domain ? ` (@${service.domain})` : '');
            option.dataset.type = 'temp_mail';
            option.dataset.serviceId = service.id;
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    }

    // DuckMail
    if (availableServices.duck_mail && availableServices.duck_mail.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `🦆 DuckMail (${availableServices.duck_mail.count} 个服务)`;

        availableServices.duck_mail.services.forEach(service => {
            const option = document.createElement('option');
            option.value = `duck_mail:${service.id}`;
            option.textContent = service.name + (service.default_domain ? ` (@${service.default_domain})` : '');
            option.dataset.type = 'duck_mail';
            option.dataset.serviceId = service.id;
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    }

    // Freemail
    if (availableServices.freemail && availableServices.freemail.available) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = `📧 Freemail (${availableServices.freemail.count} 个服务)`;

        availableServices.freemail.services.forEach(service => {
            const option = document.createElement('option');
            option.value = `freemail:${service.id}`;
            option.textContent = service.name + (service.domain ? ` (@${service.domain})` : '');
            option.dataset.type = 'freemail';
            option.dataset.serviceId = service.id;
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    }
}

// 处理邮箱服务切换
function handleServiceChange(e) {
    const value = e.target.value;
    if (!value) return;

    const [type, id] = value.split(':');
    // 处理 Outlook 批量注册模式
    if (type === 'outlook_batch') {
        isOutlookBatchMode = true;
        elements.outlookBatchSection.style.display = 'block';
        elements.regModeGroup.style.display = 'none';
        elements.batchCountGroup.style.display = 'none';
        elements.batchOptions.style.display = 'none';
        loadOutlookAccounts();
        addLog('info', '[系统] 已切换到 Outlook 批量注册模式');
        return;
    } else {
        isOutlookBatchMode = false;
        elements.outlookBatchSection.style.display = 'none';
        elements.regModeGroup.style.display = 'block';
    }

    // 显示服务信息
    if (type === 'outlook') {
        const service = availableServices.outlook.services.find(s => s.id == id);
        if (service) {
            addLog('info', `[系统] 已选择 Outlook 账户: ${service.name}`);
        }
    } else if (type === 'moe_mail') {
        const service = availableServices.moe_mail.services.find(s => s.id == id);
        if (service) {
            addLog('info', `[系统] 已选择自定义域名服务: ${service.name}`);
        }
    } else if (type === 'temp_mail') {
        const service = availableServices.temp_mail.services.find(s => s.id == id);
        if (service) {
            addLog('info', `[系统] 已选择 Temp-Mail 自部署服务: ${service.name}`);
        }
    } else if (type === 'duck_mail') {
        const service = availableServices.duck_mail.services.find(s => s.id == id);
        if (service) {
            addLog('info', `[系统] 已选择 DuckMail 服务: ${service.name}`);
        }
    } else if (type === 'freemail') {
        const service = availableServices.freemail.services.find(s => s.id == id);
        if (service) {
            addLog('info', `[系统] 已选择 Freemail 服务: ${service.name}`);
        }
    }
}

// 模式切换
function isUnlimitedRegistrationMode() {
    return elements.regMode.value === 'unlimited';
}

function handleModeChange(e) {
    const mode = e.target.value;
    isBatchMode = isBatchRegistrationModeSelected();

    elements.batchCountGroup.style.display = mode === 'batch' ? 'block' : 'none';
    elements.batchOptions.style.display = isBatchMode ? 'block' : 'none';
}

// 并发模式切换（批量）
function handleConcurrencyModeChange(selectEl, hintEl, intervalGroupEl) {
    const mode = selectEl.value;
    if (mode === 'parallel') {
        hintEl.textContent = '所有任务分成 N 个并发批次同时执行';
        intervalGroupEl.style.display = 'none';
    } else {
        hintEl.textContent = '同时最多运行 N 个任务，每隔 interval 秒启动新任务';
        intervalGroupEl.style.display = 'block';
    }
}

// 开始注册
async function handleStartRegistration(e) {
    e.preventDefault();

    const selectedValue = elements.emailService.value;
    if (!selectedValue) {
        toast.error('请选择一个邮箱服务');
        return;
    }

    // 处理 Outlook 批量注册模式
    if (isOutlookBatchMode) {
        await handleOutlookBatchRegistration();
        return;
    }

    const [emailServiceType, serviceId] = selectedValue.split(':');

    // 禁用开始按钮
    elements.startBtn.disabled = true;
    elements.cancelBtn.disabled = false;
    switchWorkbenchView('running');

    // 清空日志
    elements.consoleLog.innerHTML = '';
    resetRegistrationStreamViewState();

    // 构建请求数据（代理从设置中自动获取）
    const useProxy = !!elements.useProxy?.checked;
    const staticProxy = useProxy ? ((elements.proxy?.value || '').trim() || null) : null;
    const requestData = {
        email_service_type: emailServiceType,
        pipeline_key: elements.pipelineKey ? (elements.pipelineKey.value || 'current_pipeline') : 'current_pipeline',
        use_proxy: useProxy,
        proxy: staticProxy,
        auto_upload_cpa: elements.autoUploadCpa ? elements.autoUploadCpa.checked : false,
        cpa_service_ids: elements.autoUploadCpa && elements.autoUploadCpa.checked ? getSelectedServiceIds(elements.cpaServiceSelect) : [],
        auto_upload_sub2api: elements.autoUploadSub2api ? elements.autoUploadSub2api.checked : false,
        sub2api_service_ids: elements.autoUploadSub2api && elements.autoUploadSub2api.checked ? getSelectedServiceIds(elements.sub2apiServiceSelect) : [],
        auto_upload_tm: elements.autoUploadTm ? elements.autoUploadTm.checked : false,
        tm_service_ids: elements.autoUploadTm && elements.autoUploadTm.checked ? getSelectedServiceIds(elements.tmServiceSelect) : [],
    };

    // 如果选择了数据库中的服务，传递 service_id
    if (serviceId && serviceId !== 'default') {
        requestData.email_service_id = parseInt(serviceId);
    }

    isBatchMode = isBatchRegistrationModeSelected();
    if (isBatchMode) {
        await handleBatchRegistration(requestData);
    } else {
        await handleSingleRegistration(requestData);
    }
}

// 单次注册
async function handleSingleRegistration(requestData) {
    // 重置任务状态
    taskCompleted = false;
    taskFinalStatus = null;
    displayedLogs.clear();  // 清空日志去重集合
    toastShown = false;  // 重置 toast 标志
    currentBatch = null;
    activeBatchId = null;
    resetRegistrationStreamViewState();
    switchWorkbenchView('running');
    setRunningWorkbenchMode('single');

    addLog('info', '[系统] 正在启动注册任务...');

    try {
        const data = await api.post('/registration/start', requestData);

        currentTask = data;
        activeTaskUuid = data.task_uuid;  // 保存用于重连
        singleTaskStartedAtMs = Date.now();
        // 持久化到 sessionStorage，跨页面导航后可恢复
        sessionStorage.setItem('activeTask', JSON.stringify({
            task_uuid: data.task_uuid,
            mode: 'single',
            started_at: new Date(singleTaskStartedAtMs).toISOString(),
        }));
        addLog('info', `[系统] 任务已创建: ${data.task_uuid}`);
        showTaskStatus(data);
        updateTaskStatus('running');
        loadRecentRegistrationTasks();
        const taskDetailRefresh = refreshTaskDetail(data.task_uuid);

        // 优先使用 WebSocket
        connectWebSocket(data.task_uuid);
        await taskDetailRefresh;

    } catch (error) {
        addLog('error', `[错误] 启动失败: ${error.message}`);
        toast.error(error.message);
        resetButtons();
    }
}


// ============== WebSocket 功能 ==============

function isTerminalTaskStatus(status) {
    return ['completed', 'failed', 'cancelled', 'cancelling'].includes(status);
}

function finalizeSingleTaskIfTerminal(taskUuid, status) {
    if (!status || !isTerminalTaskStatus(status)) {
        return false;
    }

    // 避免重复收尾（例如：snapshot_required 拉到终态 snapshot 后，又收到 status_changed）
    if (taskCompleted && taskFinalStatus === status) {
        return true;
    }

    taskFinalStatus = status;
    taskCompleted = true;

    // 先停掉所有 fallback，避免收尾后继续刷屏
    stopTaskStreamPolling();
    stopLogPolling();

    rememberSingleTaskStart(currentTask || registrationStreamState?.task, registrationStreamState?.taskProgress);
    const finalElapsedText = Number.isFinite(singleTaskStartedAtMs)
        ? formatElapsedMsToClock(Date.now() - singleTaskStartedAtMs)
        : (elements.singleProgressElapsed?.textContent || '00:00:00');
    setSingleTaskElapsedText(finalElapsedText);
    stopRegistrationRuntimeTicker();

    // 先断开 WebSocket，让 onclose 能基于 taskFinalStatus/taskCompleted 做出正确分支判断
    disconnectWebSocket();

    // 让 realtime store 的连接状态收口（meta.local=true，不污染服务端 cursor）
    emitConnectionStateChanged('disconnected');

    elements.startBtn.disabled = false;
    elements.cancelBtn.disabled = true;
    activeTaskUuid = null;
    sessionStorage.removeItem('activeTask');
    setSingleTaskElapsedText(finalElapsedText);

    if (!toastShown) {
        toastShown = true;
        if (status === 'completed') {
            addLog('success', '[成功] 注册成功！');
            toast.success('注册成功！');
            loadRecentAccounts();
            loadRecentRegistrationTasks();
        } else if (status === 'failed') {
            addLog('error', '[错误] 注册失败');
            toast.error('注册失败');
            loadRecentRegistrationTasks();
        } else if (status === 'cancelled' || status === 'cancelling') {
            addLog('warning', '[警告] 任务已取消');
            loadRecentRegistrationTasks();
        }
    }
    return true;
}

function isTerminalBatchStatus(status) {
    return ['completed', 'failed', 'cancelled', 'cancelling'].includes(status);
}

function finalizeBatchIfTerminal(batchId, payload) {
    const safePayload = payload && typeof payload === 'object' ? payload : {};
    const finished = !!safePayload.finished;
    const status = safePayload.status || safePayload.final_status;
    const isTerminal = finished || isTerminalBatchStatus(status);
    if (!isTerminal) {
        return false;
    }

    const finalStatus = status || (finished ? 'completed' : null);
    if (batchCompleted && batchFinalStatus === finalStatus) {
        return true;
    }

    batchFinalStatus = finalStatus;
    batchCompleted = true;

    stopBatchPolling();
    disconnectBatchWebSocket();

    // 让 realtime store 的连接状态收口（meta.local=true，不污染服务端 cursor）
    emitConnectionStateChanged('disconnected');

    resetButtons();

    if (!toastShown) {
        toastShown = true;
        const isOutlook = !!(
            isOutlookBatchMode ||
            (currentBatch && Array.isArray(currentBatch.service_ids))
        );
        const success = safePayload.success || 0;
        const failed = safePayload.failed || 0;
        const skipped = safePayload.skipped || 0;
        if (batchFinalStatus === 'completed') {
            if (isOutlook) {
                addLog('success', `[完成] Outlook 批量任务完成！成功: ${success}, 失败: ${failed}, 跳过: ${skipped}`);
                if (success > 0) {
                    toast.success(`Outlook 批量注册完成，成功 ${success} 个`);
                    loadRecentAccounts();
                    loadRecentRegistrationTasks();
                } else {
                    toast.warning('Outlook 批量注册完成，但没有成功注册任何账号');
                    loadRecentRegistrationTasks();
                }
            } else {
                addLog('info', `[完成] 批量任务完成！成功: ${success}, 失败: ${failed}`);
                if (success > 0) {
                    toast.success(`批量注册完成，成功 ${success} 个`);
                    loadRecentAccounts();
                    loadRecentRegistrationTasks();
                } else {
                    toast.warning('批量注册完成，但没有成功注册任何账号');
                    loadRecentRegistrationTasks();
                }
            }
        } else if (batchFinalStatus === 'failed') {
            addLog('error', '[错误] 批量任务执行失败');
            toast.error('批量任务执行失败');
            loadRecentRegistrationTasks();
        } else if (batchFinalStatus === 'cancelled' || batchFinalStatus === 'cancelling') {
            addLog('warning', '[警告] 批量任务已取消');
            loadRecentRegistrationTasks();
        }
    }
    return true;
}

function startBatchFallbackPolling(batchId) {
    const isOutlook = !!(
        isOutlookBatchMode ||
        (currentBatch && Array.isArray(currentBatch.service_ids))
    );
    if (isOutlook) {
        startOutlookBatchPolling(batchId);
        return;
    }
    startBatchPolling(batchId);
}

function stopWebSocketHandshakeTimeout() {
    if (wsHandshakeTimeout) {
        clearTimeout(wsHandshakeTimeout);
        wsHandshakeTimeout = null;
    }
}

function stopBatchWebSocketHandshakeTimeout() {
    if (batchWsHandshakeTimeout) {
        clearTimeout(batchWsHandshakeTimeout);
        batchWsHandshakeTimeout = null;
    }
}

function handoverSingleTaskToPolling(taskUuid, socket) {
    stopWebSocketHandshakeTimeout();
    stopWebSocketHeartbeat();

    if (socket && webSocket === socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        try {
            socket.close();
        } catch (error) {
            console.warn('关闭单任务 WebSocket 失败:', error);
        }
        webSocket = null;
    }

    if (taskCompleted || taskFinalStatus !== null) {
        emitConnectionStateChanged('disconnected');
        return;
    }

    useWebSocket = false;
    emitConnectionStateChanged('polling');
    startTaskStreamPolling(taskUuid);
}

function handoverBatchTaskToPolling(batchId, socket) {
    stopBatchWebSocketHandshakeTimeout();
    stopBatchWebSocketHeartbeat();

    if (socket && batchWebSocket === socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        try {
            socket.close();
        } catch (error) {
            console.warn('关闭批量任务 WebSocket 失败:', error);
        }
        batchWebSocket = null;
    }

    if (batchCompleted || batchFinalStatus !== null) {
        emitConnectionStateChanged('disconnected');
        return;
    }

    emitConnectionStateChanged('polling');
    startBatchFallbackPolling(batchId);
}

// 连接 WebSocket
function connectWebSocket(taskUuid) {
    emitConnectionStateChanged('reconnecting');
    stopWebSocketHandshakeTimeout();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const streamId = `task:${taskUuid}`;
    const afterSeq = registrationStreamState?.cursors?.[streamId] || 0;
    const wsUrl = `${protocol}//${window.location.host}/api/ws/task/${taskUuid}?after_seq=${afterSeq}`;

    try {
        webSocket = new WebSocket(wsUrl);
        const currentSocket = webSocket;
        currentSocket.__handshakeCompleted = false;

        wsHandshakeTimeout = setTimeout(() => {
            if (webSocket !== currentSocket || taskCompleted || taskFinalStatus !== null) {
                return;
            }
            if (currentSocket.__handshakeCompleted === true) {
                return;
            }
            console.warn('WebSocket 握手超时，切换到 stream polling');
            handoverSingleTaskToPolling(taskUuid, currentSocket);
        }, REGISTRATION_WS_HANDSHAKE_TIMEOUT_MS);

        webSocket.onopen = () => {
            console.log('WebSocket 连接成功');
            currentSocket.__handshakeCompleted = true;
            stopWebSocketHandshakeTimeout();
            useWebSocket = true;
            emitConnectionStateChanged('connected');
            // 停止轮询（如果有）
            stopLogPolling();
            stopTaskStreamPolling();
            // 开始心跳
            startWebSocketHeartbeat();
        };

        webSocket.onmessage = async (event) => {
            currentSocket.__handshakeCompleted = true;
            stopWebSocketHandshakeTimeout();
            const data = JSON.parse(event.data);

            // 控制消息（旧协议）
            if (data.type === 'pong') {
                // 心跳响应，忽略
                return;
            }

            // 新协议：stream envelope
            if (data && typeof data.kind === 'string' && typeof data.stream === 'string') {
                if (data.kind === 'snapshot_required') {
                    // 最小兼容兜底：只有在 shared runtime / shim 都不可用时，
                    // 才退回旧 logs 轮询，保证页面仍有基本反馈。
                    // 注意：这条链路不作为注册工作台的主实时来源。
                    if (!hasRegistrationSharedRuntime() && typeof window?.registrationStream?.reduce !== 'function') {
                        startLogPolling(taskUuid);
                        return;
                    }
                    reduceRegistrationStream(data);
                    try {
                        const snapshot = await api.get(`/registration/streams/task/${taskUuid}/snapshot`);
                        reduceRegistrationStream(snapshot);
                        finalizeSingleTaskIfTerminal(taskUuid, snapshot?.payload?.task?.status);
                    } catch (error) {
                        console.error('获取 task snapshot 失败:', error);
                    }
                    return;
                }

                if (typeof data.seq === 'number') {
                    reduceRegistrationStream(data);

                    if (data.kind === 'task_status_changed') {
                        const status = data?.payload?.status;
                        if (status) {
                            refreshTaskDetail(taskUuid);
                        }

                        // 检查是否完成
                        finalizeSingleTaskIfTerminal(taskUuid, status);
                    }
                    return;
                }
            }

            // 兼容：旧 data.type === log/status
            if (data.type === 'log') {
                const logType = getLogType(data.message);
                addLog(logType, data.message);
            } else if (data.type === 'status') {
                updateTaskStatus(data.status);
                refreshTaskDetail(taskUuid);

                finalizeSingleTaskIfTerminal(taskUuid, data.status);
            }
        };

        webSocket.onclose = (event) => {
            console.log('WebSocket 连接关闭:', event.code);
            stopWebSocketHandshakeTimeout();
            stopWebSocketHeartbeat();

            // 只有在任务未完成且最终状态不是完成状态时才切换到轮询
            // 使用 taskFinalStatus 而不是 currentTask.status，因为 currentTask 可能已被重置
            const shouldPoll = !taskCompleted &&
                               taskFinalStatus === null;  // 如果 taskFinalStatus 有值，说明任务已完成

            if (shouldPoll && currentTask) {
                console.log('切换到轮询模式');
                useWebSocket = false;
                emitConnectionStateChanged('polling');
                startTaskStreamPolling(currentTask.task_uuid);
            } else if (!shouldPoll) {
                emitConnectionStateChanged('disconnected');
            }
        };

        webSocket.onerror = (error) => {
            console.error('WebSocket 错误:', error);
            handoverSingleTaskToPolling(taskUuid, currentSocket);
        };

    } catch (error) {
        console.error('WebSocket 连接失败:', error);
        stopWebSocketHandshakeTimeout();
        handoverSingleTaskToPolling(taskUuid, webSocket);
    }
}

// 断开 WebSocket
function disconnectWebSocket() {
    stopWebSocketHandshakeTimeout();
    stopWebSocketHeartbeat();
    if (webSocket) {
        webSocket.close();
        webSocket = null;
    }
}

// 开始心跳
function startWebSocketHeartbeat() {
    stopWebSocketHeartbeat();
    wsHeartbeatInterval = setInterval(() => {
        if (webSocket && webSocket.readyState === WebSocket.OPEN) {
            webSocket.send(JSON.stringify({ type: 'ping' }));
        }
    }, 25000);  // 每 25 秒发送一次心跳
}

// 停止心跳
function stopWebSocketHeartbeat() {
    if (wsHeartbeatInterval) {
        clearInterval(wsHeartbeatInterval);
        wsHeartbeatInterval = null;
    }
}

// 发送取消请求
function cancelViaWebSocket() {
    if (webSocket && webSocket.readyState === WebSocket.OPEN) {
        webSocket.send(JSON.stringify({ type: 'cancel' }));
    }
}

// ============== task stream polling fallback（方案 C） ==============

function startTaskStreamPolling(taskUuid) {
    stopTaskStreamPolling();
    emitConnectionStateChanged('polling');

    // 先补一份 snapshot，保证轮询期间 UI 有完整初始态
    (async () => {
        try {
            const snapshot = await api.get(`/registration/streams/task/${taskUuid}/snapshot`);
            reduceRegistrationStream(snapshot);
            emitConnectionStateChanged('polling');
            finalizeSingleTaskIfTerminal(taskUuid, snapshot?.payload?.task?.status);
        } catch (error) {
            console.error('轮询模式获取 task snapshot 失败:', error);
        }
    })();

    streamPollingInterval = setInterval(async () => {
        if (streamPollingInFlight) {
            return;
        }
        streamPollingInFlight = true;
        try {
            const streamId = `task:${taskUuid}`;
            const afterSeq = registrationStreamState?.cursors?.[streamId] || 0;
            const data = await api.get(`/registration/streams/task/${taskUuid}/events?after_seq=${afterSeq}`);
            const events = Array.isArray(data?.events) ? data.events : [];
            for (const event of events) {
                reduceRegistrationStream(event);
            }
            emitConnectionStateChanged('polling');

            const status = registrationStreamState?.task?.status;
            finalizeSingleTaskIfTerminal(taskUuid, status);
        } catch (error) {
            console.error('轮询 task stream 失败:', error);
        } finally {
            streamPollingInFlight = false;
        }
    }, 1000);
}

function stopTaskStreamPolling() {
    if (streamPollingInterval) {
        clearInterval(streamPollingInterval);
        streamPollingInterval = null;
    }
    streamPollingInFlight = false;
}

// 批量注册
async function handleBatchRegistration(requestData) {
    // 重置批量任务状态
    batchCompleted = false;
    batchFinalStatus = null;
    displayedLogs.clear();  // 清空日志去重集合
    toastShown = false;  // 重置 toast 标志
    currentTask = null;
    activeTaskUuid = null;
    resetRegistrationStreamViewState();
    switchWorkbenchView('running');
    setRunningWorkbenchMode('batch');

    const count = isUnlimitedRegistrationMode()
        ? 0
        : Math.min(500, Math.max(1, parseInt(elements.batchCount.value, 10) || 5));
    const intervalMin = parseInt(elements.intervalMin.value, 10) || 5;
    const intervalMax = parseInt(elements.intervalMax.value, 10) || 30;
    const concurrency = parseInt(elements.concurrencyCount.value, 10) || 3;
    const mode = elements.concurrencyMode.value || 'pipeline';

    requestData.pipeline_key = requestData.pipeline_key || (elements.pipelineKey ? (elements.pipelineKey.value || 'current_pipeline') : 'current_pipeline');
    requestData.count = count;
    requestData.interval_min = intervalMin;
    requestData.interval_max = intervalMax;
    requestData.concurrency = Math.min(50, Math.max(1, concurrency));
    requestData.mode = mode;

    if (count === 0) {
        addLog('info', '[系统] 正在启动无限注册任务...');
    } else {
        addLog('info', `[系统] 正在启动批量注册任务 (数量: ${count})...`);
    }

    try {
        const data = await api.post('/registration/batch', requestData);

        currentBatch = data;
        activeBatchId = data.batch_id;  // 保存用于重连
        batchTaskStartedAtMs = Date.now();
        // 持久化到 sessionStorage，跨页面导航后可恢复
        sessionStorage.setItem('activeTask', JSON.stringify({
            batch_id: data.batch_id,
            mode: isUnlimitedRegistrationMode() ? 'unlimited' : 'batch',
            total: data.count,
            started_at: new Date(batchTaskStartedAtMs).toISOString(),
        }));
        addLog('info', `[系统] 批量任务已创建: ${data.batch_id}`);
        addLog('info', count === 0
            ? '[系统] 已进入无限注册模式'
            : `[系统] 共 ${data.count} 个任务已加入队列`);
        showBatchStatus(data);

        // 优先使用 WebSocket
        connectBatchWebSocket(data.batch_id);

    } catch (error) {
        addLog('error', `[错误] 启动失败: ${error.message}`);
        toast.error(error.message);
        resetButtons();
    }
}

// 取消任务
async function handleCancelTask() {
    // 禁用取消按钮，防止重复点击
    elements.cancelBtn.disabled = true;
    addLog('info', '[系统] 正在提交取消请求...');

    try {
        // 批量任务取消（包括普通批量模式和 Outlook 批量模式）
        if (currentBatch && (isBatchMode || isOutlookBatchMode)) {
            // 优先通过 WebSocket 取消
            if (batchWebSocket && batchWebSocket.readyState === WebSocket.OPEN) {
                batchWebSocket.send(JSON.stringify({ type: 'cancel' }));
                addLog('warning', '[警告] 批量任务取消请求已提交');
                toast.info('任务取消请求已提交');
            } else {
                // 降级到 REST API
                const endpoint = isOutlookBatchMode
                    ? `/registration/outlook-batch/${currentBatch.batch_id}/cancel`
                    : `/registration/batch/${currentBatch.batch_id}/cancel`;

                await api.post(endpoint);
                addLog('warning', '[警告] 批量任务取消请求已提交');
                toast.info('任务取消请求已提交');
                stopBatchPolling();
                resetButtons();
            }
        }
        // 单次任务取消
        else if (currentTask) {
            // 优先通过 WebSocket 取消
            if (webSocket && webSocket.readyState === WebSocket.OPEN) {
                webSocket.send(JSON.stringify({ type: 'cancel' }));
                addLog('warning', '[警告] 任务取消请求已提交');
                toast.info('任务取消请求已提交');
            } else {
                // 降级到 REST API
                await api.post(`/registration/tasks/${currentTask.task_uuid}/cancel`);
                addLog('warning', '[警告] 任务已取消');
                toast.info('任务已取消');
                stopLogPolling();
                stopTaskStreamPolling();
                resetButtons();
            }
        }
        // 没有活动任务
        else {
            addLog('warning', '[警告] 没有活动的任务可以取消');
            toast.warning('没有活动的任务');
            resetButtons();
        }
    } catch (error) {
        addLog('error', `[错误] 取消失败: ${error.message}`);
        toast.error(error.message);
        // 恢复取消按钮，允许重试
        elements.cancelBtn.disabled = false;
    }
}

// ============== Legacy fallback：最后兜底的旧日志轮询 ==============

// 开始轮询日志
function startLogPolling(taskUuid) {
    emitConnectionStateChanged('polling');
    let lastLogIndex = 0;

    logPollingInterval = setInterval(async () => {
        try {
            const data = await api.get(`/registration/tasks/${taskUuid}/logs`);
            await refreshTaskDetail(taskUuid);

            // 更新任务状态
            updateTaskStatus(data.status);

            // 更新邮箱信息
            if (data.email) {
                elements.taskEmail.textContent = data.email;
            }
            if (data.email_service) {
                elements.taskService.textContent = getServiceTypeText(data.email_service);
            }

            // 添加新日志
            const logs = data.logs || [];
            for (let i = lastLogIndex; i < logs.length; i++) {
                const log = logs[i];
                const logType = getLogType(log);
                addLog(logType, log);
            }
            lastLogIndex = logs.length;

            // 检查任务是否完成
            if (['completed', 'failed', 'cancelled'].includes(data.status)) {
                stopLogPolling();
                resetButtons();

                // 只显示一次 toast
                if (!toastShown) {
                    toastShown = true;
                    if (data.status === 'completed') {
                        addLog('success', '[成功] 注册成功！');
                        toast.success('注册成功！');
                        // 刷新账号列表
                        loadRecentAccounts();
                    } else if (data.status === 'failed') {
                        addLog('error', '[错误] 注册失败');
                        toast.error('注册失败');
                    } else if (data.status === 'cancelled') {
                        addLog('warning', '[警告] 任务已取消');
                    }
                }
            }
        } catch (error) {
            console.error('轮询日志失败:', error);
        }
    }, 1000);
}

// 停止轮询日志
function stopLogPolling() {
    if (logPollingInterval) {
        clearInterval(logPollingInterval);
        logPollingInterval = null;
    }
}

// 开始轮询批量状态
function startBatchPolling(batchId) {
    batchPollingInterval = setInterval(async () => {
        try {
            const data = await api.get(`/registration/batch/${batchId}`);
            updateBatchProgress(data);

            // 检查是否完成
            if (data.finished) {
                finalizeBatchIfTerminal(batchId, { ...data, status: data.status || 'completed', finished: true });
            }
        } catch (error) {
            console.error('轮询批量状态失败:', error);
        }
    }, 2000);
}

// 停止轮询批量状态
function stopBatchPolling() {
    if (batchPollingInterval) {
        clearInterval(batchPollingInterval);
        batchPollingInterval = null;
    }
}

// 显示任务状态
function showTaskStatus(task) {
    setRunningWorkbenchMode('single');
    elements.taskStatusRow.style.display = 'grid';
    elements.batchProgressSection.style.display = 'none';
    elements.taskStatusBadge.style.display = 'inline-flex';
    elements.taskId.textContent = task.task_uuid.substring(0, 8) + '...';
    elements.taskEmail.textContent = task.email || task.email_address || '-';
    elements.taskService.textContent = task.email_service ? getServiceTypeText(task.email_service) : '-';
    if (elements.taskProxyIp) {
        elements.taskProxyIp.textContent = normalizeTaskProxyIp(task);
    }
    rememberSingleTaskStart(task, task.task_progress || registrationStreamState.taskProgress);
    renderSingleTaskProgressSummary(task.task_progress || registrationStreamState.taskProgress, registrationStreamState.currentStep);
    renderSingleTaskElapsedClock();
    if (isTerminalTaskStatus(task.status)) {
        stopRegistrationRuntimeTicker();
        return;
    }
    ensureRegistrationRuntimeTicker();
}

// 更新任务状态
function updateTaskStatus(status) {
    const statusInfo = {
        pending: { text: '等待中', class: 'pending' },
        running: { text: '运行中', class: 'running' },
        completed: { text: '已完成', class: 'completed' },
        failed: { text: '失败', class: 'failed' },
        cancelled: { text: '已取消', class: 'disabled' }
    };

    const info = statusInfo[status] || { text: status, class: '' };
    elements.taskStatusBadge.textContent = info.text;
    elements.taskStatusBadge.className = `status-badge ${info.class}`;
    elements.taskStatus.textContent = info.text;
}

async function refreshTaskDetail(taskUuid) {
    if (!taskUuid) return null;
    try {
        const detail = await api.get(`/registration/tasks/${taskUuid}`);
        if (!detail) return null;
        currentTask = { ...(currentTask || {}), ...detail };
        showTaskStatus(currentTask);
        if (detail.status) {
            updateTaskStatus(detail.status);
        }
        return currentTask;
    } catch (error) {
        console.error('加载任务详情失败:', error);
        return null;
    }
}

function normalizeProgressPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return 0;
    }
    return Math.max(0, Math.min(100, numeric));
}

function renderSingleTaskProgressSummary(taskProgress, currentStep) {
    if (!elements.singleProgressCard) return;

    if (!taskProgress || typeof taskProgress !== 'object') {
        elements.singleProgressCard.style.display = 'none';
        if (elements.singleProgressCurrentStep) elements.singleProgressCurrentStep.textContent = '-';
        if (elements.singleProgressStepText) elements.singleProgressStepText.textContent = '第 0 / 0 步';
        if (elements.singleProgressBar) elements.singleProgressBar.style.width = '0%';
        setSingleTaskElapsedText('00:00:00');
        return;
    }

    const stepIndex = Number.isFinite(taskProgress.step_index) ? taskProgress.step_index : 0;
    const totalSteps = Number.isFinite(taskProgress.total_steps) ? taskProgress.total_steps : 0;
    const percent = normalizeProgressPercent(taskProgress.progress_percent);
    const currentStepKey = currentStep?.step_key || taskProgress.step_key || '-';

    elements.singleProgressCard.style.display = 'block';
    if (elements.singleProgressCurrentStep) elements.singleProgressCurrentStep.textContent = currentStepKey;
    if (elements.singleProgressStepText) elements.singleProgressStepText.textContent = `第 ${stepIndex} / ${totalSteps} 步`;
    if (elements.singleProgressBar) elements.singleProgressBar.style.width = `${percent}%`;
    renderSingleTaskElapsedClock();
}

// 显示批量状态
function showBatchStatus(batch) {
    setRunningWorkbenchMode('batch');
    const isUnlimited = !!(batch && (batch.is_unlimited || batch.count === 0));

    elements.batchProgressSection.style.display = 'block';
    elements.taskStatusRow.style.display = 'none';
    elements.taskStatusBadge.style.display = 'none';
    rememberBatchTaskStart(batch);
    renderSingleTaskProgressSummary(null, null);
    elements.batchProgressText.textContent = isUnlimited ? '0/∞' : `0/${batch.count}`;
    elements.batchProgressPercent.textContent = isUnlimited ? '运行中' : '0%';
    elements.progressBar.style.width = isUnlimited ? '100%' : '0%';
    elements.progressBar.classList.toggle('indeterminate', isUnlimited);
    elements.batchSuccess.textContent = '0';
    elements.batchFailed.textContent = '0';
    elements.batchRemaining.textContent = isUnlimited ? '不限' : batch.count;
    elements.batchConsecutiveFailures.textContent = '0/0';
    setBatchElapsedTexts('00:00:00', '—');
    renderBatchDomainStats([]);
    ensureRegistrationRuntimeTicker();

    // 重置计数器
    elements.batchSuccess.dataset.last = '0';
    elements.batchFailed.dataset.last = '0';
}

// 更新批量进度
function updateBatchProgress(data) {
    currentBatch = { ...(currentBatch || {}), ...(data || {}) };
    rememberBatchTaskStart(currentBatch);
    if (data.is_unlimited) {
        elements.batchProgressText.textContent = `${data.completed}/∞`;
        elements.batchProgressPercent.textContent = data.finished ? '已结束' : '运行中';
        elements.progressBar.classList.add('indeterminate');
        elements.progressBar.style.width = '100%';
        elements.batchSuccess.textContent = data.success;
        elements.batchFailed.textContent = data.failed;
        elements.batchRemaining.textContent = '不限';
        elements.batchConsecutiveFailures.textContent = `${data.consecutive_failures || 0}/${data.max_consecutive_failures || 0}`;
        renderBatchDomainStats(data.finished ? (data.domain_stats || []) : []);
        renderBatchRuntimeMetrics();
        return;
    }

    elements.progressBar.classList.remove('indeterminate');
    const progress = ((data.completed / data.total) * 100).toFixed(0);
    elements.batchProgressText.textContent = `${data.completed}/${data.total}`;
    elements.batchProgressPercent.textContent = `${progress}%`;
    elements.progressBar.style.width = `${progress}%`;
    elements.batchSuccess.textContent = data.success;
    elements.batchFailed.textContent = data.failed;
    elements.batchRemaining.textContent = data.total - data.completed;
    if (data.max_consecutive_failures !== undefined && data.max_consecutive_failures !== null) {
        elements.batchConsecutiveFailures.textContent = `${data.consecutive_failures || 0}/${data.max_consecutive_failures}`;
    } else {
        elements.batchConsecutiveFailures.textContent = '-';
    }
    renderBatchDomainStats(data.finished ? (data.domain_stats || []) : []);
    renderBatchRuntimeMetrics();

    // 记录日志（避免重复）
    if (data.completed > 0) {
        const lastSuccess = parseInt(elements.batchSuccess.dataset.last || '0');
        const lastFailed = parseInt(elements.batchFailed.dataset.last || '0');

        if (data.success > lastSuccess) {
            addLog('success', `[成功] 第 ${data.success} 个账号注册成功`);
        }
        if (data.failed > lastFailed) {
            addLog('error', `[失败] 第 ${data.failed} 个账号注册失败`);
        }

        elements.batchSuccess.dataset.last = data.success;
        elements.batchFailed.dataset.last = data.failed;
    }
}

function renderBatchDomainStats(rows) {
    if (!rows || rows.length === 0) {
        elements.batchDomainStats.innerHTML = '';
        elements.batchDomainStats.style.display = 'none';
        return;
    }

    const html = rows.map(row => `
        <tr>
            <td>${escapeHtml(row.domain || '-')}</td>
            <td>${row.total || 0}</td>
            <td>${row.success || 0}</td>
            <td>${row.failed || 0}</td>
            <td>${formatDomainRate(row.success_rate, row.success, row.total)}</td>
            <td>${formatDomainRate(row.failure_rate, row.failed, row.total)}</td>
        </tr>
    `).join('');

    elements.batchDomainStats.innerHTML = `
        <div style="margin-top: var(--spacing-sm);">
            <div style="font-weight: 500; margin-bottom: var(--spacing-xs);">域名统计</div>
            <div style="max-height: 160px; overflow-y: auto;">
                <table class="data-table" style="font-size: 0.8125rem;">
                    <thead>
                        <tr>
                            <th>域名</th>
                            <th>总计</th>
                            <th>成功</th>
                            <th>失败</th>
                            <th>成功率</th>
                            <th>失败率</th>
                        </tr>
                    </thead>
                    <tbody>${html}</tbody>
                </table>
            </div>
        </div>
    `;
    elements.batchDomainStats.style.display = 'block';
}

function formatDomainRate(rate, count, total) {
    if (typeof rate === 'number' && Number.isFinite(rate)) {
        return `${rate.toFixed(2)}%`;
    }
    if (!total) return '0.00%';
    return `${((count || 0) / total * 100).toFixed(2)}%`;
}

function getTaskStatusBadgeHtml(status) {
    const normalized = String(status || '').trim().toLowerCase();
    const mapping = {
        pending: { text: '等待中', className: 'pending' },
        running: { text: '运行中', className: 'running' },
        completed: { text: '已完成', className: 'completed' },
        failed: { text: '失败', className: 'failed' },
        cancelled: { text: '已取消', className: 'disabled' },
    };
    const info = mapping[normalized] || { text: status || '未知', className: '' };
    return `<span class="status-badge ${escapeHtml(info.className)}">${escapeHtml(info.text)}</span>`;
}

function renderRecentRegistrationTasks(tasks) {
    if (!elements.recentRegistrationTasksTable) {
        return;
    }
    const rows = Array.isArray(tasks) ? tasks : [];
    if (rows.length === 0) {
        elements.recentRegistrationTasksTable.innerHTML = `
            <tr>
                <td colspan="5">
                    <div class="empty-state" style="padding: var(--spacing-md);">
                        <div class="empty-state-icon">🧾</div>
                        <div class="empty-state-title">暂无任务记录</div>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    elements.recentRegistrationTasksTable.innerHTML = rows.map((task) => `
        <tr data-task-uuid="${escapeHtml(task.task_uuid || '')}">
            <td>${escapeHtml(String(task.task_uuid || '').slice(0, 8) || '—')}...</td>
            <td>${escapeHtml(task.email || task.email_address || '—')}</td>
            <td>${escapeHtml(task.email_service_id != null ? String(task.email_service_id) : '—')}</td>
            <td>${escapeHtml(normalizeTaskProxyIp(task))}</td>
            <td>${getTaskStatusBadgeHtml(task.status)}</td>
        </tr>
    `).join('');
}

async function loadRecentRegistrationTasks() {
    if (!elements.recentRegistrationTasksTable) {
        return null;
    }
    try {
        const data = await api.get('/registration/tasks?page=1&page_size=10');
        renderRecentRegistrationTasks(data?.tasks || []);
        return data;
    } catch (error) {
        console.error('加载最近任务失败:', error);
        return null;
    }
}

// 加载最近注册的账号
async function loadRecentAccounts() {
    try {
        const data = await api.get('/accounts?page=1&page_size=10');

        if (data.accounts.length === 0) {
            elements.recentAccountsTable.innerHTML = `
                <tr>
                    <td colspan="5">
                        <div class="empty-state" style="padding: var(--spacing-md);">
                            <div class="empty-state-icon">📭</div>
                            <div class="empty-state-title">暂无已注册账号</div>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        elements.recentAccountsTable.innerHTML = data.accounts.map(account => `
            <tr data-id="${account.id}">
                <td>${account.id}</td>
                <td>
                    <span style="display:inline-flex;align-items:center;gap:4px;">
                        <span title="${escapeHtml(account.email)}">${escapeHtml(account.email)}</span>
                        <button class="btn-copy-icon copy-email-btn" data-email="${escapeHtml(account.email)}" title="复制邮箱">📋</button>
                    </span>
                </td>
                <td class="password-cell">
                    ${account.password
                        ? `<span style="display:inline-flex;align-items:center;gap:4px;">
                            <span class="password-hidden" title="点击查看">${escapeHtml(account.password.substring(0, 8))}...</span>
                            <button class="btn-copy-icon copy-pwd-btn" data-pwd="${escapeHtml(account.password)}" title="复制密码">📋</button>
                           </span>`
                        : '-'}
                </td>
                <td>
                    ${getStatusIcon(account.status)}
                </td>
            </tr>
        `).join('');

        // 绑定复制按钮事件
        elements.recentAccountsTable.querySelectorAll('.copy-email-btn').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); copyToClipboard(btn.dataset.email); });
        });
        elements.recentAccountsTable.querySelectorAll('.copy-pwd-btn').forEach(btn => {
            btn.addEventListener('click', (e) => { e.stopPropagation(); copyToClipboard(btn.dataset.pwd); });
        });

    } catch (error) {
        console.error('加载账号列表失败:', error);
    }
}

// 开始账号列表轮询
function startAccountsPolling() {
    // 每30秒刷新一次账号列表
    accountsPollingInterval = setInterval(() => {
        loadRecentAccounts();
        loadRecentRegistrationTasks();
    }, 30000);
}

function getRegistrationActiveStreamId() {
    if (activeBatchId) {
        return `ui:batch:${activeBatchId}`;
    }
    if (activeTaskUuid) {
        return `ui:task:${activeTaskUuid}`;
    }
    return 'ui:task:local';
}

function nextRegistrationLocalEventSeq() {
    registrationLocalEventSeq += 1;
    return registrationLocalEventSeq;
}

function getRegistrationLogLevel(type, message) {
    const normalizedType = String(type || '').trim().toLowerCase();
    if (normalizedType === 'error') return 'ERROR';
    if (normalizedType === 'warning' || normalizedType === 'warn') return 'WARN';
    const normalizedMessage = String(message || '').toUpperCase();
    if (normalizedMessage.includes('[ERROR]')) return 'ERROR';
    if (normalizedMessage.includes('[WARN]')) return 'WARN';
    return 'INFO';
}

function buildRegistrationLocalLogEntry(type, message, streamId, seq) {
    const now = new Date();
    const displayTime = now.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
    const timestamp = now.toISOString();
    const level = getRegistrationLogLevel(type, message);
    return {
        seq,
        stream: streamId,
        timestamp,
        display_time: displayTime,
        level,
        message,
        raw: `[${displayTime}] ${message}`,
        source: 'ui',
    };
}

function addLog(type, message) {
    const normalizedMessage = String(message || '').trim();
    if (!normalizedMessage) {
        return false;
    }

    if (!hasRegistrationSharedRuntime() && typeof window?.registrationStream?.reduce !== 'function') {
        return appendLegacyLogLine(type, normalizedMessage, { dedupeByMessage: true });
    }

    const logKey = `${type}:${normalizedMessage}`;
    if (displayedLogs.has(logKey)) {
        return false;
    }
    displayedLogs.add(logKey);

    if (displayedLogs.size > 1000) {
        const keys = Array.from(displayedLogs);
        keys.slice(0, 500).forEach(key => displayedLogs.delete(key));
    }

    const streamId = getRegistrationActiveStreamId();
    const seq = nextRegistrationLocalEventSeq();
    const entry = buildRegistrationLocalLogEntry(type, normalizedMessage, streamId, seq);

    reduceRegistrationStream({
        seq,
        stream: streamId,
        kind: 'log_appended',
        payload: { entry },
        meta: { local: true },
    });
    return true;
}

function appendLegacyLogLine(type, message, options = {}) {
    if (!elements.consoleLog) return false;

    const dedupeByMessage = options.dedupeByMessage === true;
    if (dedupeByMessage) {
        const logKey = `${type}:${message}`;
        if (displayedLogs.has(logKey)) {
            return false;
        }
        displayedLogs.add(logKey);

        // 限制去重集合大小，避免内存泄漏
        if (displayedLogs.size > 1000) {
            const keys = Array.from(displayedLogs);
            keys.slice(0, 500).forEach(k => displayedLogs.delete(k));
        }
    }

    const line = document.createElement('div');
    line.className = `log-line ${type}${isRateLimitText(message) ? ' rate-limit' : ''}`;

    const timestamp = new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });

    line.innerHTML = `<span class="timestamp">[${timestamp}]</span>${escapeHtml(message)}${isRateLimitText(message) ? '<span class="failure-badge failure-badge-rate-limit">限流</span>' : ''}`;
    elements.consoleLog.appendChild(line);

    elements.consoleLog.scrollTop = elements.consoleLog.scrollHeight;

    const lines = elements.consoleLog.querySelectorAll('.log-line');
    if (lines.length > 500) {
        // 使用 removeChild，便于 JS harness 同步 children 列表；浏览器同样支持。
        elements.consoleLog.removeChild(lines[0]);
    }
    return true;
}

// 获取日志类型
function getLogType(log) {
    if (typeof log !== 'string') return 'info';

    const lowerLog = log.toLowerCase();
    if (lowerLog.includes('error') || lowerLog.includes('失败') || lowerLog.includes('错误')) {
        return 'error';
    }
    if (lowerLog.includes('warning') || lowerLog.includes('警告')) {
        return 'warning';
    }
    if (lowerLog.includes('success') || lowerLog.includes('成功') || lowerLog.includes('完成')) {
        return 'success';
    }
    return 'info';
}

// 重置按钮状态
function resetButtons() {
    elements.startBtn.disabled = false;
    elements.cancelBtn.disabled = true;
    stopRegistrationRuntimeTicker();
    singleTaskStartedAtMs = null;
    batchTaskStartedAtMs = null;
    currentTask = null;
    currentBatch = null;
    isBatchMode = isBatchRegistrationModeSelected();
    // 重置完成标志
    taskCompleted = false;
    batchCompleted = false;
    // 重置最终状态标志
    taskFinalStatus = null;
    batchFinalStatus = null;
    // 清除活跃任务标识
    activeTaskUuid = null;
    activeBatchId = null;
    // 清除 sessionStorage 持久化状态
    sessionStorage.removeItem('activeTask');
    // 断开 WebSocket
    disconnectWebSocket();
    disconnectBatchWebSocket();
    // 注意：不重置 isOutlookBatchMode，因为用户可能想继续使用 Outlook 批量模式
    setRunningWorkbenchMode('idle');
}

// HTML 转义
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}


// ============== Outlook 批量注册功能 ==============

// 加载 Outlook 账户列表
async function loadOutlookAccounts() {
    try {
        elements.outlookAccountsContainer.innerHTML = '<div class="loading-placeholder" style="text-align: center; padding: var(--spacing-md); color: var(--text-muted);">加载中...</div>';

        const data = await api.get('/registration/outlook-accounts');
        outlookAccounts = data.accounts || [];

        renderOutlookAccountsList();

        addLog('info', `[系统] 已加载 ${data.total} 个 Outlook 账户 (已注册: ${data.registered_count}, 未注册: ${data.unregistered_count})`);

    } catch (error) {
        console.error('加载 Outlook 账户列表失败:', error);
        elements.outlookAccountsContainer.innerHTML = `<div style="text-align: center; padding: var(--spacing-md); color: var(--text-muted);">加载失败: ${error.message}</div>`;
        addLog('error', `[错误] 加载 Outlook 账户列表失败: ${error.message}`);
    }
}

// 渲染 Outlook 账户列表
function renderOutlookAccountsList() {
    if (outlookAccounts.length === 0) {
        elements.outlookAccountsContainer.innerHTML = '<div style="text-align: center; padding: var(--spacing-md); color: var(--text-muted);">没有可用的 Outlook 账户</div>';
        return;
    }

    const html = outlookAccounts.map(account => `
        <label class="outlook-account-item" style="display: flex; align-items: center; padding: var(--spacing-sm); border-bottom: 1px solid var(--border-light); cursor: pointer; ${account.is_registered ? 'opacity: 0.6;' : ''}" data-id="${account.id}" data-registered="${account.is_registered}">
            <input type="checkbox" class="outlook-account-checkbox" value="${account.id}" ${account.is_registered ? '' : 'checked'} style="margin-right: var(--spacing-sm);">
            <div style="flex: 1;">
                <div style="font-weight: 500;">${escapeHtml(account.email)}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">
                    ${account.is_registered
                        ? `<span style="color: var(--success-color);">✓ 已注册</span>`
                        : '<span style="color: var(--primary-color);">未注册</span>'
                    }
                    ${account.has_oauth ? ' | OAuth' : ''}
                </div>
            </div>
        </label>
    `).join('');

    elements.outlookAccountsContainer.innerHTML = html;
}

// 全选
function selectAllOutlookAccounts() {
    const checkboxes = document.querySelectorAll('.outlook-account-checkbox');
    checkboxes.forEach(cb => cb.checked = true);
}

// 只选未注册
function selectUnregisteredOutlook() {
    const items = document.querySelectorAll('.outlook-account-item');
    items.forEach(item => {
        const checkbox = item.querySelector('.outlook-account-checkbox');
        const isRegistered = item.dataset.registered === 'true';
        checkbox.checked = !isRegistered;
    });
}

// 取消全选
function deselectAllOutlookAccounts() {
    const checkboxes = document.querySelectorAll('.outlook-account-checkbox');
    checkboxes.forEach(cb => cb.checked = false);
}

// 处理 Outlook 批量注册
async function handleOutlookBatchRegistration() {
    // 重置批量任务状态
    batchCompleted = false;
    batchFinalStatus = null;
    displayedLogs.clear();  // 清空日志去重集合
    toastShown = false;  // 重置 toast 标志
    currentTask = null;
    activeTaskUuid = null;
    resetRegistrationStreamViewState();

    // 获取选中的账户
    const selectedIds = [];
    document.querySelectorAll('.outlook-account-checkbox:checked').forEach(cb => {
        selectedIds.push(parseInt(cb.value));
    });

    if (selectedIds.length === 0) {
        toast.error('请选择至少一个 Outlook 账户');
        return;
    }

    const intervalMin = parseInt(elements.outlookIntervalMin.value) || 5;
    const intervalMax = parseInt(elements.outlookIntervalMax.value) || 30;
    const skipRegistered = elements.outlookSkipRegistered.checked;
    const concurrency = parseInt(elements.outlookConcurrencyCount.value) || 3;
    const mode = elements.outlookConcurrencyMode.value || 'pipeline';

    // 禁用开始按钮
    elements.startBtn.disabled = true;
    elements.cancelBtn.disabled = false;

    // 清空日志
    elements.consoleLog.innerHTML = '';

    const requestData = {
        service_ids: selectedIds,
        skip_registered: skipRegistered,
        interval_min: intervalMin,
        interval_max: intervalMax,
        concurrency: Math.min(50, Math.max(1, concurrency)),
        mode: mode,
        use_proxy: !!elements.useProxy?.checked,
        proxy: elements.useProxy?.checked ? ((elements.proxy?.value || '').trim() || null) : null,
        auto_upload_cpa: elements.autoUploadCpa ? elements.autoUploadCpa.checked : false,
        cpa_service_ids: elements.autoUploadCpa && elements.autoUploadCpa.checked ? getSelectedServiceIds(elements.cpaServiceSelect) : [],
        auto_upload_sub2api: elements.autoUploadSub2api ? elements.autoUploadSub2api.checked : false,
        sub2api_service_ids: elements.autoUploadSub2api && elements.autoUploadSub2api.checked ? getSelectedServiceIds(elements.sub2apiServiceSelect) : [],
        auto_upload_tm: elements.autoUploadTm ? elements.autoUploadTm.checked : false,
        tm_service_ids: elements.autoUploadTm && elements.autoUploadTm.checked ? getSelectedServiceIds(elements.tmServiceSelect) : [],
    };

    addLog('info', `[系统] 正在启动 Outlook 批量注册 (${selectedIds.length} 个账户)...`);

    try {
        const data = await api.post('/registration/outlook-batch', requestData);

        if (data.to_register === 0) {
            addLog('warning', '[警告] 所有选中的邮箱都已注册，无需重复注册');
            toast.warning('所有选中的邮箱都已注册');
            resetButtons();
            return;
        }

        currentBatch = { batch_id: data.batch_id, ...data };
        activeBatchId = data.batch_id;  // 保存用于重连
        batchTaskStartedAtMs = Date.now();
        // 持久化到 sessionStorage，跨页面导航后可恢复
        sessionStorage.setItem('activeTask', JSON.stringify({
            batch_id: data.batch_id,
            mode: isOutlookBatchMode ? 'outlook_batch' : 'batch',
            total: data.to_register,
            started_at: new Date(batchTaskStartedAtMs).toISOString(),
        }));
        addLog('info', `[系统] 批量任务已创建: ${data.batch_id}`);
        addLog('info', `[系统] 总数: ${data.total}, 跳过已注册: ${data.skipped}, 待注册: ${data.to_register}`);

        // 初始化批量状态显示
        showBatchStatus({ count: data.to_register });

        // 优先使用 WebSocket
        connectBatchWebSocket(data.batch_id);

    } catch (error) {
        addLog('error', `[错误] 启动失败: ${error.message}`);
        toast.error(error.message);
        resetButtons();
    }
}

// ============== 批量任务 WebSocket 功能 ==============

// 连接批量任务 WebSocket
function connectBatchWebSocket(batchId) {
    emitConnectionStateChanged('reconnecting');
    stopBatchWebSocketHandshakeTimeout();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const streamId = `batch:${batchId}`;
    const afterSeq = registrationStreamState?.cursors?.[streamId] || 0;
    const wsUrl = `${protocol}//${window.location.host}/api/ws/batch/${batchId}?after_seq=${afterSeq}`;

    try {
        batchWebSocket = new WebSocket(wsUrl);
        const currentSocket = batchWebSocket;
        currentSocket.__handshakeCompleted = false;

        batchWsHandshakeTimeout = setTimeout(() => {
            if (batchWebSocket !== currentSocket || batchCompleted || batchFinalStatus !== null) {
                return;
            }
            if (currentSocket.__handshakeCompleted === true) {
                return;
            }
            console.warn('批量任务 WebSocket 握手超时，切换到 polling');
            handoverBatchTaskToPolling(batchId, currentSocket);
        }, REGISTRATION_WS_HANDSHAKE_TIMEOUT_MS);

        batchWebSocket.onopen = () => {
            console.log('批量任务 WebSocket 连接成功');
            currentSocket.__handshakeCompleted = true;
            stopBatchWebSocketHandshakeTimeout();
            emitConnectionStateChanged('connected');
            // 停止轮询（如果有）
            stopBatchPolling();
            // 开始心跳
            startBatchWebSocketHeartbeat();
        };

        batchWebSocket.onmessage = async (event) => {
            currentSocket.__handshakeCompleted = true;
            stopBatchWebSocketHandshakeTimeout();
            const data = JSON.parse(event.data);

            if (data.type === 'pong') {
                // 心跳响应，忽略
                return;
            }

            // 新协议：stream envelope
            if (data && typeof data.kind === 'string' && typeof data.stream === 'string') {
                if (data.kind === 'snapshot_required') {
                    reduceRegistrationStream(data);
                    try {
                        const snapshot = await api.get(`/registration/streams/batch/${batchId}/snapshot`);
                        reduceRegistrationStream(snapshot);
                        finalizeBatchIfTerminal(batchId, snapshot?.payload?.batch);
                    } catch (error) {
                        console.error('获取 batch snapshot 失败:', error);
                    }
                    return;
                }

                if (typeof data.seq === 'number') {
                    reduceRegistrationStream(data);

                    if (data.kind === 'batch_progress_updated' || data.kind === 'stream_closed') {
                        finalizeBatchIfTerminal(batchId, data.payload);
                    }
                    return;
                }
            }

            // 兼容：旧 data.type === log/status
            if (data.type === 'log') {
                const logType = getLogType(data.message);
                addLog(logType, data.message);
            } else if (data.type === 'status') {
                if (data.total !== undefined) {
                    updateBatchProgress({
                        total: data.total,
                        completed: data.completed || 0,
                        success: data.success || 0,
                        failed: data.failed || 0,
                        finished: data.finished || ['completed', 'failed', 'cancelled', 'cancelling'].includes(data.status),
                        is_unlimited: !!data.is_unlimited,
                        consecutive_failures: data.consecutive_failures || 0,
                        max_consecutive_failures: data.max_consecutive_failures || 0,
                        domain_stats: data.domain_stats || []
                    });
                }

                if (['completed', 'failed', 'cancelled', 'cancelling'].includes(data.status)) {
                    finalizeBatchIfTerminal(batchId, data);
                }
            }
        };

        batchWebSocket.onclose = (event) => {
            console.log('批量任务 WebSocket 连接关闭:', event.code);
            stopBatchWebSocketHandshakeTimeout();
            stopBatchWebSocketHeartbeat();

            // 只有在任务未完成且最终状态不是完成状态时才切换到轮询
            // 使用 batchFinalStatus 而不是 currentBatch.status，因为 currentBatch 可能已被重置
            const shouldPoll = !batchCompleted &&
                               batchFinalStatus === null;  // 如果 batchFinalStatus 有值，说明任务已完成

            if (shouldPoll && currentBatch) {
                console.log('切换到轮询模式');
                emitConnectionStateChanged('polling');
                startBatchFallbackPolling(currentBatch.batch_id);
            } else if (!shouldPoll) {
                emitConnectionStateChanged('disconnected');
            }
        };

        batchWebSocket.onerror = (error) => {
            console.error('批量任务 WebSocket 错误:', error);
            handoverBatchTaskToPolling(batchId, currentSocket);
        };

    } catch (error) {
        console.error('批量任务 WebSocket 连接失败:', error);
        stopBatchWebSocketHandshakeTimeout();
        handoverBatchTaskToPolling(batchId, batchWebSocket);
    }
}

// 断开批量任务 WebSocket
function disconnectBatchWebSocket() {
    stopBatchWebSocketHandshakeTimeout();
    stopBatchWebSocketHeartbeat();
    if (batchWebSocket) {
        batchWebSocket.close();
        batchWebSocket = null;
    }
}

// 开始批量任务心跳
function startBatchWebSocketHeartbeat() {
    stopBatchWebSocketHeartbeat();
    batchWsHeartbeatInterval = setInterval(() => {
        if (batchWebSocket && batchWebSocket.readyState === WebSocket.OPEN) {
            batchWebSocket.send(JSON.stringify({ type: 'ping' }));
        }
    }, 25000);  // 每 25 秒发送一次心跳
}

// 停止批量任务心跳
function stopBatchWebSocketHeartbeat() {
    if (batchWsHeartbeatInterval) {
        clearInterval(batchWsHeartbeatInterval);
        batchWsHeartbeatInterval = null;
    }
}

// 发送批量任务取消请求
function cancelBatchViaWebSocket() {
    if (batchWebSocket && batchWebSocket.readyState === WebSocket.OPEN) {
        batchWebSocket.send(JSON.stringify({ type: 'cancel' }));
    }
}

// 开始轮询 Outlook 批量状态（降级方案）
function startOutlookBatchPolling(batchId) {
    emitConnectionStateChanged('polling');
    batchPollingInterval = setInterval(async () => {
        try {
            const data = await api.get(`/registration/outlook-batch/${batchId}`);

            // 更新进度
            updateBatchProgress({
                total: data.total,
                completed: data.completed,
                success: data.success,
                failed: data.failed
            });

            // 输出日志
            if (data.logs && data.logs.length > 0) {
                const lastLogIndex = batchPollingInterval.lastLogIndex || 0;
                for (let i = lastLogIndex; i < data.logs.length; i++) {
                    const log = data.logs[i];
                    const logType = getLogType(log);
                    addLog(logType, log);
                }
                batchPollingInterval.lastLogIndex = data.logs.length;
            }

            // 检查是否完成
            if (data.finished) {
                finalizeBatchIfTerminal(batchId, { ...data, status: data.status || 'completed', finished: true });
            }
        } catch (error) {
            console.error('轮询 Outlook 批量状态失败:', error);
        }
    }, 2000);

    batchPollingInterval.lastLogIndex = 0;
}

// ============== 页面可见性重连机制 ==============

function initVisibilityReconnect() {
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;

        // 页面重新可见时，检查是否需要重连（针对同页面标签切换场景）
        const wsDisconnected = !webSocket || webSocket.readyState === WebSocket.CLOSED;
        const batchWsDisconnected = !batchWebSocket || batchWebSocket.readyState === WebSocket.CLOSED;

        // 单任务重连
        if (activeTaskUuid && !taskCompleted && wsDisconnected) {
            console.log('[重连] 页面重新可见，重连单任务 WebSocket:', activeTaskUuid);
            addLog('info', '[系统] 页面重新激活，正在重连任务监控...');
            connectWebSocket(activeTaskUuid);
        }

        // 批量任务重连
        if (activeBatchId && !batchCompleted && batchWsDisconnected) {
            console.log('[重连] 页面重新可见，重连批量任务 WebSocket:', activeBatchId);
            addLog('info', '[系统] 页面重新激活，正在重连批量任务监控...');
            connectBatchWebSocket(activeBatchId);
        }
    });
}

// 页面加载时恢复进行中的任务（处理跨页面导航后回到注册页的情况）
async function restoreActiveTask() {
    const saved = sessionStorage.getItem('activeTask');
    if (!saved) return;

    let state;
    try {
        state = JSON.parse(saved);
    } catch {
        sessionStorage.removeItem('activeTask');
        return;
    }

    const { mode, task_uuid, batch_id, total, started_at } = state;

    if (mode === 'single' && task_uuid) {
        // 查询任务是否仍在运行
        try {
            const data = await api.get(`/registration/tasks/${task_uuid}`);
            if (['completed', 'failed', 'cancelled'].includes(data.status)) {
                sessionStorage.removeItem('activeTask');
                return;
            }
            // 任务仍在运行，恢复状态
            currentTask = data;
            activeTaskUuid = task_uuid;
            switchWorkbenchView('running');
            singleTaskStartedAtMs = parseRegistrationTimestampMs(data.started_at) ?? parseRegistrationTimestampMs(started_at);
            taskCompleted = false;
            taskFinalStatus = null;
            toastShown = false;
            displayedLogs.clear();
            resetRegistrationStreamViewState();
            elements.startBtn.disabled = true;
            elements.cancelBtn.disabled = false;
            showTaskStatus(data);
            updateTaskStatus(data.status);
            addLog('info', `[系统] 检测到进行中的任务，正在重连监控... (${task_uuid.substring(0, 8)})`);
            connectWebSocket(task_uuid);
        } catch {
            sessionStorage.removeItem('activeTask');
        }
    } else if ((mode === 'batch' || mode === 'unlimited' || mode === 'outlook_batch') && batch_id) {
        // 查询批量任务是否仍在运行
        const endpoint = mode === 'outlook_batch'
            ? `/registration/outlook-batch/${batch_id}`
            : `/registration/batch/${batch_id}`;
        try {
            const data = await api.get(endpoint);
            if (data.finished) {
                sessionStorage.removeItem('activeTask');
                return;
            }
            // 批量任务仍在运行，恢复状态
            currentBatch = { batch_id, ...data };
            activeBatchId = batch_id;
            switchWorkbenchView('running');
            batchTaskStartedAtMs = parseRegistrationTimestampMs(data.started_at) ?? parseRegistrationTimestampMs(started_at);
            isOutlookBatchMode = (mode === 'outlook_batch');
            isBatchMode = (mode === 'batch' || mode === 'unlimited');
            batchCompleted = false;
            batchFinalStatus = null;
            toastShown = false;
            displayedLogs.clear();
            resetRegistrationStreamViewState();
            elements.startBtn.disabled = true;
            elements.cancelBtn.disabled = false;
            showBatchStatus({ count: total || data.total });
            updateBatchProgress(data);
            addLog('info', `[系统] 检测到进行中的批量任务，正在重连监控... (${batch_id.substring(0, 8)})`);
            connectBatchWebSocket(batch_id);
        } catch {
            sessionStorage.removeItem('activeTask');
        }
    }
}
