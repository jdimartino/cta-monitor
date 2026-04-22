// ═══════════════════════════════════════════════════════
//  CTA Monitor — app.js
//  Router SPA + handlers de todas las vistas
// ═══════════════════════════════════════════════════════

const API_BASE = '';

let performanceChartInstance = null;
let cachedTeams = [];      // Cache global de equipos para el buscador
let cachedPlayers = [];    // Cache global de jugadores para el buscador
let ownTeamPlayers = [];   // Cache de jugadores propios
let clubsMap = {};         // { "TAC": "Club Tachira", ... }
let ownTeamId = null;      // Se llena desde /api/dashboard

// ─────────────────────────────────────────────
// NOMBRES COMPLETOS DE EQUIPOS
// TACA → clubsMap["TAC"] + " A" = "Club Tachira A"
// ─────────────────────────────────────────────
async function loadClubs() {
    try {
        const res = await fetch(`${API_BASE}/api/clubs`);
        const data = await res.json();
        (data.clubs || []).forEach(c => { clubsMap[c.acronym] = c.name; });
    } catch(e) {}
}

function expandTeamName(sigla) {
    if (!sigla) return sigla;
    const acronym = sigla.slice(0, -1);
    const letter  = sigla.slice(-1);
    const club    = clubsMap[acronym];
    return club ? `${club} ${letter}` : sigla;
}

document.addEventListener("DOMContentLoaded", () => {
    // Conectar navegación
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            navigateTo(item.dataset.view);
        });
    });

    // Carga inicial
    loadClubs().then(() => {
        fetchDashboardData();
        fetchLastSync();
        initSearch();
    });
});

// ─────────────────────────────────────────────
// BUSCADOR
// Lógica: al cargar la página se descargan los
// 36 equipos y se guardan en caché (cachedTeams).
// Mientras escribes, se filtran en memoria (sin
// llamadas extra al servidor). Al hacer clic en
// un resultado de equipo → navega al Predictor
// con ese rival ya pre-seleccionado.
// ─────────────────────────────────────────────
async function initSearch() {
    const input = document.getElementById('searchInput');
    if (!input) return;

    // Precarga equipos y jugadores en segundo plano
    try {
        const [teamsRes, playersRes] = await Promise.all([
            fetch(`${API_BASE}/api/teams`),
            fetch(`${API_BASE}/api/players`),
        ]);
        cachedTeams   = (await teamsRes.json()).teams   || [];
        cachedPlayers = (await playersRes.json()).players || [];
    } catch (e) { /* silencioso */ }

    // Eventos del input
    input.addEventListener('input', () => renderSearchResults(input.value.trim()));
    input.addEventListener('focus', () => {
        if (input.value.trim()) renderSearchResults(input.value.trim());
    });
    input.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeSearchDropdown();
    });

    // Cerrar al click fuera
    document.addEventListener('click', e => {
        const bar = document.getElementById('searchBar');
        if (bar && !bar.contains(e.target)) closeSearchDropdown();
    });
}

function renderSearchResults(query) {
    closeSearchDropdown();
    if (!query || query.length < 1) return;

    const q = query.toLowerCase();
    const bar = document.getElementById('searchBar');
    if (!bar) return;

    const teamResults   = cachedTeams.filter(t => expandTeamName(t.name).toLowerCase().includes(q) || t.name.toLowerCase().includes(q)).slice(0, 5);
    const playerResults = cachedPlayers.filter(p => p.name.toLowerCase().includes(q)).slice(0, 5);

    let html = '';

    if (teamResults.length === 0 && playerResults.length === 0) {
        html = `<div class="search-empty">Sin resultados para "<strong>${query}</strong>"</div>`;
    }

    if (teamResults.length > 0) {
        html += '<div class="search-group-label">Equipos</div>';
        teamResults.forEach(t => {
            const isOwn = t.is_own_team;
            const fullName = expandTeamName(t.name);
            html += `
            <div class="search-result-item" onclick="searchSelectTeam(${t.cta_id}, '${t.name.replace(/'/g,"\\'")}', ${isOwn})">
                <i class="ri-${isOwn ? 'home' : 'team'}-line search-result-icon"></i>
                <div class="search-result-text">
                    <div class="search-result-name">${highlightMatch(fullName, query)}${t.categoria_name ? ` <span class="cat-badge cat-${t.categoria_name}">${t.categoria_name}</span>` : ''}</div>
                    <div class="search-result-sub">${isOwn ? 'Tu equipo' : 'Equipo rival'}</div>
                </div>
                <span class="search-result-action">${isOwn ? 'Ver →' : 'Predecir →'}</span>
            </div>`;
        });
    }

    if (playerResults.length > 0) {
        html += '<div class="search-group-label">Jugadores</div>';
        playerResults.forEach(p => {
            const teamFull = expandTeamName(p.team_name);
            html += `
            <div class="search-result-item" onclick="searchSelectPlayer(${p.cta_id})">
                <i class="ri-user-3-line search-result-icon"></i>
                <div class="search-result-text">
                    <div class="search-result-name">${highlightMatch(p.name, query)}</div>
                    <div class="search-result-sub">${teamFull}${p.categoria_name ? ' · ' + p.categoria_name : ''}</div>
                </div>
                <span class="search-result-action">Ver →</span>
            </div>`;
        });
    }

    const dropdown = document.createElement('div');
    dropdown.id = 'searchDropdown';
    dropdown.className = 'search-dropdown';
    dropdown.innerHTML = html;
    bar.appendChild(dropdown);
}

