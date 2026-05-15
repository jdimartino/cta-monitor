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
let _lastMain  = null;
let _lastTime  = null;
let _lastHm    = null;
let _lastH2h   = null;
let _lastForcedData = null;

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
    showForcedPanel: showForcedPanel,
    calcForcedDraw: calcForcedDraw,
    sendToWhatsApp: sendToWhatsApp,
    sendForcedToWhatsApp: sendForcedToWhatsApp,
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
      _lastMain = main;
      _lastTime = timeData;
      _lastHm = hm;
      _lastH2h = h2h;
      container.innerHTML = _render(main, timeData, hm, h2h);
      _bindEvents(container, ownPlayers);

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
        <div class="dp-controls">
          <button class="dp-mode-btn" onclick="window.DrawPredictor.showForcedPanel()" title="Modo Draw Forzado: elige manualmente la alineación">
            <i class="ri-hand-coin-line"></i> Draw Forzado
          </button>
          <button class="dp-whatsapp-btn" id="dp-whatsapp-btn" title="Enviar predicción a WhatsApp">
            <i class="ri-whatsapp-line"></i> Enviar a WhatsApp
          </button>
        </div>
        <div id="dp-forced-container"></div>
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

  /* ── Explicación detallada (predicción rival) ── */
  function _renderPredExplain(slot) {
    const lines = [];
    const names = (slot.players || []).map(p => p.name).join(' y ');

    if (names && slot.candidates && slot.candidates.length > 0) {
      const top = slot.candidates[0];
      if (slot.type === 'doubles') {
        if (top.appearances === 1)
          lines.push(`Jugaron juntos en ${slot.slot} por primera vez en el último partido.`);
        else
          lines.push(`Han jugado juntos en ${slot.slot} en ${top.appearances} de los últimos partidos.`);
      } else {
        if (top.appearances === 1)
          lines.push(`Jugó en ${slot.slot} por primera vez en el último partido.`);
        else
          lines.push(`Ha jugado en ${slot.slot} en ${top.appearances} de los últimos partidos.`);
      }
    }

    if (slot.badge === 'fija') {
      lines.push('Posición consolidada: alta probabilidad de que repitan esta alineación.');
    } else if (slot.badge === 'rotativa') {
      lines.push('Posición rotativa: el equipo suele alternar jugadores aquí.');
      if (slot.candidates && slot.candidates.length > 1) {
        const alt = slot.candidates[1];
        const altNames = alt.players.map(p => p.name).join(' y ');
        lines.push(`Alternativa frecuente: ${altNames} (${alt.appearances} partido${alt.appearances !== 1 ? 's' : ''}).`);
      }
    } else {
      lines.push('Sin patrón claro: no hay suficientes datos para determinar una tendencia.');
    }

    if (slot.low_data) {
      lines.push('⚠️ Datos limitados: hay menos de 3 partidos de historial, la predicción tiene baja certeza.');
    }

    if (!lines.length) return '';
    return `<div class="dp-explain-block dp-explain-rival">${lines.map(l => `<p>${l}</p>`).join('')}</div>`;
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
          ${_renderPredExplain(slot)}
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

  /* ── Explicación detallada de sugerencia propia ── */
  function _renderSuggestExplain(slot, winPct) {
    const lines = [];
    const our = (slot.our_players || []).map(p => p.name).join(' + ');
    const vs  = (slot.vs_players || []).map(p => p.name).join(' + ');

    lines.push(`Enfrentamiento: ${our} vs ${vs}`);

    if (winPct >= 60) {
      lines.push(`↑ Ventaja táctica — ${winPct}% de probabilidad de ganar este punto.`);
    } else if (winPct >= 45) {
      lines.push(`→ Paridad táctica — ${winPct}% de probabilidad.`);
    } else {
      lines.push(`↓ El rival parte con ventaja — solo ${winPct}% de probabilidad de ganar.`);
    }

    if (slot.priority === 'primario') {
      lines.push('★ Primario: punto clave para asegurar 3 de 5. Sugerimos alinear aquí a los mejores disponibles.');
    } else {
      lines.push('○ Secundario: puedes rotar jugadores si necesitas reforzar otro slot.');
    }

    if (slot.alternatives && slot.alternatives.length > 0) {
      const alt = slot.alternatives.slice(0, 2).map(a =>
        (a.players || []).map(p => p.name).join(' + ') + ` (${Math.round((a.expected_win_prob || 0) * 100)}%)`
      ).join(' | ');
      lines.push(`Alternativas: ${alt}`);
    }

    return `<div class="dp-explain-block dp-explain-suggest">${lines.map(l => `<p>${l}</p>`).join('')}</div>`;
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
          ${slot.reasoning ? _renderSuggestExplain(slot, winPct) : ''}
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

  function _bindEvents(container, ownPlayers) {
    const btn = container.querySelector('#dp-recalc-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        const checks = container.querySelectorAll('.dp-avail-check input[type=checkbox]');
        const selected = Array.from(checks).filter(c => c.checked).map(c => parseInt(c.value, 10));
        _checkedIds = selected.length === ownPlayers.length ? null : selected;
        load(_rivalId, _ownTeamId);
      });
    }

    const waBtn = container.querySelector('#dp-whatsapp-btn');
    if (waBtn) {
      waBtn.addEventListener('click', sendToWhatsApp);
    }
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

  function _surname(name) {
    if (!name) return '?';
    // "Apellido, Nombre" → "Apellido"
    return name.includes(',') ? name.split(',')[0].trim() : name.split(' ').slice(0, 2).join(' ');
  }

  /* ═══════════════════════════════════════════
     WHATSAPP — generar texto, heatmap canvas y enviar
  ═══════════════════════════════════════════ */
  function _renderHeatmapCanvas(hm) {
    if (!hm || !hm.players || !hm.players.length) return null;
    const slots = hm.slots || ['D1','D2','D3','D4','S1'];
    const rowsN = hm.players.length;
    const colsN = slots.length;

    const cellW = 64, cellH = 30, nameW = 140, pad = 14, headerH = 34, gap = 1, titleH = 16;
    const cw = nameW + pad + colsN * (cellW + gap) + pad;
    const ch = pad + titleH + gap + headerH + gap + rowsN * (cellH + gap) + pad;

    const c = document.createElement('canvas');
    c.width = cw; c.height = ch;
    const ctx = c.getContext('2d');

    // bg
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, cw, ch);

    // title
    ctx.fillStyle = '#e2e8f0';
    ctx.font = 'bold 13px -apple-system,Helvetica,Arial,sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('HEATMAP · % por slot', cw / 2, pad + titleH / 2);

    // header row (D1, D2, D3, D4, S1)
    let y = pad + titleH + gap;
    ctx.fillStyle = '#1e293b';
    ctx.fillRect(0, y, cw, headerH);
    ctx.fillStyle = '#94a3b8';
    ctx.font = 'bold 12px -apple-system,Helvetica,Arial,sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    slots.forEach((s, ci) => {
      ctx.fillText(s, nameW + pad + ci * (cellW + gap) + cellW / 2, y + headerH / 2);
    });

    // data rows
    y += headerH + gap;
    hm.players.forEach((p, ri) => {
      // name cell
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(0, y, nameW + pad, cellH);
      ctx.fillStyle = '#e2e8f0';
      ctx.font = '12px -apple-system,Helvetica,Arial,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(_surname(p.name), pad, y + cellH / 2);

      // data cells
      (hm.cells[ri] || []).forEach((pct, ci) => {
        const v = Math.round(pct * 100);
        const x = nameW + pad + ci * (cellW + gap);
        const g = Math.round(40 + pct * 180);
        ctx.fillStyle = `rgb(10, ${g}, 30)`;
        ctx.fillRect(x, y, cellW, cellH);
        if (v > 0) {
          ctx.fillStyle = pct > 0.5 ? '#fff' : '#94a3b8';
          ctx.font = 'bold 12px -apple-system,Helvetica,Arial,sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(v + '%', x + cellW / 2, y + cellH / 2);
        }
      });

      y += cellH + gap;
    });

    return c;
  }

  function _whatsappText(main, timeData, h2h) {
    const prediction = main.prediction || [];
    const suggestion = main.suggestion || [];
    const alerts     = main.alerts     || [];
    const rival      = main.rival      || {};
    const lines = [];

    lines.push(`🔮 PREDICCIÓN vs ${rival.name || 'Rival'}`);
    if (main.low_data) lines.push('⚠️  Datos limitados — baja certeza en la predicción');
    lines.push('');

    lines.push('🏠 ALINEACIÓN RIVAL');
    for (const s of prediction) {
      const players = (s.players || []).map(p => _surname(p.name)).join(' + ') || '?';
      const conf = Math.round((s.confidence || 0) * 100);
      const badge = s.badge || 'incierta';
      lines.push(`  ${s.slot} · ${players} (${conf}%) · ${badge}`);
    }
    lines.push('');

    if (suggestion.length) {
      lines.push('🏆 NUESTRA ALINEACIÓN SUGERIDA');
      for (const s of suggestion) {
        const our = (s.our_players || []).map(p => _surname(p.name)).join(' + ') || '?';
        const vs  = (s.vs_players || []).map(p => _surname(p.name)).join(' + ') || '?';
        const win = Math.round((s.expected_win_prob || 0) * 100);
        lines.push(`  ${s.slot} · ${our} vs ${vs} → ${win}%`);
      }
      lines.push('');
    }

    if (alerts.length) {
      const sevIcons = { critical: '🚨', warning: '⚠️', info: 'ℹ️' };
      lines.push(`⚠️ ALERTAS (${alerts.length})`);
      for (const a of alerts) {
        const icon = sevIcons[a.severity] || '⚠️';
        lines.push(`  ${icon} ${a.title}: ${a.detail}`);
      }
      lines.push('');
    }

    if (h2h) {
      const s = h2h.season || {};
      const a = h2h.all_time || {};
      lines.push(`📊 H2H · Temporada ${s.won || 0}V-${s.lost || 0}D · Histórico ${a.won || 0}V-${a.lost || 0}D`);
      lines.push('');
    }

    lines.push('🔗 cta.tenistac.site');
    lines.push('🕐 ' + new Date().toLocaleString('es-VE', { timeZone: 'America/Caracas' }));

    return lines.join('\n');
  }

  async function sendToWhatsApp() {
    if (!_lastMain) {
      alert('Primero debes cargar la predicción.');
      return;
    }

    const text = _whatsappText(_lastMain, _lastTime, _lastH2h);
    const waUrl = 'https://wa.me/?text=' + encodeURIComponent(text);

    // Abrir wa.me en contexto síncrono (click del usuario) para evitar popup blocker
    const waWindow = window.open(waUrl, '_blank');

    // Generar heatmap canvas → blob (async)
    const canvas = _renderHeatmapCanvas(_lastHm);
    let blob = null;
    if (canvas) {
      blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
    }

    // Web Share API (móvil: texto + imagen juntos)
    if (navigator.share && navigator.canShare && blob) {
      const file = new File([blob], 'heatmap.png', { type: 'image/png' });
      const data = { text, files: [file] };
      if (navigator.canShare(data)) {
        try {
          await navigator.share(data);
          if (waWindow) waWindow.close();
          return; // éxito
        } catch (e) {
          if (e.name === 'AbortError') return; // usuario canceló
        }
      }
    }

    // Fallback desktop: descargar PNG (wa.me ya está abierto)
    if (blob) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'heatmap-cta.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    }
  }

  /* ═══════════════════════════════
     DRAW FORZADO — UI y cálculo
  ═══════════════════════════════ */
  function showForcedPanel() {
    const ownPlayers = _ownPlayers || [];
    const slots = ['D1', 'D2', 'D3', 'D4', 'S1'];
    const maxPerSlot = { 'D1': 2, 'D2': 2, 'D3': 2, 'D4': 2, 'S1': 1 };

    const slotRows = slots.map(slot => {
      const max = maxPerSlot[slot];
      const dropdowns = Array.from({ length: max }, (_, i) => `
        <select class="dp-forced-select" data-slot="${slot}" data-index="${i}">
          <option value="">${i === 0 ? 'Jugador 1' : 'Jugador 2'}</option>
          ${ownPlayers.map(p => `<option value="${p.cta_id}">${_esc(p.name)}</option>`).join('')}
        </select>
      `).join('');

      return `
        <div class="dp-forced-slot-row">
          <label class="dp-forced-slot-label">${slot}</label>
          <div class="dp-forced-selects">${dropdowns}</div>
        </div>
      `;
    }).join('');

    const panel = `
      <div class="dp-forced-panel" id="dp-forced-panel">
        <div class="dp-forced-header">
          <h3><i class="ri-hand-coin-line"></i> Predictor de Draw Forzado</h3>
          <button class="dp-close-forced" onclick="document.getElementById('dp-forced-panel').remove()" title="Cerrar">✕</button>
        </div>
        <div class="dp-forced-body">
          ${slotRows}
          <button id="dp-calc-forced-btn" class="dp-calc-btn"><i class="ri-calculator-line"></i> Calcular probabilidad</button>
        </div>
        <div id="dp-forced-result" class="dp-forced-result"></div>
      </div>
    `;

    const container = document.getElementById('dp-forced-container');
    container.innerHTML = panel;

    // Bind el botón de calcular
    const calcBtn = document.querySelector('#dp-calc-forced-btn');
    if (calcBtn) {
      calcBtn.addEventListener('click', () => calcForcedDraw(_rivalId, _ownTeamId));
    }
  }

  function calcForcedDraw(rivalId, ownTeamId) {
    const slots = ['D1', 'D2', 'D3', 'D4', 'S1'];
    const forced = {};

    for (const slot of slots) {
      const selects = document.querySelectorAll(`.dp-forced-select[data-slot="${slot}"]`);
      const ids = Array.from(selects)
        .map(s => parseInt(s.value, 10))
        .filter(id => !isNaN(id));
      if (ids.length > 0) {
        forced[slot] = ids;
      }
    }

    if (Object.keys(forced).length === 0) {
      alert('Selecciona al menos un jugador en algún slot');
      return;
    }

    const resultDiv = document.getElementById('dp-forced-result');
    resultDiv.innerHTML = '<p style="text-align:center; color:#999;"><i class="ri-loader-4-line" style="animation: spin 1s linear infinite;"></i> Calculando...</p>';

    const body = { forced, own_team: ownTeamId };
    const token = localStorage.getItem('cta_auth_token');
    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    };

    fetch(`${API_BASE}/api/draw-predictor/${rivalId}/forced`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.detail) {
          resultDiv.innerHTML = `<p class="dp-error">Error: ${data.detail}</p>`;
          return;
        }
        _lastForcedData = data;
        resultDiv.innerHTML = _renderForcedResult(data);
      })
      .catch(e => {
        resultDiv.innerHTML = `<p class="dp-error">Error: ${e.message}</p>`;
        console.error('[ForcedDraw]', e);
      });
  }

  function _forcedSummaryLine(slot, winPct) {
    const us  = (slot.own_players  || []).map(p => p.name).join(' + ');
    const vs  = (slot.rival_players || []).map(p => p.name).join(' + ');
    const lines = [];

    lines.push(`Enfrentamiento: ${us} vs ${vs}`);

    if (winPct >= 60) {
      lines.push(`↑ Ventaja clara — ${winPct}% de probabilidad de ganar este punto.`);
    } else if (winPct >= 52) {
      lines.push(`→ Leve ventaja — ${winPct}% de probabilidad. Margen estrecho.`);
    } else if (winPct >= 48) {
      lines.push(`↔ Paridad extrema — ${winPct}%. El resultado es impredecible.`);
    } else if (winPct >= 40) {
      lines.push(`↓ Leve desventaja — ${winPct}% de probabilidad.`);
    } else {
      lines.push(`↓ Desventaja clara — solo ${winPct}% de probabilidad de ganar.`);
    }

    // Extract ranking info from reasoning
    const rankReason = (slot.reasoning || []).find(r => r.includes('Ranking'));
    if (rankReason) lines.push(rankReason);

    // Extract H2H info from reasoning
    const h2hReason = (slot.reasoning || []).find(r => r.includes('H2H'));
    if (h2hReason) lines.push(h2hReason);
    else lines.push('Sin historial H2H previo entre estos jugadores.');

    // Rival's consistency
    const badge = slot.rival_badge || 'incierta';
    const badgeLabels = {
      fija:     'El rival suele repetir esta alineación — es su formación más confiable.',
      rotativa: 'El rival rota esta posición frecuentemente — pueden presentar otra pareja.',
      incierta: 'El rival no tiene un patrón definido en esta posición.',
    };
    lines.push(badgeLabels[badge] || badgeLabels.incierta);

    if (slot.low_data) {
      lines.push('⚠️ Datos limitados: las predicciones del rival tienen baja certeza.');
    }

    return lines.map(l => `<p>${_esc(l)}</p>`).join('');
  }

  function _renderForcedResult(data) {
    const slots = data.slots || [];
    const expectedWins = data.expected_wins || 0;
    const drawProb = data.draw_win_prob || 0;

    const slotRows = slots.map(slot => {
      const our = (slot.own_players || [])
        .map(p => `<span class="dp-player-chip own">${_esc(p.name)}</span>`)
        .join('<span class="dp-amp"> &amp; </span>');

      const vs = (slot.rival_players || [])
        .map(p => `<span class="dp-player-chip rival">${_esc(p.name)}</span>`)
        .join('<span class="dp-amp"> &amp; </span>');

      const winPct = Math.round((slot.win_prob || 0) * 100);
      const winClass = slot.win_prob >= 0.5 ? 'is-win' : 'is-loss';

      const reasoning = (slot.reasoning || [])
        .map(r => {
          let cls = 'dp-reason-tag';
          if (r.includes('ventaja')) cls += ' is-positive';
          else if (r.includes('desventaja')) cls += ' is-negative';
          else if (r.includes('similar')) cls += ' is-neutral';
          else if (r.includes('H2H')) cls += ' is-h2h';
          return `<span class="${cls}">${_esc(r)}</span>`;
        })
        .join('');

      return `
        <div class="dp-forced-matchup ${winClass}">
          <div class="dp-forced-slot-name">${slot.slot}</div>
          <div class="dp-forced-comparison">
            <div class="dp-forced-side">${our}</div>
            <div class="dp-vs-large">VS</div>
            <div class="dp-forced-side rival">${vs}</div>
          </div>
          <div class="dp-forced-winprob">
            <div class="dp-conf-bar"><div class="dp-conf-fill" style="width:${winPct}%"></div></div>
            <span class="dp-conf-label">${winPct}% probabilidad de victoria</span>
          </div>
          <div class="dp-explain-block dp-explain-forced">
            ${_forcedSummaryLine(slot, winPct)}
          </div>
          <div class="dp-forced-reasoning">${reasoning}</div>
        </div>
      `;
    }).join('');

    const drawProbPct = Math.round(drawProb * 100);
    const drawClass = expectedWins >= 3 ? 'is-favorable' : expectedWins >= 2 ? 'is-neutral' : 'is-unfavorable';

    const rivalName = _lastMain && _lastMain.rival ? _lastMain.rival.name : 'Rival';

    return `
      <div class="dp-forced-results-panel">
        <div class="dp-forced-summary ${drawClass}">
          <div class="dp-draw-wins">
            Ganarías <strong>${expectedWins}/5</strong> posiciones
          </div>
          <div class="dp-draw-prob">
            Probabilidad del draw: <strong>${drawProbPct}%</strong>
          </div>
        </div>
        <div class="dp-forced-matchups">${slotRows}</div>
        <div class="dp-forced-actions">
          <button class="dp-whatsapp-btn dp-whatsapp-btn--sm" onclick="window.DrawPredictor.sendForcedToWhatsApp()">
            <i class="ri-whatsapp-line"></i> Enviar a WhatsApp
          </button>
        </div>
      </div>
    `;
  }

  function _whatsappForcedText(data) {
    const slots = data.slots || [];
    const expectedWins = data.expected_wins || 0;
    const drawProb = data.draw_win_prob || 0;
    const rivalName = (_lastMain && _lastMain.rival ? _lastMain.rival.name : 'Rival');
    const lines = [];

    lines.push('🎲 DRAW FORZADO vs ' + rivalName);
    lines.push('');

    for (const s of slots) {
      const our = (s.own_players || []).map(p => _surname(p.name)).join(' + ');
      const vs  = (s.rival_players || []).map(p => _surname(p.name)).join(' + ');
      const win = Math.round((s.win_prob || 0) * 100);
      lines.push(`  ${s.slot} · ${our} vs ${vs} → ${win}%`);
    }

    lines.push('');
    lines.push(`📊 Resumen: ganarías ${expectedWins}/5 posiciones · ${Math.round(drawProb * 100)}% prob. del draw`);
    lines.push('');
    lines.push('🔗 cta.tenistac.site');
    lines.push('🕐 ' + new Date().toLocaleString('es-VE', { timeZone: 'America/Caracas' }));

    return lines.join('\n');
  }

  function sendForcedToWhatsApp() {
    if (!_lastForcedData) {
      alert('Primero calcula un Draw Forzado.');
      return;
    }
    const text = _whatsappForcedText(_lastForcedData);
    window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank');
  }

})();
