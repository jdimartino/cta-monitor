// ═══════════════════════════════════════════════════════
//  Draw Predictor v2 — draw_predictor.js
//  IIFE que expone window.DrawPredictor
//  Depende de: API_BASE, ownTeamId, openPlayerModal (app.js)
// ═══════════════════════════════════════════════════════

  (function () {
  'use strict';

  let _rivalId    = null;
  let _ownTeamId  = null;  // equipo propio seleccionado en paso 2
  let _ownPlayers = [];    // [{cta_id, name}, ...]
  let _checkedIds = null;  // null = todos disponibles

  function _authHeaders() {
    const token = localStorage.getItem('cta_auth_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }

  function _fetch(url) {
    return fetch(url, { headers: _authHeaders() });
  }

  /* ── Public API ── */
  window.DrawPredictor = {
    load,
    refresh: () => load(_rivalId, _ownTeamId),
  };

  /* ═══════════════════════════════
     load — punto de entrada principal
  ═══════════════════════════════ */
  async function load(rivalId, ownTeamId = null) {
    if (!rivalId) return;
    _rivalId   = rivalId;
    _ownTeamId = ownTeamId;

    const container = document.getElementById('fullPredictorContent');
    _setLoading(container);

    try {
      const ownPlayersPromise = _fetchOwnPlayers(ownTeamId);

      const ownParam   = ownTeamId ? `own_team=${ownTeamId}` : '';
      const availParam = _checkedIds ? `available=${_checkedIds.join(',')}` : '';
      const mainQS     = [ownParam, availParam].filter(Boolean).join('&');
      const h2hQS      = ownParam;

      const results = await Promise.allSettled([
        _fetch(`${API_BASE}/api/draw-predictor/${rivalId}${mainQS ? '?' + mainQS : ''}`).then(r => r.json()),
        _fetch(`${API_BASE}/api/draw-predictor/${rivalId}/timeline?last_n=5`).then(r => r.json()),
        _fetch(`${API_BASE}/api/draw-predictor/${rivalId}/heatmap`).then(r => r.json()),
        _fetch(`${API_BASE}/api/draw-predictor/${rivalId}/h2h${h2hQS ? '?' + h2hQS : ''}`).then(r => r.json()),
        ownPlayersPromise,
      ]);

      const main      = results[0].status === 'fulfilled' ? results[0].value : {};
      const timeData  = results[1].status === 'fulfilled' ? results[1].value : { timeline: [] };
      const hm        = results[2].status === 'fulfilled' ? results[2].value : { players: [], slots: [], cells: [] };
      const h2h       = results[3].status === 'fulfilled' ? results[3].value : null;
      const ownPlayers = results[4].status === 'fulfilled' ? results[4].value : [];

      if (main.detail) {
        container.innerHTML = `<p class="dp-error">Error: ${main.detail}</p>`;
        return;
      }

      _ownPlayers = ownPlayers;
      container.innerHTML = _render(main, timeData, hm, h2h);
      _bindEvents(container);

    } catch (e) {
      container.innerHTML = `<p class="dp-error">Error al calcular: ${e.message}</p>`;
      console.error('[DrawPredictor]', e);
    }
  }

  /* ═══════════════════════════════
     Render raíz
  ═══════════════════════════════ */
  function _render(main, timeData, hm, h2h) {
    const prediction = main.prediction || [];
    const suggestion = main.suggestion || [];
    const alerts     = main.alerts     || [];
    const rival      = main.rival      || {};
    const timeline   = timeData.timeline || [];

    return `
      <div class="dp-root">
        ${_renderSummary(rival, main.low_data, alerts.length)}
        ${_renderAvailability()}
        <div class="dp-grid">
          ${_renderPrediction(prediction)}
          ${_renderSuggestion(suggestion)}
          ${_renderAlerts(alerts)}
          ${_renderH2H(h2h)}
          ${_renderTimeline(timeline, rival.name)}
          ${_renderHeatmap(hm)}
        </div>
      </div>
    `;
  }

  /* ── Summary bar ── */
  function _renderSummary(rival, lowData, alertCount) {
    let chips = `<span class="dp-chip dp-chip--rival"><i class="ri-team-line"></i> ${_esc(rival.name || 'Rival')}</span>`;
    if (lowData) chips += `<span class="dp-chip dp-chip--warn"><i class="ri-information-line"></i> Datos limitados</span>`;
    if (alertCount > 0) chips += `<span class="dp-chip dp-chip--alert"><i class="ri-alarm-warning-line"></i> ${alertCount} alerta${alertCount > 1 ? 's' : ''}</span>`;
    return `<div class="dp-summary-bar">${chips}</div>`;
  }

  /* ── Availability panel ── */
  function _renderAvailability() {
    if (!_ownPlayers.length) return '';

    const items = _ownPlayers.map(p => {
      const checked = !_checkedIds || _checkedIds.includes(p.cta_id) ? 'checked' : '';
      return `<label class="dp-avail-check"><input type="checkbox" value="${p.cta_id}" ${checked}> ${_esc(p.name)}</label>`;
    }).join('');

    return `
      <div class="dp-availability-panel">
        <div class="dp-avail-header">
          <span class="dp-avail-title"><i class="ri-checkbox-circle-line"></i> Disponibilidad</span>
          <button class="dp-avail-btn" id="dp-recalc-btn"><i class="ri-refresh-line"></i> Recalcular</button>
        </div>
        <div class="dp-avail-players">${items}</div>
      </div>
    `;
  }

  /* ── Predicción rival ── */
  function _renderPrediction(prediction) {
    const cards = prediction.map(slot => {
      const players = (slot.players || []).map(p =>
        `<span class="dp-player-chip" onclick="openPlayerModal(${p.cta_id})">${_esc(p.name)}</span>`
      ).join('<span class="dp-amp"> &amp; </span>');
      const conf  = Math.round((slot.confidence || 0) * 100);
      const badge = slot.badge || 'incierta';
      const low   = slot.low_data ? '<span class="dp-low-data">pocos datos</span>' : '';

      return `
        <div class="dp-slot-card">
          <div class="dp-slot-header">
            <span class="dp-slot-label">${slot.slot}</span>
            <span class="dp-slot-badge is-${badge}">${badge}</span>
          </div>
          <div class="dp-slot-players">${players || '<span class="dp-low-data">?</span>'}</div>
          <div class="dp-slot-footer">
            <div class="dp-conf-bar"><div class="dp-conf-fill" style="width:${conf}%"></div></div>
            <span class="dp-conf-label">${conf}%</span>
            ${low}
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="glass-panel dp-prediction-panel">
        <div class="panel-header"><h3><i class="ri-crosshair-2-line"></i> Predicción Rival</h3></div>
        <div class="dp-slots">${cards || '<p class="dp-no-data" style="padding:1rem">Sin datos de alineaciones anteriores.</p>'}</div>
      </div>
    `;
  }

  /* ── Sugerencia propia ── */
  function _renderSuggestion(suggestion) {
    if (!suggestion.length) {
      return `
        <div class="glass-panel dp-suggestion-panel">
          <div class="panel-header"><h3><i class="ri-team-fill"></i> Nuestra Alineación Sugerida</h3></div>
          <p class="dp-no-data" style="padding:1rem">Sin jugadores disponibles configurados.</p>
        </div>
      `;
    }

    const items = suggestion.map(slot => {
      const our = (slot.our_players || []).map(p =>
        `<span class="dp-player-chip own">${_esc(p.name)}</span>`
      ).join('<span class="dp-amp"> &amp; </span>');

      const vs  = (slot.vs_players || []).map(p =>
        `<span class="dp-player-chip rival" onclick="openPlayerModal(${p.cta_id})">${_esc(p.name)}</span>`
      ).join('<span class="dp-amp"> &amp; </span>');

      const isPrimary = slot.priority === 'primario';
      const winPct    = Math.round((slot.expected_win_prob || 0) * 100);
      const priBadge  = isPrimary
        ? '<span class="dp-priority-badge is-primary">Primario</span>'
        : '<span class="dp-priority-badge is-secondary">Secundario</span>';

      return `
        <div class="dp-suggest-row ${isPrimary ? 'is-primary' : ''}">
          <div class="dp-suggest-slot">${slot.slot} ${priBadge}</div>
          <div class="dp-suggest-matchup">
            <div class="dp-suggest-side">${our || '<span class="dp-low-data">?</span>'}</div>
            <div class="dp-vs">VS</div>
            <div class="dp-suggest-side rival">${vs || '<span class="dp-low-data">?</span>'}</div>
          </div>
          <div class="dp-suggest-win">
            <div class="dp-conf-bar"><div class="dp-conf-fill" style="width:${winPct}%"></div></div>
            <span class="dp-conf-label">${winPct}% victoria</span>
          </div>
          ${slot.reasoning ? `<div class="dp-suggest-reason">${_esc(slot.reasoning)}</div>` : ''}
        </div>
      `;
    }).join('');

    return `
      <div class="glass-panel dp-suggestion-panel">
        <div class="panel-header"><h3><i class="ri-team-fill"></i> Nuestra Alineación Sugerida</h3></div>
        <div class="dp-suggestion-list">${items}</div>
      </div>
    `;
  }

  /* ── Alertas tácticas ── */
  const ALERT_ICONS = {
    first_time_pair: '🎯',
    promoted_slot:   '📈',
    versatile:       '🔄',
    inactive:        '🔴',
    unusual_s1:      '⚠️',
  };

  function _renderAlerts(alerts) {
    if (!alerts.length) {
      return `
        <div class="glass-panel dp-alerts-panel">
          <div class="panel-header"><h3><i class="ri-alarm-warning-line"></i> Alertas Tácticas</h3></div>
          <p class="dp-no-alerts" style="padding:0.5rem 1rem">Sin alertas destacadas.</p>
        </div>
      `;
    }

    const items = alerts.map(a => `
      <li class="dp-alert dp-alert--${a.severity || 'info'}">
        <span class="dp-alert-icon">${ALERT_ICONS[a.kind] || '⚠️'}</span>
        <div class="dp-alert-body">
          <strong>${_esc(a.title)}</strong>
          <span>${_esc(a.detail)}</span>
        </div>
      </li>
    `).join('');

    return `
      <div class="glass-panel dp-alerts-panel">
        <div class="panel-header"><h3><i class="ri-alarm-warning-line"></i> Alertas Tácticas</h3></div>
        <ul class="dp-alerts-list">${items}</ul>
      </div>
    `;
  }

  /* ── H2H ── */
  function _renderH2H(h2h) {
    if (!h2h) return '';
    const season   = h2h.season    || {};
    const allTime  = h2h.all_time  || {};
    const meetings = h2h.last_meetings || [];

    const mtgRows = meetings.slice(0, 3).map(m => `
      <div class="dp-h2h-row">
        <span class="dp-h2h-date">${m.date || '?'}</span>
        <span class="dp-h2h-jornada">${m.jornada || ''}</span>
        <span class="dp-h2h-score">${m.score || '?'}</span>
        <span class="dp-h2h-winner ${m.result === 'W' ? 'win' : m.result === 'D' ? '' : 'loss'}">${m.result === 'W' ? 'Victoria' : m.result === 'D' ? 'Empate' : 'Derrota'}</span>
      </div>
    `).join('');

    return `
      <div class="glass-panel dp-h2h-panel">
        <div class="panel-header"><h3><i class="ri-history-line"></i> Historial H2H</h3></div>
        <div class="dp-h2h-stats">
          <div class="dp-h2h-stat">
            <span class="dp-h2h-num win">${season.won || 0}</span>
            <span class="dp-h2h-lbl">V Temporada</span>
          </div>
          <div class="dp-h2h-stat">
            <span class="dp-h2h-num loss">${season.lost || 0}</span>
            <span class="dp-h2h-lbl">D Temporada</span>
          </div>
          <div class="dp-h2h-stat">
            <span class="dp-h2h-num">${allTime.won || 0}V / ${allTime.lost || 0}D</span>
            <span class="dp-h2h-lbl">Histórico</span>
          </div>
        </div>
        <div class="dp-h2h-meetings">
          ${mtgRows || '<p class="dp-no-data">Sin partidos previos registrados.</p>'}
        </div>
      </div>
    `;
  }

  /* ── Timeline ── */
  function _renderTimeline(timeline, rivalName) {
    if (!timeline.length) {
      return `
        <div class="glass-panel dp-timeline-panel">
          <div class="panel-header"><h3><i class="ri-timeline-view"></i> Últimos Partidos</h3></div>
          <p class="dp-no-data" style="padding:0.5rem 1rem">Sin historial disponible.</p>
        </div>
      `;
    }

    const rows = timeline.map(match => {
      const slots = ['D1','D2','D3','D4','S1'].map(s => {
        const players = (match.lineup && match.lineup[s]) || [];
        const names   = players.map(p => {
          const parts = (p.name || '').split(' ');
          return parts[parts.length - 1];
        }).join(' / ');
        return `
          <div class="dp-tl-slot">
            <span class="dp-tl-slot-label">${s}</span>
            <span class="dp-tl-slot-players" title="${players.map(p => p.name).join(' / ')}">${names || '-'}</span>
          </div>
        `;
      }).join('');

      return `
        <div class="dp-tl-match">
          <div class="dp-tl-header">
            <span class="dp-tl-date">${match.match_date || '?'}</span>
            <span class="dp-tl-jornada">${match.jornada || ''}</span>
            <span class="dp-tl-opp">vs ${_esc(match.opponent || '?')}</span>
          </div>
          <div class="dp-tl-slots">${slots}</div>
        </div>
      `;
    }).join('');

    return `
      <div class="glass-panel dp-timeline-panel">
        <div class="panel-header"><h3><i class="ri-timeline-view"></i> Últimos Partidos de ${_esc(rivalName || 'Rival')}</h3></div>
        <div class="dp-timeline-list">${rows}</div>
      </div>
    `;
  }

  /* ── Heatmap ── */
  function _renderHeatmap(hm) {
    if (!hm || !hm.players || !hm.players.length) {
      return `
        <div class="glass-panel dp-heatmap-panel">
          <div class="panel-header"><h3><i class="ri-grid-fill"></i> Heatmap Jugador × Slot</h3></div>
          <p class="dp-no-data" style="padding:0.5rem 1rem">Sin datos suficientes.</p>
        </div>
      `;
    }

    const slots      = hm.slots || ['D1','D2','D3','D4','S1'];
    const headerCells = slots.map(s => `<th>${s}</th>`).join('');

    const bodyRows = (hm.players || []).map((p, pi) => {
      const cells = (hm.cells[pi] || []).map(pct => {
        const bucket     = Math.min(10, Math.round(pct * 10));
        const pctDisplay = Math.round(pct * 100);
        return `<td class="dp-hm-cell b${bucket}" title="${pctDisplay}%">${pctDisplay > 0 ? pctDisplay + '%' : ''}</td>`;
      }).join('');

      const shortName = _shortName(p.name);
      return `<tr><td class="dp-hm-player" onclick="openPlayerModal(${p.cta_id})" title="${_esc(p.name)}">${_esc(shortName)}</td>${cells}</tr>`;
    }).join('');

    return `
      <div class="glass-panel dp-heatmap-panel">
        <div class="panel-header"><h3><i class="ri-grid-fill"></i> Heatmap Jugador × Slot</h3></div>
        <div class="dp-heatmap-scroll">
          <table class="dp-heatmap-table">
            <thead><tr><th>Jugador</th>${headerCells}</tr></thead>
            <tbody>${bodyRows}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  /* ═══════════════════════════════
     Helpers
  ═══════════════════════════════ */

  function _setLoading(container) {
    container.innerHTML = `
      <div class="dp-loading">
        <div class="loading-spinner" style="margin:0 auto 1rem"></div>
        <p class="text-muted">Calculando alineación óptima...</p>
      </div>
    `;
  }

  async function _fetchOwnPlayers(ownTeamId = null) {
    try {
      const teamId = ownTeamId || window.ownTeamId;
      if (!teamId) return [];
      const res  = await _fetch(`${API_BASE}/api/team/${teamId}`);
      const data = await res.json();
      return (data.players || []).map(p => ({ cta_id: p.cta_id, name: p.name }));
    } catch (e) {
      return [];
    }
  }

  function _bindEvents(container) {
    const btn = container.querySelector('#dp-recalc-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const checks = container.querySelectorAll('.dp-avail-check input[type=checkbox]');
      const selected = Array.from(checks).filter(c => c.checked).map(c => parseInt(c.value, 10));
      _checkedIds = selected.length === _ownPlayers.length ? null : selected;
      load(_rivalId, _ownTeamId);
    });
  }

  function _esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _shortName(name) {
    if (!name) return '?';
    // "Apellido, Nombre" → "Nombre Apellido" → primeras 2 palabras
    const parts = name.includes(',')
      ? name.split(',').reverse().map(s => s.trim())
      : name.split(' ');
    return parts.slice(0, 2).join(' ');
  }

})();