function highlightMatch(text, query) {
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return text;
    return text.slice(0, idx)
        + `<strong style="color:var(--accent-blue)">${text.slice(idx, idx + query.length)}</strong>`
        + text.slice(idx + query.length);
}

function searchSelectTeam(ctaId, _name, isOwn) {
    closeSearchDropdown();
    document.getElementById('searchInput').value = '';

    if (isOwn) {
        // Propio equipo → ir a Mi Equipo
        navigateTo('equipo');
    } else {
        // Rival → ir a Predictor con ese equipo pre-seleccionado
        navigateTo('predictor');
        // Esperar a que fetchRivalTeams() termine y luego seleccionar
        const trySelect = setInterval(() => {
            const select = document.getElementById('rivalSelect');
            if (!select) return;
            const opt = Array.from(select.options).find(o => o.value == ctaId);
            if (opt) {
                select.value = ctaId;
                clearInterval(trySelect);
            }
        }, 100);
        setTimeout(() => clearInterval(trySelect), 3000);
    }
}

function searchSelectPlayer(playerCtaId) {
    closeSearchDropdown();
    document.getElementById('searchInput').value = '';
    // Por ahora: navega a Mi Equipo si es jugador propio, o muestra info básica
    const player = cachedPlayers.find(p => p.cta_id === playerCtaId);
    if (!player) return;
    if (player.team_cta_id === (ownTeamId || 7361)) {
        navigateTo('equipo');
    } else {
        searchSelectTeam(player.team_cta_id, player.team_name, false);
    }
}

function closeSearchDropdown() {
    const existing = document.getElementById('searchDropdown');
    if (existing) existing.remove();
}

// ─────────────────────────────────────────────
// ROUTER
// ─────────────────────────────────────────────
function navigateTo(viewId) {
    // Actualizar estado activo en nav
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    const activeNav = document.querySelector(`[data-view="${viewId}"]`);
    if (activeNav) activeNav.classList.add('active');

    // Mostrar la vista correcta
    document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
    const view = document.getElementById(`view-${viewId}`);
    if (view) view.classList.add('active');

    // Cargar datos según vista
    if (viewId === 'inicio')     fetchDashboardData();
    else if (viewId === 'equipo')    fetchTeamData();
    else if (viewId === 'posiciones') { initCategoryTabs(); fetchStandings(); }
    else if (viewId === 'predictor') fetchRivalTeams();
}

// ─────────────────────────────────────────────
// LOG PANEL EN VIVO
// ─────────────────────────────────────────────
let _activeSSE = null;

function openLogPanel(title) {
    document.getElementById('logPanelTitle').textContent = title;
    document.getElementById('logOutput').innerHTML = '';
    document.getElementById('logPanelStatus').textContent = '';
    document.getElementById('logPanelStatus').className = 'log-status running';
    document.getElementById('logPanelStatus').textContent = 'En progreso...';
    document.getElementById('logPanel').classList.add('open');
}

function closeLogPanel() {
    document.getElementById('logPanel').classList.remove('open');
    if (_activeSSE) { _activeSSE.close(); _activeSSE = null; }
}

function clearLog() {
    document.getElementById('logOutput').innerHTML = '';
}

function appendLog(text, type = 'normal') {
    const out = document.getElementById('logOutput');
    const line = document.createElement('div');
    line.className = 'log-line' + (type !== 'normal' ? ' log-' + type : '');
    line.textContent = text;
    out.appendChild(line);
    out.scrollTop = out.scrollHeight;
}

