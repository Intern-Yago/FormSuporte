(function (global) {
  // Dynamic options provider backed by server-side DB (via /ocorrencia/options/)
  const STATE = {
    loaded: false,
    data: { SISTEMA: {}, PROBLEMA_BY_SYSTEM: {}, PROBLEMA_BY_AREA: {} },
    waiters: []
  };

  function sortAlpha(arr) {
    return (arr || []).slice().filter(Boolean).sort((a, b) =>
      String(a).localeCompare(String(b), 'pt-BR', { sensitivity: 'base' })
    );
  }
  function withOutroSorted(arr) {
    const sorted = sortAlpha(arr).filter(v => v !== 'Outro...');
    sorted.push('Outro...');
    return sorted;
  }

  function buildOptionsUrl() {
    try {
      const parts = (window.location.pathname || '/').split('/').filter(Boolean);
      // i18n_prefix like 'pt-br' or 'en', else none
      const lang = parts.length ? parts[0] : '';
      return lang ? `/${lang}/options/` : '/options/';
    } catch (_) {
      return '/options/';
    }
  }

  function loadIfNeeded() {
    if (STATE.loaded) return;
    const url = buildOptionsUrl();
    fetch(url, { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('Options fetch failed')))
      .then(json => {
        STATE.data = json || { SISTEMA: {}, PROBLEMA_BY_SYSTEM: {}, PROBLEMA_BY_AREA: {} };
        STATE.loaded = true;
        STATE.waiters.splice(0).forEach(fn => { try { fn(); } catch (_) { } });
      })
      .catch(() => {
        // Keep STATE.loaded false to allow retry on next onReady registration
      });
  }

  function get(cat, area) {
    if (!STATE.loaded) {
      loadIfNeeded();
      return [];
    }
    function normalizeArea(a) {
      if (!a) return '';
      const u = String(a).toUpperCase();
      if (u === 'IMMO') return 'IMMO';
      if (u === 'DIAGNOSIS') return 'Diagnosis';
      if (u === 'DEVICE') return 'Device';
      if (u === 'BOX360') return 'BOX360';
      // fallback: keep as-is for preloaded keys
      return a;
    }
    const byCat = STATE.data[cat] || {};
    const arr = byCat[normalizeArea(area)] || [];
    return arr;
  }

  const api = {
    getSistemaOptions(area) { return sortAlpha(get('SISTEMA', area)); },
    // Fallback by area (legacy)
    getProblemaOptions(area) { return withOutroSorted(get('PROBLEMA_BY_AREA', area)); },
    // New: problems by system label
    getProblemaOptionsBySistema(sistema) {
      if (!STATE.loaded) { loadIfNeeded(); return []; }
      const bySys = STATE.data['PROBLEMA_BY_SYSTEM'] || {};
      const arr = bySys[sistema] || [];
      return withOutroSorted(arr);
    },
    getAllProblemaOptions() {
      if (!STATE.loaded) { loadIfNeeded(); return []; }
      const bySys = STATE.data['PROBLEMA_BY_SYSTEM'] || {};
      const set = new Set();
      Object.values(bySys).forEach(list => (list || []).forEach(v => set.add(v)));
      // Aqui usamos sortAlpha pois é para sugestões misturadas, mas o 'Outro...' não faz sentido na lista de sugestão
      return sortAlpha(Array.from(set));
    },
    getAllSistemaOptions() {
      if (!STATE.loaded) { loadIfNeeded(); return []; }
      const byArea = STATE.data['SISTEMA'] || {};
      const set = new Set();
      Object.values(byArea).forEach(list => (list || []).forEach(v => set.add(v)));
      return sortAlpha(Array.from(set));
    },
    onReady(cb) {
      if (STATE.loaded) { try { cb(); } catch (_) { } return; }
      STATE.waiters.push(cb);
      loadIfNeeded();
    },
    async addSistema(area, label) {
      const url = (buildOptionsUrl().replace(/\/$/, '')) + '/add/';
      const payload = { category: 'SISTEMA', area, label };
      const csrftoken = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(csrftoken ? { 'X-CSRFToken': csrftoken } : {}) },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });
      STATE.loaded = false; loadIfNeeded();
    },
    async addProblema(area, label, systemLabel = null, globalProblem = false) {
      const url = (buildOptionsUrl().replace(/\/$/, '')) + '/add/';
      const payload = { category: 'PROBLEMA', area, label, system_label: systemLabel, global_problem: !!globalProblem };
      const csrftoken = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(csrftoken ? { 'X-CSRFToken': csrftoken } : {}) },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });
      STATE.loaded = false; loadIfNeeded();
    }
  };

  global.OcorrenciaOptions = api;
})(window);
