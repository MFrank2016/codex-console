/**
 * registration realtime 兼容 shim
 *
 * 说明：
 * - 统一委托给 shared realtimeLogStore
 * - 保留旧入口：window.registrationStream.reduce(state, event)
 */
(function () {
  function reduce(state, event) {
    const sharedStore = window?.realtimeLogStore;
    if (!sharedStore || typeof sharedStore.createState !== 'function' || typeof sharedStore.reduceEvent !== 'function') {
      throw new Error('realtimeLogStore must be loaded before registrationStream shim');
    }
    return sharedStore.reduceEvent(sharedStore.createState(state || {}), event);
  }

  if (typeof window !== 'undefined') {
    window.registrationStream = { reduce };
  }
})();