function startSSE(url, btnId, btnIdleHTML, title) {
    // Disable all action buttons while running
    ['syncBtn','groupBtn','crawlBtn'].forEach(id => {
        const b = document.getElementById(id);
        if (b) b.disabled = true;
    });
    const btn = document.getElementById(btnId);
    if (btn) btn.innerHTML = '<i class="ri-loader-4-line spin"></i> En progreso...';

    openLogPanel(title);

    if (_activeSSE) _activeSSE.close();
    const es = new EventSource(`${API_BASE}${url}`);
    _activeSSE = es;

    es.onmessage = (e) => {
        const msg = e.data;
        if (msg.startsWith('__DONE__')) {
            const ok = msg === '__DONE__ok';
            const statusEl = document.getElementById('logPanelStatus');
            statusEl.textContent = ok ? '✓ Completado' : '✗ Error';
            statusEl.className = 'log-status ' + (ok ? 'done-ok' : 'done-error');
            appendLog(ok ? '— Operación completada exitosamente —' : '— Finalizó con error —', ok ? 'success' : 'error');
            es.close();
            _activeSSE = null;

            // Re-enable buttons
            ['syncBtn','groupBtn','crawlBtn'].forEach(id => {
                const b = document.getElementById(id);
                if (b) b.disabled = false;
            });
            if (btn) btn.innerHTML = btnIdleHTML;

            // Refresh current view
            const viewId = document.querySelector('.view-section.active')?.id?.replace('view-', '');
            if (viewId) navigateTo(viewId);
            fetchLastSync();
        } else {
            const type = msg.includes('ERROR') || msg.includes('Error') ? 'error'
                       : msg.includes('✓') || msg.includes('OK') || msg.includes('completad') ? 'success'
                       : msg.startsWith('[') ? 'info'
                       : 'normal';
            appendLog(msg, type);
        }
    };

    es.onerror = () => {
        appendLog('— Conexión perdida con el servidor —', 'error');
        const statusEl = document.getElementById('logPanelStatus');
        statusEl.textContent = '✗ Conexión perdida';
        statusEl.className = 'log-status done-error';
        es.close();
        _activeSSE = null;
        ['syncBtn','groupBtn','crawlBtn'].forEach(id => {
            const b = document.getElementById(id);
            if (b) b.disabled = false;
        });
        if (btn) btn.innerHTML = btnIdleHTML;
    };
}

// ─────────────────────────────────────────────
// SINCRONIZACIÓN
// ─────────────────────────────────────────────
function syncData() {
    startSSE(
        '/api/sync/stream',
        'syncBtn',
        '<i class="ri-refresh-line"></i> Sincronizar',
        'Sincronizar — Posiciones + Equipo propio'
    );
}

function groupSync() {
    startSSE(
        '/api/group/stream',
        'groupBtn',
        '<i class="ri-calendar-check-line"></i> Actualizar Grupo',
        'Actualizar Grupo — Posiciones + Fixture'
    );
}

function crawlFull() {
    startSSE(
        '/api/crawl/stream',
        'crawlBtn',
        '<i class="ri-database-2-line"></i> Crawl Completo',
        'Crawl Completo — Todas las categorías + jugadores'
    );
}

