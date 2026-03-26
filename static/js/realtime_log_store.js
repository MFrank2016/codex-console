(function () {
  const MAX_LIVE_WINDOW = 500;
  const DEFAULT_FILTERS = {
    search: '',
    level: '',
    wrap: true,
    autoScroll: true,
  };
  const LOG_LEVELS = new Set(['INFO', 'WARN', 'ERROR']);

  function hasOwn(object, key) {
    return !!object && Object.prototype.hasOwnProperty.call(object, key);
  }

  function clone(value) {
    if (Array.isArray(value)) {
      return value.map(clone);
    }
    if (value && typeof value === 'object') {
      const result = {};
      Object.keys(value).forEach((key) => {
        result[key] = clone(value[key]);
      });
      return result;
    }
    return value;
  }

  function normalizeLevel(level) {
    const text = String(level || 'INFO').trim().toUpperCase();
    return LOG_LEVELS.has(text) ? text : 'INFO';
  }

  function inferLevel(text) {
    const message = String(text || '').toUpperCase();
    if (message.includes('[ERROR]')) return 'ERROR';
    if (message.includes('[WARN]')) return 'WARN';
    return 'INFO';
  }

  function deriveDisplayTime(timestamp, raw) {
    const stamp = String(timestamp || '');
    if (stamp.length >= 19 && stamp.includes('T')) {
      return stamp.slice(11, 19);
    }
    const source = String(raw || stamp || '');
    const match = source.match(/(\d{2}:\d{2}:\d{2})/);
    return match ? match[1] : '--:--:--';
  }

  function parseHistoryLine(line) {
    const raw = String(line || '');
    const match = raw.match(/^(\d{4}-\d{2}-\d{2})?\s*(\d{2}:\d{2}:\d{2})(?:\.\d+)?\s+\[(INFO|WARN|ERROR)\]\s?(.*)$/);
    if (!match) {
      return normalizeLogEntry({ raw, message: raw, level: inferLevel(raw), source: 'history' }, {});
    }
    const [, dayPart, timePart, level, message] = match;
    const timestamp = dayPart ? `${dayPart}T${timePart}` : null;
    return normalizeLogEntry(
      {
        timestamp,
        display_time: timePart,
        level,
        message,
        raw,
        source: 'history',
      },
      {}
    );
  }

  function normalizeLogEntry(item, fallback) {
    const payload = item && typeof item === 'object' ? clone(item) : {};
    const message = typeof payload.message === 'string'
      ? payload.message
      : typeof payload.raw === 'string'
        ? payload.raw
        : typeof item === 'string'
          ? item
          : '';
    const raw = typeof payload.raw === 'string' ? payload.raw : message;
    const timestamp = typeof payload.timestamp === 'string' ? payload.timestamp : null;
    return {
      seq: typeof payload.seq === 'number' ? payload.seq : (typeof fallback.seq === 'number' ? fallback.seq : null),
      stream: typeof payload.stream === 'string' ? payload.stream : String(fallback.stream || ''),
      timestamp,
      display_time: typeof payload.display_time === 'string' ? payload.display_time : deriveDisplayTime(timestamp, raw),
      level: normalizeLevel(payload.level || inferLevel(raw)),
      message,
      raw,
      source: typeof payload.source === 'string' ? payload.source : String(fallback.source || 'realtime'),
    };
  }

  function rebuildLegacyState(state) {
    const nextState = clone(state || {});
    nextState.filters = { ...DEFAULT_FILTERS, ...(nextState.filters || {}) };
    nextState.connection = {
      status: 'disconnected',
      errorMessage: '',
      ...(nextState.connection || {}),
    };
    nextState.cursors = { ...(nextState.cursors || {}) };
    nextState.historyPrefix = Array.isArray(nextState.historyPrefix) ? nextState.historyPrefix.map(clone) : [];
    nextState.liveWindow = Array.isArray(nextState.liveWindow) ? nextState.liveWindow.map(clone) : [];
    nextState.logs = [...nextState.historyPrefix, ...nextState.liveWindow].map(clone);
    nextState.context = {
      task: nextState.task || null,
      batch: nextState.batch || null,
      run: nextState.run || null,
      taskProgress: hasOwn(nextState, 'taskProgress') ? nextState.taskProgress : null,
      runProgress: hasOwn(nextState, 'runProgress') ? nextState.runProgress : null,
      ...(nextState.context || {}),
    };
    nextState.task = nextState.task && typeof nextState.task === 'object' ? nextState.task : {};
    nextState.batch = nextState.batch && typeof nextState.batch === 'object' ? nextState.batch : {};
    nextState.run = nextState.run && typeof nextState.run === 'object' ? nextState.run : {};
    nextState.currentStep = nextState.currentStep || null;
    nextState.steps = Array.isArray(nextState.steps) ? nextState.steps.map(clone) : [];
    nextState.taskProgress = hasOwn(nextState, 'taskProgress') ? clone(nextState.taskProgress) : null;
    nextState.runProgress = hasOwn(nextState, 'runProgress') ? clone(nextState.runProgress) : null;
    nextState.resyncRequired = nextState.resyncRequired === true;
    return nextState;
  }

  function createState(seed) {
    return rebuildLegacyState({
      filters: clone(DEFAULT_FILTERS),
      connection: { status: 'disconnected', errorMessage: '' },
      cursors: {},
      historyPrefix: [],
      liveWindow: [],
      logs: [],
      context: { task: null, batch: null, run: null, taskProgress: null, runProgress: null },
      task: {},
      batch: {},
      run: {},
      currentStep: null,
      steps: [],
      taskProgress: null,
      runProgress: null,
      resyncRequired: false,
      ...(seed || {}),
    });
  }

  function applyCursor(state, stream, seq) {
    if (!stream || typeof seq !== 'number') {
      return state;
    }
    const nextState = createState(state);
    nextState.cursors[stream] = seq;
    return rebuildLegacyState(nextState);
  }

  function replaceLiveWindow(state, logsTail, stream, seq) {
    const nextState = createState(state);
    nextState.liveWindow = (Array.isArray(logsTail) ? logsTail : []).map((item) =>
      normalizeLogEntry(item, { stream, seq, source: 'snapshot' })
    ).slice(-MAX_LIVE_WINDOW);
    return rebuildLegacyState(nextState);
  }

  function appendLiveEntry(state, entry) {
    const nextState = createState(state);
    nextState.liveWindow = [...nextState.liveWindow, normalizeLogEntry(entry, {})].slice(-MAX_LIVE_WINDOW);
    return rebuildLegacyState(nextState);
  }

  function reduceEvent(state, event) {
    const currentState = createState(state);
    if (!event || typeof event.kind !== 'string') {
      return currentState;
    }

    const stream = typeof event.stream === 'string' ? event.stream : '';
    const lastSeq = typeof currentState.cursors[stream] === 'number' ? currentState.cursors[stream] : 0;
    const isLocal = !!(event.meta && event.meta.local === true);
    if (!isLocal && typeof event.seq === 'number' && event.seq <= lastSeq) {
      return currentState;
    }

    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    let nextState = createState(currentState);

    switch (event.kind) {
      case 'connection_state_changed': {
        nextState.connection = {
          ...currentState.connection,
          ...(payload || {}),
        };
        return rebuildLegacyState(nextState);
      }
      case 'snapshot_required': {
        nextState.connection = {
          ...currentState.connection,
          status: 'reconnecting',
          reason: payload.reason || '',
        };
        nextState.resyncRequired = true;
        return rebuildLegacyState(nextState);
      }
      case 'snapshot': {
        if (payload.task && typeof payload.task === 'object') {
          nextState.task = clone(payload.task);
        }
        if (payload.batch && typeof payload.batch === 'object') {
          nextState.batch = clone(payload.batch);
        }
        if (payload.run && typeof payload.run === 'object') {
          nextState.run = clone(payload.run);
        }
        if (hasOwn(payload, 'current_step')) {
          nextState.currentStep = clone(payload.current_step);
        }
        if (Array.isArray(payload.steps)) {
          nextState.steps = payload.steps.map(clone);
        }
        if (hasOwn(payload, 'task_progress')) {
          nextState.taskProgress = clone(payload.task_progress);
        }
        if (hasOwn(payload, 'run_progress')) {
          nextState.runProgress = clone(payload.run_progress);
        }
        nextState.context = {
          task: nextState.task,
          batch: nextState.batch,
          run: nextState.run,
          taskProgress: nextState.taskProgress,
          runProgress: nextState.runProgress,
        };
        nextState.connection = {
          ...currentState.connection,
          status: currentState.connection.status === 'reconnecting' ? 'connected' : currentState.connection.status,
          reason: '',
        };
        nextState.resyncRequired = false;
        nextState = replaceLiveWindow(nextState, payload.logs_tail, stream, event.seq);
        return applyCursor(nextState, stream, event.seq);
      }
      case 'log_appended': {
        const entry = normalizeLogEntry(payload.entry || payload, { stream, seq: event.seq, source: 'realtime' });
        nextState = appendLiveEntry(nextState, entry);
        return applyCursor(nextState, stream, event.seq);
      }
      case 'task_status_changed': {
        nextState.task = { ...currentState.task, ...clone(payload) };
        nextState.context.task = nextState.task;
        return applyCursor(nextState, stream, event.seq);
      }
      case 'task_step_updated': {
        if (hasOwn(payload, 'current_step')) {
          nextState.currentStep = clone(payload.current_step);
        }
        if (Array.isArray(payload.steps)) {
          nextState.steps = payload.steps.map(clone);
        }
        if (hasOwn(payload, 'task_progress')) {
          nextState.taskProgress = clone(payload.task_progress);
          nextState.context.taskProgress = nextState.taskProgress;
        }
        return applyCursor(nextState, stream, event.seq);
      }
      case 'batch_progress_updated': {
        nextState.batch = { ...currentState.batch, ...clone(payload) };
        nextState.context.batch = nextState.batch;
        return applyCursor(nextState, stream, event.seq);
      }
      case 'run_status_changed': {
        nextState.run = { ...currentState.run, ...clone(payload) };
        if (hasOwn(payload, 'run_progress')) {
          nextState.runProgress = clone(payload.run_progress);
        }
        nextState.context.run = nextState.run;
        nextState.context.runProgress = nextState.runProgress;
        return applyCursor(nextState, stream, event.seq);
      }
      case 'stream_closed': {
        if (stream.startsWith('run:')) {
          nextState.run = {
            ...currentState.run,
            stream_closed: true,
            stream_final_status: payload.final_status || currentState.run.stream_final_status,
          };
          nextState.context.run = nextState.run;
        } else if (stream.startsWith('batch:')) {
          nextState.batch = {
            ...currentState.batch,
            stream_closed: true,
            stream_final_status: payload.final_status || currentState.batch.stream_final_status,
          };
          nextState.context.batch = nextState.batch;
        } else {
          nextState.task = {
            ...currentState.task,
            stream_closed: true,
            stream_final_status: payload.final_status || currentState.task.stream_final_status,
          };
          nextState.context.task = nextState.task;
        }
        return applyCursor(nextState, stream, event.seq);
      }
      default:
        return applyCursor(nextState, stream, event.seq);
    }
  }

  function reduceHistoryChunk(state, chunkText) {
    const currentState = createState(state);
    const lines = String(chunkText || '')
      .replace(/\r\n/g, '\n')
      .split('\n')
      .filter((line) => line.trim().length > 0);
    const nextState = createState(currentState);
    nextState.historyPrefix = [...currentState.historyPrefix, ...lines.map(parseHistoryLine)];
    return rebuildLegacyState(nextState);
  }

  if (typeof window !== 'undefined') {
    window.realtimeLogStore = {
      MAX_LIVE_WINDOW,
      createState,
      reduceEvent,
      reduceHistoryChunk,
      normalizeLogEntry,
    };
  }
})();
