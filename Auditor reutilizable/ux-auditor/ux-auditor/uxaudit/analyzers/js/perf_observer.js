// UX-Auditor · observador de rendimiento.
// Se inyecta al crear cada documento en un MUNDO AISLADO (isolated world) de Chromium:
// la página auditada no puede ver ni manipular estas variables ni los
// PerformanceObserver originales que usamos aquí.
(() => {
  if (globalThis.__uxperf) return;
  const state = { lcp: null, cls: 0, sessions: [], longTasks: [], fcp: null, errors: [] };
  globalThis.__uxperf = state;
  const observe = (type, cb) => {
    try {
      new PerformanceObserver((list) => { for (const e of list.getEntries()) cb(e); })
        .observe({ type, buffered: true });
    } catch (err) { state.errors.push(type); }
  };
  observe('largest-contentful-paint', (e) => { state.lcp = e.startTime; });
  observe('paint', (e) => { if (e.name === 'first-contentful-paint') state.fcp = e.startTime; });
  observe('longtask', (e) => { if (state.longTasks.length < 2000) state.longTasks.push([e.startTime, e.duration]); });
  // CLS con «ventanas de sesión» (máx. 5 s, separación 1 s), como define web.dev.
  let current = null;
  observe('layout-shift', (e) => {
    if (e.hadRecentInput) return;
    if (current && e.startTime - current.last < 1000 && e.startTime - current.first < 5000) {
      current.value += e.value; current.last = e.startTime;
    } else {
      current = { first: e.startTime, last: e.startTime, value: e.value };
      state.sessions.push(current);
    }
    state.cls = Math.max(state.cls, current.value);
  });
  state.read = () => {
    const fcp = state.fcp || 0;
    let tbt = 0;
    for (const [start, dur] of state.longTasks) {
      if (start + dur > fcp) tbt += Math.max(0, dur - 50);
    }
    const nav = performance.getEntriesByType('navigation')[0];
    return {
      lcp_ms: state.lcp, fcp_ms: state.fcp, cls: state.cls, tbt_ms: tbt,
      long_tasks: state.longTasks.length,
      dom_content_loaded_ms: nav ? nav.domContentLoadedEventEnd : null,
      load_ms: nav ? nav.loadEventEnd : null,
      unsupported: state.errors.slice(0, 5),
    };
  };
})();