function formatCaracasTime(sqliteTimestamp) {
    // SQLite datetime('now') is UTC — forzar zona horaria Caracas (UTC-4)
    const d = new Date(sqliteTimestamp.replace(' ', 'T') + 'Z');
    return d.toLocaleString('es-VE', {
        timeZone: 'America/Caracas',
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

async function fetchLastSync() {
    try {
        const res = await fetch(`${API_BASE}/api/last-sync`);
        const data = await res.json();
        if (data.last_sync) {
            const formatted = formatCaracasTime(data.last_sync);
            const status = document.getElementById('syncStatus');
            if (!status.textContent || status.className === 'sync-status muted') {
                status.textContent = `Datos: ${formatted}`;
                status.className = 'sync-status muted';
            }
            const badge = document.getElementById('standingsLastSync');
            if (badge) badge.textContent = `Actualizado: ${formatted}`;
        }
    } catch (e) { /* silencioso */ }
}

// ─────────────────────────────────────────────
// PANEL DE NOTIFICACIONES
// ─────────────────────────────────────────────
async function toggleNotifications() {
    let panel = document.getElementById('notifPanel');
    if (panel) { panel.remove(); return; }

    panel = document.createElement('div');
    panel.id = 'notifPanel';
    panel.className = 'notif-panel glass-panel';
    panel.innerHTML = '<p class="notif-loading"><i class="ri-loader-4-line spin"></i> Cargando...</p>';
    document.querySelector('.topbar-actions').appendChild(panel);

    // Cerrar al hacer click fuera
    setTimeout(() => {
        document.addEventListener('click', function closePanel(e) {
            if (!panel.contains(e.target) && e.target.id !== 'bellBtn') {
                panel.remove();
                document.removeEventListener('click', closePanel);
            }
        });
    }, 100);

    try {
        const [syncRes, dashRes, teamsRes] = await Promise.all([
            fetch(`${API_BASE}/api/last-sync`),
            fetch(`${API_BASE}/api/dashboard`),
            fetch(`${API_BASE}/api/teams`),
        ]);
        const syncData  = await syncRes.json();
        const dashData  = await dashRes.json();
        const teamsData = await teamsRes.json();

        const lastSync = syncData.last_sync
            ? formatCaracasTime(syncData.last_sync)
            : 'Nunca';

        const teamCount   = (teamsData.teams || []).length;
        const ownTeam     = dashData.team_name || 'Mi Equipo';
        const position    = dashData.position  || '-';
        const points      = dashData.points    || 0;
        const winRate     = dashData.win_rate  || 0;

        panel.innerHTML = `
            <div class="notif-header">
                <span>Notificaciones</span>
                <button class="notif-close" onclick="document.getElementById('notifPanel').remove()">
                    <i class="ri-close-line"></i>
                </button>
            </div>
            <div class="notif-item notif-sync">
                <i class="ri-time-line"></i>
                <div>
                    <div class="notif-title">Última sincronización</div>
                    <div class="notif-sub">${lastSync}</div>
                </div>
            </div>
            <div class="notif-item">
                <i class="ri-trophy-line"></i>
                <div>
                    <div class="notif-title">${ownTeam}</div>
                    <div class="notif-sub">Posición #${position} · ${points} pts · ${winRate}% victorias</div>
                </div>
            </div>
            <div class="notif-item">
                <i class="ri-group-line"></i>
                <div>
                    <div class="notif-title">Equipos en base de datos</div>
                    <div class="notif-sub">${teamCount} equipos registrados</div>
                </div>
            </div>
            <div class="notif-item notif-info">
                <i class="ri-telegram-line"></i>
                <div>
                    <div class="notif-title">Alertas Telegram</div>
                    <div class="notif-sub">Configura TELEGRAM_TOKEN en .env para alertas automáticas</div>
                </div>
            </div>
        `;
    } catch (e) {
        panel.innerHTML = '<p class="text-muted" style="padding:1rem">Error al cargar datos.</p>';
    }
}

// ─────────────────────────────────────────────
// VISTA: INICIO (Dashboard)
// ─────────────────────────────────────────────
async function fetchDashboardData() {
    try {
        const res = await fetch(`${API_BASE}/api/dashboard`);
        const data = await res.json();

        if (data.error) {
            console.error("Error de API:", data.error);
            document.getElementById('matchesList').innerHTML =
                '<p class="text-muted">Sin datos. Ejecuta una sincronización primero.</p>';
            return;
        }

        // Guardar ID del equipo propio (fuente única de verdad)
        if (data.team_cta_id) ownTeamId = data.team_cta_id;

        // Nombres y subtítulos dinámicos
        const teamFullName = expandTeamName(data.team_name) || 'Mi Equipo';
        const catName = data.categoria_name || '';
        const ligaId  = data.liga_id || 32;

        document.getElementById('userNameLabel').textContent = teamFullName;
        const roleEl = document.getElementById('userRoleLabel');
        if (roleEl) roleEl.textContent = `Liga ${ligaId} / Cat ${catName}`;

        const equipoSub = document.getElementById('equipoSubtitle');
        if (equipoSub) equipoSub.textContent = `Liga ${ligaId} · ${catName} · Temporada Actual`;

        if (data.data_missing) {
            document.getElementById('valPosition').textContent = '–';
            document.getElementById('trendPosition').innerHTML =
                '<i class="ri-information-line"></i> Sin datos de tabla';
            document.getElementById('trendPosition').className = 'trend neutral';

            document.getElementById('valPoints').textContent = '–';
            document.querySelector('#valPoints').closest('.kpi-card')
                .querySelector('.kpi-footer .trend').textContent = 'Pendiente de sincronización';

            document.getElementById('valWinRate').textContent = '–';
            document.getElementById('valMatchesPlayed').textContent =
                `${data.scheduled_count ?? 0} Partidos Programados`;
        } else {
            document.getElementById('valPosition').textContent =
                data.position != null ? `#${data.position}` : '–';
            document.getElementById('valPoints').textContent =
                data.points != null ? data.points : '–';
            document.getElementById('valWinRate').textContent =
                data.win_rate != null ? `${data.win_rate}%` : '–';
            document.getElementById('valMatchesPlayed').textContent =
                `${data.matches_played} Partidos Jugados`;

            // Trend de posición dinámico
            const pos = data.position;
            const total = data.total_teams || 8;
            const trendEl = document.getElementById('trendPosition');
            if (trendEl && pos != null) {
                const third = Math.ceil(total / 3);
                if (pos <= third) {
                    trendEl.className = 'trend positive';
                    trendEl.innerHTML = `<i class="ri-arrow-up-line"></i> Zona Alta · ${pos} de ${total}`;
                } else if (pos <= third * 2) {
                    trendEl.className = 'trend neutral';
                    trendEl.innerHTML = `<i class="ri-subtract-line"></i> Zona Media · ${pos} de ${total}`;
                } else {
                    trendEl.className = 'trend negative';
                    trendEl.innerHTML = `<i class="ri-arrow-down-line"></i> Zona Baja · ${pos} de ${total}`;
                }
            }
        }

        renderMatches(data.recent_matches);
        renderChart(data.recent_matches);

    } catch (e) {
        console.error("Error al cargar el dashboard:", e);
    }
}

function renderMatches(matches) {
    const container = document.getElementById('matchesList');
    container.innerHTML = '';

    if (!matches || matches.length === 0) {
        container.innerHTML = '<p class="text-muted">Sin partidos recientes.</p>';
        return;
    }

    matches.forEach(m => {
        const isScheduled = m.status === 'scheduled' || m.result === '?';
        let resClass, resText, scoreHtml, dateHtml;

        if (m.result === 'W') {
            resClass = 'win';  resText = 'V';
        } else if (m.result === 'L') {
            resClass = 'loss'; resText = 'D';
        } else {
            resClass = 'upcoming'; resText = '<i class="ri-calendar-event-line"></i>';
        }

        dateHtml = m.date
            ? m.date
            : (isScheduled
                ? '<em style="color:var(--text-muted)">Fecha por confirmar</em>'
                : 'Fecha Pendiente');

        scoreHtml = (!isScheduled && m.score && m.score !== 'pendiente')
            ? m.score
            : '';

        const div = document.createElement('div');
        div.className = 'match-item';
        div.innerHTML = `
            <div class="match-result-badge ${resClass}">${resText}</div>
            <div class="match-info">
                <div class="match-opp">${expandTeamName(m.opponent) || 'Rival'}</div>
                <div class="match-date">${dateHtml}</div>
            </div>
            <div class="match-score">${scoreHtml}</div>
        `;
        container.appendChild(div);
    });
}

function renderChart(matches) {
    const ctx = document.getElementById('performanceChart').getContext('2d');
    if (performanceChartInstance) {
        performanceChartInstance.destroy();
        performanceChartInstance = null;
    }

    const reversed = [...(matches || [])].reverse();
    const labels = reversed.map(m => m.date || 'N/A');

    let currentScore = 50;
    const dataPoints = [];
    reversed.forEach(m => {
        if (m.result === 'W') currentScore += 10;
        else if (m.result === 'L') currentScore -= 5;
        dataPoints.push(currentScore);
    });

    if (dataPoints.length === 0) {
        const wrap = document.getElementById('performanceChart').closest('.canvas-wrapper');
        if (wrap) wrap.innerHTML = '<p class="text-muted" style="text-align:center;padding:3rem 1rem">Sin partidos registrados.<br>Ejecuta un Crawl Completo para obtener historial.</p>';
        return;
    }

    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(0, 228, 255, 0.4)');
    gradient.addColorStop(1, 'rgba(0, 228, 255, 0.0)');

    performanceChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Tendencia de Rendimiento',
                data: dataPoints,
                borderColor: '#00E4FF',
                backgroundColor: gradient,
                borderWidth: 3,
                pointBackgroundColor: '#0F1218',
                pointBorderColor: '#00E4FF',
                pointBorderWidth: 2,
                pointRadius: 4,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    display: false,
                    min: Math.min(...dataPoints) - 10,
                    max: Math.max(...dataPoints) + 10
                },
                x: {
                    grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                    ticks: { color: '#64748B' }
                }
            }
        }
    });
}

