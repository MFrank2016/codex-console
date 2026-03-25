/**
 * registration realtime store
 *
 * 约定：事件必须包含递增的 seq（number），否则 reducer 忽略。
 * 目前仅提供纯函数 reduce，供 app.js / harness 驱动渲染。
 */
(function () {
  function reduce(state, event) {
    const currentState = state || {};
    const lastSeq = typeof currentState.lastSeq === 'number' ? currentState.lastSeq : 0;

    if (!event || typeof event.seq !== 'number' || event.seq <= lastSeq) {
      return currentState;
    }

    const logs = Array.isArray(currentState.logs) ? currentState.logs : [];
    const batch = currentState.batch && typeof currentState.batch === 'object' ? currentState.batch : {};
    const connection =
      currentState.connection && typeof currentState.connection === 'object'
        ? currentState.connection
        : { status: 'disconnected' };

    switch (event.kind) {
      case 'snapshot':
        return {
          ...currentState,
          ...(event.payload || {}),
          connection: { status: 'connected' },
          lastSeq: event.seq,
        };
      case 'task_step_updated':
        return {
          ...currentState,
          currentStep: event.payload ? event.payload.current_step : currentState.currentStep,
          steps: event.payload ? event.payload.steps : currentState.steps,
          lastSeq: event.seq,
        };
      case 'batch_progress_updated':
        return {
          ...currentState,
          batch: { ...batch, ...(event.payload ? event.payload.batch : null) },
          lastSeq: event.seq,
        };
      case 'log_appended':
        return {
          ...currentState,
          logs: [...logs, event.payload],
          lastSeq: event.seq,
        };
      case 'connection_state_changed':
        return {
          ...currentState,
          connection: { status: event.payload ? event.payload.status : connection.status },
          lastSeq: event.seq,
        };
      default:
        return { ...currentState, lastSeq: event.seq };
    }
  }

  if (typeof window !== 'undefined') {
    window.registrationStream = { reduce };
  }
})();

