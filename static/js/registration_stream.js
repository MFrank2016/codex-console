/**
 * registration realtime store
 *
 * 约定：
 * - 服务端事件：必须包含 stream + seq（number），并按 stream 维度递增去重。
 * - 本地事件（如连接态切换）：通过 meta.local = true 标记，绕过 seq/cursor，
 *   且不会更新服务端 cursor（避免污染后端事件游标域）。
 *
 * 目前仅提供纯函数 reduce，供 app.js / harness 驱动渲染。
 */
(function () {
  function reduce(state, event) {
    const currentState = state || {};

    if (!event || typeof event.kind !== 'string') {
      return currentState;
    }

    const logs = Array.isArray(currentState.logs) ? currentState.logs : [];
    const batch = currentState.batch && typeof currentState.batch === 'object' ? currentState.batch : {};
    const task = currentState.task && typeof currentState.task === 'object' ? currentState.task : {};
    const connection =
      currentState.connection && typeof currentState.connection === 'object'
        ? currentState.connection
        : { status: 'disconnected' };
    const cursors =
      currentState.cursors && typeof currentState.cursors === 'object' ? currentState.cursors : {};

    const isLocal = !!(event.meta && event.meta.local === true);

    if (event.kind === 'connection_state_changed' && isLocal) {
      return {
        ...currentState,
        connection: { status: event.payload ? event.payload.status : connection.status },
      };
    }

    const stream = typeof event.stream === 'string' && event.stream ? event.stream : 'default';
    const lastSeq = typeof cursors[stream] === 'number' ? cursors[stream] : 0;
    if (typeof event.seq !== 'number' || event.seq <= lastSeq) {
      return currentState;
    }

    switch (event.kind) {
      case 'snapshot':
        return _applyServerCursor(
          {
            ...currentState,
            ...(event.payload && event.payload.task ? { task: { ...task, ...event.payload.task } } : null),
            ...(event.payload && event.payload.batch ? { batch: { ...batch, ...event.payload.batch } } : null),
            ...(event.payload ? { currentStep: event.payload.current_step || currentState.currentStep } : null),
            ...(event.payload ? { steps: event.payload.steps || currentState.steps } : null),
            ...(event.payload && Array.isArray(event.payload.logs_tail)
              ? { logs: [...logs, ...event.payload.logs_tail.map(message => ({ message, meta: { tail: true } }))] }
              : null),
          },
          stream,
          event.seq,
          cursors,
        );
      case 'log_appended':
        return _applyServerCursor(
          {
            ...currentState,
            logs: [...logs, { ...event.payload, seq: event.seq, stream }],
          },
          stream,
          event.seq,
          cursors,
        );
      case 'task_status_changed':
        return _applyServerCursor(
          {
            ...currentState,
            task: { ...task, ...(event.payload || {}) },
          },
          stream,
          event.seq,
          cursors,
        );
      case 'task_step_updated':
        return _applyServerCursor(
          {
            ...currentState,
            currentStep: event.payload ? event.payload.current_step : currentState.currentStep,
            steps: event.payload ? event.payload.steps : currentState.steps,
          },
          stream,
          event.seq,
          cursors,
        );
      case 'batch_progress_updated':
        return _applyServerCursor(
          {
            ...currentState,
            batch: { ...batch, ...(event.payload || {}) },
          },
          stream,
          event.seq,
          cursors,
        );
      case 'stream_closed':
        return _applyServerCursor(
          {
            ...currentState,
            batch: { ...batch, stream_closed: true, ...(event.payload || {}) },
          },
          stream,
          event.seq,
          cursors,
        );
      default:
        return _applyServerCursor(
          { ...currentState },
          stream,
          event.seq,
          cursors,
        );
    }
  }

  function _applyServerCursor(nextState, stream, seq, cursors) {
    const nextCursors = { ...cursors, [stream]: seq };
    return { ...nextState, cursors: nextCursors };
  }

  if (typeof window !== 'undefined') {
    window.registrationStream = { reduce };
  }
})();