// ─────────────────────────────────────────────
// VISTA: MI EQUIPO
// ─────────────────────────────────────────────
async function fetchTeamData() {
    const teamId = ownTeamId || 7361;
    const roster = document.getElementById('playerRoster');
    const quickStats = document.getElementById('teamQuickStats');
    roster.innerHTML = '<div class="loading-spinner"></div>';
    quickStats.innerHTML = '<div class="loading-inline"></div>';

    try {
        const [teamRes, dashRes] = await Promise.all([
            fetch(`${API_BASE}/api/team/${teamId}`),
            fetch(`${API_BASE}/api/dashboard`)
        ]);
        const teamData = await teamRes.json();
        const dash = await dashRes.json();

        document.getElementById('teamNameHeading').textContent =
            expandTeamName(teamData.team?.name) || 'Mi Equipo';
        document.getElementById('playerCount').textContent =
            `${teamData.players?.length ?? 0} jugadores`;

        if (!dash.error) {
            quickStats.innerHTML = `
                <div class="quick-stat">
                    <span class="qs-value">#${dash.position}</span>
                    <span class="qs-label">Posición</span>
                </div>
                <div class="quick-stat">
                    <span class="qs-value">${dash.points}</span>
                    <span class="qs-label">Puntos</span>
                </div>
                <div class="quick-stat">
                    <span class="qs-value">${dash.win_rate}%</span>
                    <span class="qs-label">% Victorias</span>
                </div>
                <div class="quick-stat">
                    <span class="qs-value">${dash.matches_played}</span>
                    <span class="qs-label">Partidos</span>
                </div>
            `;
        } else {
            quickStats.innerHTML = '';
        }

        renderPlayerRoster(teamData.players || []);

    } catch (e) {
        roster.innerHTML = '<p class="text-muted">Error al cargar el equipo.</p>';
        console.error("Error al cargar equipo:", e);
    }
}

