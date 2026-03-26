(function () {
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

  function createStreamClient(options) {
    const store = window.realtimeLogStore;
    if (!store || typeof store.createState !== 'function' || typeof store.reduceEvent !== 'function') {
      throw new Error('realtimeLogStore is required before createStreamClient');
    }

    let state = store.createState(options && options.initialState ? options.initialState : {});
    let pendingQueue = [];
    let resyncPending = false;
    let replayedInOrder = true;
    const onStateChange = options && typeof options.onStateChange === 'function' ? options.onStateChange : function () {};

    function emit(nextState) {
      state = store.createState(nextState);
      onStateChange(state);
      return state;
    }

    function updateConnection(status, extra) {
      return emit({
        ...state,
        connection: {
          ...state.connection,
          status,
          ...(extra || {}),
        },
      });
    }

    function dispatchEvent(event) {
      if (!event || typeof event.kind !== 'string') {
        return state;
      }
      if (event.kind === 'snapshot_required') {
        resyncPending = true;
        pendingQueue = [];
        replayedInOrder = true;
        return emit(store.reduceEvent(state, event));
      }
      if (resyncPending && event.kind !== 'snapshot') {
        pendingQueue.push(clone(event));
        pendingQueue.sort((left, right) => (left.seq || 0) - (right.seq || 0));
        return state;
      }
      return emit(store.reduceEvent(state, event));
    }

    function applySnapshot(snapshot) {
      let nextState = store.reduceEvent(state, snapshot);
      const snapshotSeq = snapshot && typeof snapshot.seq === 'number' ? snapshot.seq : 0;
      const replayQueue = pendingQueue
        .filter((event) => typeof event.seq !== 'number' || event.seq > snapshotSeq)
        .sort((left, right) => (left.seq || 0) - (right.seq || 0));
      replayedInOrder = replayQueue.every((event, index) => index === 0 || (replayQueue[index - 1].seq || 0) <= (event.seq || 0));
      pendingQueue = [];
      resyncPending = false;
      replayQueue.forEach((event) => {
        nextState = store.reduceEvent(nextState, event);
      });
      nextState = {
        ...nextState,
        connection: {
          ...nextState.connection,
          status: 'connected',
          reason: '',
        },
      };
      return emit(nextState);
    }

    function applyHistoryChunk(chunkText) {
      return emit(store.reduceHistoryChunk(state, chunkText));
    }

    function setConnectionStatus(status, extra) {
      return updateConnection(status, extra || {});
    }

    function getDiagnostics() {
      return {
        resyncPending,
        pendingQueueLength: pendingQueue.length,
        replayedInOrder,
      };
    }

    return {
      dispatchEvent,
      applySnapshot,
      applyHistoryChunk,
      setConnectionStatus,
      getDiagnostics,
      isResyncPending: function () {
        return resyncPending;
      },
      getState: function () {
        return state;
      },
    };
  }

  if (typeof window !== 'undefined') {
    window.realtimeLogClient = {
      createStreamClient,
    };
  }
})();
