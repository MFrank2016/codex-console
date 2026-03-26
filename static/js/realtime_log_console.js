(function () {
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function mapConnectionText(status) {
    return {
      connected: '已连接',
      connecting: '连接中',
      reconnecting: '重连中',
      disconnected: '已断开',
      error: '连接异常',
    }[String(status || '')] || String(status || '已断开');
  }

  function getLevelClass(level) {
    return `realtime-log-level-${String(level || 'info').toLowerCase()}`;
  }

  function formatEntryText(entry) {
    const displayTime = String(entry && entry.display_time ? entry.display_time : '--:--:--');
    const level = String(entry && entry.level ? entry.level : 'INFO');
    const message = String(entry && entry.message ? entry.message : '');
    return `${displayTime} ${level} ${message}`.trim();
  }

  function getVisibleEntries(state, uiState) {
    const search = String(uiState.search || '').trim().toLowerCase();
    const level = String(uiState.level || '').trim().toUpperCase();
    let entries = Array.isArray(state && state.logs) ? state.logs.slice() : [];
    if (uiState.viewCleared) {
      const clearedAfterSeq = Number.isFinite(Number(uiState.clearedAfterSeq)) ? Number(uiState.clearedAfterSeq) : 0;
      entries = entries.filter((entry) => typeof entry.seq === 'number' && entry.seq > clearedAfterSeq);
    }
    return entries.filter((entry) => {
      const message = String(entry && (entry.message || entry.raw) ? (entry.message || entry.raw) : '').toLowerCase();
      const entryLevel = String(entry && entry.level ? entry.level : '').toUpperCase();
      if (level && entryLevel !== level) {
        return false;
      }
      if (search && !message.includes(search)) {
        return false;
      }
      return true;
    });
  }

  function renderRealtimeLogConsole(target, nextState) {
    const controller = target && target.root ? target : target && target.__realtimeLogConsoleController;
    if (!controller) {
      throw new Error('mountRealtimeLogConsole must be called before renderRealtimeLogConsole');
    }
    if (nextState) {
      controller.state = window.realtimeLogStore.createState(nextState);
    }

    const state = controller.state;
    const entries = getVisibleEntries(state, controller.ui);
    const connectionText = mapConnectionText(state.connection && state.connection.status);
    const errorMessage = String(state.connection && state.connection.errorMessage ? state.connection.errorMessage : '');
    const emptyStateVisible = entries.length === 0;
    const errorStateVisible = !!errorMessage;

    controller.root.classList.add('realtime-log-console-shell');
    controller.root.classList.toggle('realtime-log-console--nowrap', controller.ui.wrap === false);
    controller.root.classList.toggle('realtime-log-console--wrap', controller.ui.wrap !== false);

    const linesHtml = entries.map((entry) => {
      const levelClass = getLevelClass(entry.level);
      return `
        <div class="realtime-log-line">
          <span class="realtime-log-time">${escapeHtml(entry.display_time || '--:--:--')}</span>
          <span class="realtime-log-level-badge ${levelClass}">${escapeHtml(entry.level || 'INFO')}</span>
          <span class="realtime-log-message">${escapeHtml(entry.message || '')}</span>
        </div>
      `;
    }).join('');

    controller.root.innerHTML = `
      <div class="realtime-log-toolbar">
        <span class="realtime-log-connection">${escapeHtml(connectionText)}</span>
      </div>
      <div class="realtime-log-states">
        <div class="realtime-log-empty${emptyStateVisible ? ' is-visible' : ''}">暂无日志</div>
        <div class="realtime-log-error${errorStateVisible ? ' is-visible' : ''}">${escapeHtml(errorMessage)}</div>
      </div>
      <div class="realtime-log-lines">${linesHtml}</div>
    `;

    controller.root.dataset.connectionText = connectionText;
    controller.root.dataset.emptyVisible = String(emptyStateVisible);
    controller.root.dataset.errorVisible = String(errorStateVisible);
    controller.root.dataset.visibleCount = String(entries.length);

    if (controller.ui.autoScroll === false) {
      controller.root.scrollTop = controller.ui.manualScrollTop;
    } else {
      controller.root.scrollTop = controller.root.scrollHeight || 0;
    }

    controller.lastRender = {
      visibleEntries: entries,
      connectionText,
      emptyStateVisible,
      errorStateVisible,
      html: controller.root.innerHTML,
    };
    return controller;
  }

  function mountRealtimeLogConsole(root, options) {
    if (!root || typeof root !== 'object') {
      throw new Error('mountRealtimeLogConsole requires a root element');
    }
    const controller = {
      root,
      state: window.realtimeLogStore.createState(options && options.state ? options.state : {}),
      ui: {
        search: '',
        level: '',
        wrap: true,
        autoScroll: true,
        viewCleared: false,
        clearedAfterSeq: 0,
        manualScrollTop: 0,
        copiedText: '',
      },
      lastRender: {
        visibleEntries: [],
        connectionText: '已断开',
        emptyStateVisible: true,
        errorStateVisible: false,
        html: '',
      },
      setState(nextState) {
        this.state = window.realtimeLogStore.createState(nextState);
        return renderRealtimeLogConsole(this);
      },
      setSearch(value) {
        this.ui.search = String(value || '');
        this.ui.viewCleared = false;
        this.ui.clearedAfterSeq = 0;
        return renderRealtimeLogConsole(this);
      },
      setLevelFilter(value) {
        this.ui.level = String(value || '').toUpperCase();
        this.ui.viewCleared = false;
        this.ui.clearedAfterSeq = 0;
        return renderRealtimeLogConsole(this);
      },
      toggleWrap(value) {
        this.ui.wrap = value === undefined ? !this.ui.wrap : !!value;
        return renderRealtimeLogConsole(this);
      },
      toggleAutoScroll(value) {
        this.ui.autoScroll = value === undefined ? !this.ui.autoScroll : !!value;
        return renderRealtimeLogConsole(this);
      },
      rememberManualScroll(position) {
        this.ui.manualScrollTop = Number.isFinite(Number(position)) ? Number(position) : 0;
        return this;
      },
      clearView() {
        this.ui.viewCleared = true;
        this.ui.clearedAfterSeq = Array.isArray(this.state.logs)
          ? this.state.logs.reduce((max, entry) => (typeof entry.seq === 'number' && entry.seq > max ? entry.seq : max), 0)
          : 0;
        return renderRealtimeLogConsole(this);
      },
      copyVisibleText() {
        const text = getVisibleEntries(this.state, this.ui).map(formatEntryText).join('\n');
        this.ui.copiedText = text;
        const clipboard = window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText;
        if (typeof clipboard === 'function') {
          return Promise.resolve(clipboard(text)).then(() => text).catch(() => text);
        }
        return Promise.resolve(text);
      },
    };
    root.__realtimeLogConsoleController = controller;
    return renderRealtimeLogConsole(controller);
  }

  if (typeof window !== 'undefined') {
    window.realtimeLogConsole = {
      mountRealtimeLogConsole,
      renderRealtimeLogConsole,
    };
  }
})();