function renderPlayerRoster(players) {
    const container = document.getElementById('playerRoster');

    if (!players || players.length === 0) {
        container.innerHTML = '<p class="text-muted">Sin jugadores registrados. Ejecuta una sincronización.</p>';
        return;
    }

    const rows = players.map(p => {
        const s = p.stats || {};
        const mw  = s.matches_won  ?? '-';
        const ml  = s.matches_lost ?? '-';
        const sw  = s.sets_won     ?? '-';
        const sl  = s.sets_lost    ?? '-';
        const ranking = p.ranking || s.ranking || 'N/R';
        return `
        <div class="player-row clickable" onclick="openPlayerModal(${p.cta_id})">
            <div class="player-avatar"><i class="ri-user-3-line"></i></div>
            <div class="player-name">${p.name}</div>
            <div class="player-stat-pill">Ranking: <strong>${ranking}</strong></div>
            <div class="player-stat-pill">Partidos: <strong>${mw}G / ${ml}P</strong></div>
            <div class="player-stat-pill">Sets: <strong>${sw} / ${sl}</strong></div>
            <div class="player-detail-hint"><i class="ri-arrow-right-s-line"></i></div>
        </div>`;
    }).join('');

    container.innerHTML = rows;
}

// ─────────────────────────────────────────────
// MODAL: PERFIL DE JUGADOR
// ─────────────────────────────────────────────
async function openPlayerModal(ctaId) {
    const modal = document.getElementById('playerModal');
    const content = document.getElementById('playerModalContent');
    content.innerHTML = '<div class="loading-spinner"></div>';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    try {
        const res = await fetch(`${API_BASE}/api/player/${ctaId}`);
        const data = await res.json();
        content.innerHTML = renderPlayerModal(data);
    } catch (e) {
        content.innerHTML = '<p class="text-muted" style="padding:2rem">Error al cargar el jugador.</p>';
    }
}

function closePlayerModal(event) {
    if (event && event.currentTarget === event.target) {
        document.getElementById('playerModal').classList.remove('active');
        document.body.style.overflow = '';
    } else if (!event) {
        document.getElementById('playerModal').classList.remove('active');
        document.body.style.overflow = '';
    }
}

function renderPlayerModal(data) {
    const p = data.player || {};
    const s = data.stats || {};
    const team = data.team || {};
    const history = data.match_history || [];

    const ranking = s.ranking || 'N/R';
    const mw = s.matches_won ?? '-';
    const ml = s.matches_lost ?? '-';
    const total = (s.matches_won || 0) + (s.matches_lost || 0);
    const winPct = total > 0 ? Math.round((s.matches_won / total) * 100) : null;
    const sw = s.sets_won ?? '-';
    const sl = s.sets_lost ?? '-';

    const teamName = expandTeamName(team.name) || team.name || '—';
    const cat = team.categoria_name || '';

    const historyRows = history.length > 0 ? history.map(h => {
        const resClass = h.result === 'W' ? 'win' : h.result === 'L' ? 'loss' : '';
        const resLabel = h.result === 'W' ? 'G' : h.result === 'L' ? 'P' : h.result || '?';
        return `
        <div class="history-row">
            <span class="history-date">${h.match_date || '—'}</span>
            <span class="history-vs">vs</span>
            <span class="history-opponent">${h.opponent_name || '—'}</span>
            <span class="history-score">${h.score || '—'}</span>
            <span class="history-result ${resClass}">${resLabel}</span>
        </div>`;
    }).join('') : '<p class="text-muted" style="padding:.5rem 0">Sin historial disponible. Ejecuta un Crawl para obtener datos.</p>';

    return `
    <div class="modal-player-header">
        <div class="modal-avatar"><i class="ri-user-3-line"></i></div>
        <div>
            <h2 class="modal-player-name">${p.name || 'Jugador'}</h2>
            <p class="modal-player-sub">${teamName}${cat ? ' · ' + cat : ''}</p>
        </div>
    </div>

    <div class="modal-stats-grid">
        <div class="modal-stat">
            <span class="modal-stat-value">${ranking}</span>
            <span class="modal-stat-label">Ranking</span>
        </div>
        <div class="modal-stat">
            <span class="modal-stat-value">${mw}G / ${ml}P${winPct !== null ? ` <small>(${winPct}%)</small>` : ''}</span>
            <span class="modal-stat-label">Partidos</span>
        </div>
        <div class="modal-stat">
            <span class="modal-stat-value">${sw} / ${sl}</span>
            <span class="modal-stat-label">Sets G/P</span>
        </div>
    </div>

    <div class="modal-history-section">
        <h4 class="modal-section-title"><i class="ri-history-line"></i> Historial Reciente</h4>
        <div class="modal-history-list">${historyRows}</div>
    </div>`;
}

// ─────────────────────────────────────────────
// VISTA: POSICIONES
// ─────────────────────────────────────────────
function initCategoryTabs() {
    const tabs = document.querySelectorAll('#categoryTabs .cat-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const cat = tab.dataset.cat || null;
            const sub = document.getElementById('posicionesSubtitle');
            if (sub) {
                sub.textContent = cat
                    ? `Liga 32 · Categoría ${cat} · Temporada Actual`
                    : 'Liga 32 · Todas las Categorías · Temporada Actual';
            }
            fetchStandings(cat);
        });
    });
}

async function fetchStandings(categoria = null) {
    const container = document.getElementById('standingsTable');
    container.innerHTML = '<div class="loading-spinner"></div>';

    const url = categoria
        ? `${API_BASE}/api/standings?categoria=${encodeURIComponent(categoria)}`
        : `${API_BASE}/api/standings`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        const standings = data.standings || [];

        if (standings.length === 0) {
            container.innerHTML =
                '<p class="text-muted" style="padding:1.5rem">Sin datos de posiciones. Ejecuta una sincronización.</p>';
            return;
        }

        const showCat = !categoria;

        const rows = standings.map((s, i) => {
            const isOwn = s.team_cta_id === (ownTeamId || 7361);
            const catBadge = showCat && s.categoria_name
                ? `<span class="cat-badge cat-${s.categoria_name}">${s.categoria_name}</span>` : '';
            return `
            <tr class="${isOwn ? 'own-team' : ''}">
                <td class="pos-cell">${s.position ?? (i + 1)}</td>
                <td class="team-cell">
                    ${catBadge}${expandTeamName(s.team_name) || '?'}
                    ${isOwn ? '<span class="own-badge">TÚ</span>' : ''}
                </td>
                <td>${s.played    ?? '-'}</td>
                <td>${s.won      ?? '-'}</td>
                <td>${s.lost     ?? '-'}</td>
                <td>${s.sets_won  ?? '-'}</td>
                <td>${s.sets_lost ?? '-'}</td>
                <td>${s.games_won  ?? '-'}</td>
                <td>${s.games_lost ?? '-'}</td>
                <td class="pts-cell"><strong>${s.points ?? '-'}</strong></td>
            </tr>`;
        }).join('');

        container.innerHTML = `
        <table class="standings-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Equipo</th>
                    <th title="Partidos Jugados">PJ</th>
                    <th title="Partidos Ganados">PG</th>
                    <th title="Partidos Perdidos">PP</th>
                    <th title="Sets Ganados">SG</th>
                    <th title="Sets Perdidos">SP</th>
                    <th title="Games Ganados">GG</th>
                    <th title="Games Perdidos">GP</th>
                    <th title="Puntos">Pts</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    } catch (e) {
        container.innerHTML = '<p class="text-muted" style="padding:1.5rem">Error al cargar posiciones.</p>';
        console.error("Error al cargar posiciones:", e);
    }
}

// ─────────────────────────────────────────────
// VISTA: PREDICTOR DE DRAW
// ─────────────────────────────────────────────
async function fetchRivalTeams() {
    const select = document.getElementById('rivalSelect');
    select.innerHTML = '<option value="">-- Cargando equipos... --</option>';

    try {
        const res = await fetch(`${API_BASE}/api/teams`);
        const data = await res.json();
        const rivals = (data.teams || []).filter(t => !t.is_own_team);

        select.innerHTML = '<option value="">-- Selecciona un rival --</option>';
        rivals.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.cta_id;
            opt.textContent = expandTeamName(t.name);
            select.appendChild(opt);
        });

        if (rivals.length === 0) {
            select.innerHTML = '<option value="">Sin equipos disponibles. Ejecuta sync.</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">Error al cargar equipos</option>';
        console.error("Error al cargar equipos:", e);
    }
}

async function runFullPredictor() {
    const select  = document.getElementById('rivalSelect');
    const content = document.getElementById('fullPredictorContent');
    const rivalId = select.value;

    if (!rivalId) {
        content.innerHTML = '<p class="text-muted">Selecciona un equipo rival primero.</p>';
        return;
    }

    const rivalName = expandTeamName(select.options[select.selectedIndex].text);
    content.innerHTML = `
        <div style="text-align:center;padding:2rem">
            <div class="loading-spinner" style="margin:0 auto 1rem"></div>
            <p class="text-muted">Calculando alineación óptima contra <strong>${rivalName}</strong>...</p>
        </div>`;

    try {
        const res = await fetch(`${API_BASE}/api/lineup-predictor/${rivalId}`);
        const data = await res.json();

        if (!data.our_suggestions || data.our_suggestions.length === 0) {
            content.innerHTML =
                '<p class="text-muted" style="padding:1rem">Sin datos suficientes para predecir. Ejecuta un crawl completo del equipo rival.</p>';
            return;
        }

        let html = `<div class="predictor-rival-title">vs. <strong>${rivalName}</strong></div>`;
        html += '<div class="predictor-columns">';

        // Columna: Sugerencia Táchira
        html += '<div class="pred-col"><h4>Sugerencia Táchira</h4>';
        data.our_suggestions.forEach(s => {
            const p1 = s.player?.name || '?';
            if (s.type === 'singles') {
                html += `
                <div class="matchup-row">
                    <div class="matchup-pos">S${s.position}</div>
                    <div class="player-box"><span>${p1}</span></div>
                    <div class="vs-badge">VS</div>
                    <div class="player-box"><span class="rival-name">${s.vs || 'Rival'}</span></div>
                </div>`;
            } else {
                const partner = s.partner?.name || '?';
                html += `
                <div class="matchup-row">
                    <div class="matchup-pos">Dbl</div>
                    <div class="player-box"><span>${p1} &amp; ${partner}</span></div>
                </div>`;
            }
        });
        html += '</div>';

        // Columna: Alineación rival estimada
        if (data.rival_predicted && data.rival_predicted.length > 0) {
            html += '<div class="pred-col"><h4>Rival Estimado</h4>';
            data.rival_predicted.forEach(s => {
                const name = s.player?.name || '?';
                const pos  = s.type === 'singles' ? `S${s.position}` : 'Dbl';
                const conf = Math.round((s.confidence || 0.5) * 100);
                html += `
                <div class="matchup-row rival-pred-row">
                    <div class="matchup-pos">${pos}</div>
                    <div class="player-box"><span>${name}</span></div>
                    <div class="confidence-wrap">
                        <div class="confidence-bar">
                            <div class="confidence-fill" style="width:${conf}%"></div>
                        </div>
                        <span class="confidence-label">${conf}%</span>
                    </div>
                </div>`;
            });
            html += '</div>';
        }

        html += '</div>';
        content.innerHTML = html;

    } catch (e) {
        content.innerHTML = `<p class="text-muted">Error al calcular: ${e.message}</p>`;
    }
}
