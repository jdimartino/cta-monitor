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

function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.getElementById('sidebarOverlay').classList.toggle('visible');
}
function closeSidebar() {
    document.querySelector('.sidebar').classList.remove('open');
    document.getElementById('sidebarOverlay').classList.remove('visible');
}

document.addEventListener("DOMContentLoaded", () => {
    // Conectar navegación
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            navigateTo(item.dataset.view);
            closeSidebar();
        });
    });

    // Carga inicial
    loadClubs().then(() => {
        navigateTo('posiciones');
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
    if (viewId === 'equipo')         fetchTeamData();
    else if (viewId === 'posiciones') {
        initCategoryTabs();
        // Ocultar group-tabs y cargar tabla global (Todas) al entrar
        const groupTabs = document.getElementById('groupTabs');
        if (groupTabs) groupTabs.style.display = 'none';
        fetchTeamRankings(null);
    }
    else if (viewId === 'predictor') fetchRivalTeams();
    else if (viewId === 'refuerzos') initRefuerzosView();
    // team-detail se carga desde showTeamDetailView, no aquí
}

async function showTeamDetailView(teamCtaId, teamName, standingsRow = null) {
    // Activar vista sin disparar carga de datos del navigateTo normal
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
    const view = document.getElementById('view-team-detail');
    if (view) view.classList.add('active');

    // Resetear contenido con spinners
    document.getElementById('tdTeamName').textContent    = expandTeamName(teamName) || teamName;
    document.getElementById('tdTeamSubtitle').textContent = '';
    document.getElementById('tdQuickStats').innerHTML    = '';
    document.getElementById('tdMetaCard').innerHTML      = '';
    document.getElementById('tdRoster').innerHTML        = '<div class="loading-spinner"></div>';
    document.getElementById('tdMatches').innerHTML       = '';
    document.getElementById('tdMatchesSection').style.display = 'none';
    document.getElementById('tdPlayerCount').textContent = '';

    try {
        const [teamRes, capRes, matchRes] = await Promise.all([
            fetch(`${API_BASE}/api/team/${teamCtaId}`),
            fetch(`${API_BASE}/api/team/${teamCtaId}/captains`),
            fetch(`${API_BASE}/api/team/${teamCtaId}/matches`),
        ]);
        const teamData  = await teamRes.json();
        const capData   = capRes.ok   ? await capRes.json()   : null;
        const matchData = matchRes.ok ? await matchRes.json() : null;

        const team    = teamData.team    || {};
        const players = teamData.players || [];
        const matches = matchData?.matches || [];

        const sr = standingsRow;
        const cat = sr?.categoria_name || team.categoria_name || '';

        document.getElementById('tdTeamName').textContent    = expandTeamName(teamName) || teamName;
        document.getElementById('tdTeamSubtitle').textContent = cat;
        document.getElementById('tdPlayerCount').textContent  = `${players.length} jugador${players.length !== 1 ? 'es' : ''}`;

        // ── Quick stats ──
        if (sr) {
            const winRate = sr.played > 0 ? Math.round((sr.won / sr.played) * 100) : 0;
            const pAve   = team.p_ave   != null ? Number(team.p_ave).toFixed(3)   : null;
            const setAve = team.set_ave != null ? Number(team.set_ave).toFixed(3) : null;
            document.getElementById('tdQuickStats').innerHTML = `
                <div class="quick-stat"><span class="qs-value">#${sr.position ?? '—'}</span><span class="qs-label">Posición</span></div>
                <div class="quick-stat"><span class="qs-value">${sr.points ?? '—'}</span><span class="qs-label">Puntos</span></div>
                <div class="quick-stat"><span class="qs-value">${winRate}%</span><span class="qs-label">% Victorias</span></div>
                <div class="quick-stat"><span class="qs-value">${sr.played ?? '—'}</span><span class="qs-label">Partidos</span></div>
                ${pAve   ? `<div class="quick-stat"><span class="qs-value">${pAve}</span><span class="qs-label">P Ave</span></div>` : ''}
                ${setAve ? `<div class="quick-stat"><span class="qs-value">${setAve}</span><span class="qs-label">Set Ave</span></div>` : ''}`;
        }

        // ── Meta card (capitanes, forma, protestas) ──
        renderTeamMetaCard(team, capData, 'tdMetaCard');

        // ── Roster ──
        renderPlayerRoster(players, 'tdRoster');

        // ── Partidos ──
        if (matches.length > 0) {
            const past     = matches.filter(m => m.home_score !== null && m.home_score !== '');
            const upcoming = matches.filter(m => !m.home_score || m.home_score === '');

            const renderMatch = (m) => {
                const isHome = m.home_cta_id === teamCtaId;
                const isAway = m.away_cta_id === teamCtaId;
                let resultBadge = '';
                if (m.home_score !== null && m.home_score !== '') {
                    const hs = parseInt(m.home_score), as_ = parseInt(m.away_score);
                    const won  = (isHome && hs > as_) || (isAway && as_ > hs);
                    const lost = (isHome && hs < as_) || (isAway && as_ < hs);
                    const cls  = won ? 'result-badge win' : (lost ? 'result-badge loss' : 'result-badge draw');
                    resultBadge = `<span class="${cls}">${m.home_score} - ${m.away_score}</span>`;
                } else {
                    resultBadge = '<span class="result-badge pending">Pendiente</span>';
                }
                let rd = m.raw_detail;
                if (typeof rd === 'string') { try { rd = JSON.parse(rd); } catch(_) { rd = {}; } }
                const sede = rd?.sede || '';
                const hora = rd?.time || '';
                const jor  = rd?.jornada || '';
                return `
                <div class="fixture-row${isHome || isAway ? ' own-fixture' : ''}" onclick="openMatchDetailModal(${m.id})">
                    <div class="fixture-jornada-label">
                        ${jor  ? `<span class="fixture-jor">${jor}</span>` : ''}
                        ${m.match_date ? `<span class="fixture-date-inline">${m.match_date}</span>` : ''}
                    </div>
                    <div class="fixture-teams-row">
                        <span class="fixture-home">${expandTeamName(m.home_team_name) || m.home_team_name}</span>
                        <span class="fixture-vs">vs</span>
                        <span class="fixture-away">${expandTeamName(m.away_team_name) || m.away_team_name}</span>
                    </div>
                    <div class="fixture-meta">
                        ${hora ? `<span class="fixture-time"><i class="ri-time-line"></i> ${hora}</span>` : ''}
                        ${sede ? `<span class="fixture-sede"><i class="ri-map-pin-line"></i> ${sede}</span>` : ''}
                    </div>
                    ${resultBadge}
                </div>`;
            };

            let matchesHtml = '';
            if (past.length > 0)
                matchesHtml += `<div class="team-modal-section-title"><i class="ri-history-line"></i> Resultados</div>
                    <div class="fixtures-section">${past.map(renderMatch).join('')}</div>`;
            if (upcoming.length > 0)
                matchesHtml += `<div class="team-modal-section-title"><i class="ri-calendar-line"></i> Próximos partidos</div>
                    <div class="fixtures-section">${upcoming.map(renderMatch).join('')}</div>`;

            document.getElementById('tdMatches').innerHTML = matchesHtml;
            document.getElementById('tdMatchesSection').style.display = '';
        }

    } catch(e) {
        document.getElementById('tdRoster').innerHTML = '<p class="empty-state-msg">Error al cargar el equipo.</p>';
        console.error('showTeamDetailView error:', e);
    }
}

// ─────────────────────────────────────────────
// VISTA: REFUERZOS
// ─────────────────────────────────────────────
let _refuerzosCatInit = false;

async function initRefuerzosView() {
    if (!_refuerzosCatInit) {
        _refuerzosCatInit = true;
        try {
            const res = await fetch(`${API_BASE}/api/categories`);
            const data = await res.json();
            const sel = document.getElementById('refuerzosCatFilter');
            if (sel && data.categories) {
                data.categories.forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c.name || c;
                    opt.textContent = c.name || c;
                    sel.appendChild(opt);
                });
                sel.addEventListener('change', () => loadRefuerzos());
            }
        } catch (e) { /* ignore — categorias no disponible */ }
    }
    loadRefuerzos();
}

async function loadRefuerzos() {
    const list = document.getElementById('refuerzosList');
    const count = document.getElementById('refuerzosCount');
    if (!list) return;
    list.innerHTML = '<div class="loading-spinner"></div>';

    const cat = document.getElementById('refuerzosCatFilter')?.value || '';
    const url = `${API_BASE}/api/refuerzos${cat ? '?categoria=' + encodeURIComponent(cat) : ''}`;
    try {
        const res = await fetch(url);
        const data = await res.json();
        const items = data.items || [];
        if (count) count.textContent = `${items.length} aparición${items.length !== 1 ? 'es' : ''}`;

        if (!items.length) {
            list.innerHTML = '<p class="empty-state-msg">No hay refuerzos detectados todavía. Ejecuta un crawl global.</p>';
            return;
        }

        list.innerHTML = items.map(r => {
            const photo = r.photo_url
                ? (r.photo_url.startsWith('http') ? r.photo_url : `https://ctatenis.com${r.photo_url}`)
                : null;
            const photoHtml = photo
                ? `<img class="ref-photo" src="${photo}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'cap-avatar-fallback',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
                : `<div class="cap-avatar-fallback"><i class="ri-user-3-line"></i></div>`;
            const opp = r.rubber_type === 'doubles' && r.partner_name
                ? `${r.partner_name} → vs ${r.opponent_name}`
                : `vs ${r.opponent_name}`;
            const resCls = r.result === 'W' ? 'win' : r.result === 'L' ? 'loss' : '';
            return `
            <div class="refuerzo-row">
                ${photoHtml}
                <div class="ref-meta">
                    <span class="ref-name clickable" onclick="openPlayerModal(${r.player_cta_id})">${r.player_name}</span>
                    <span class="ref-detail">${r.jornada || '?'} · ${r.season || ''} ${r.category_match || ''} · ${opp}</span>
                </div>
                <span class="ref-played-for" title="Equipo donde reforzó">${r.played_for}</span>
                <span class="ref-result ${resCls}">${r.result || ''} ${r.score || ''}</span>
            </div>`;
        }).join('');
    } catch (e) {
        list.innerHTML = '<p class="empty-state-msg">Error al cargar refuerzos.</p>';
        console.error(e);
    }
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
        const [teamRes, dashRes, capRes] = await Promise.all([
            fetch(`${API_BASE}/api/team/${teamId}`),
            fetch(`${API_BASE}/api/dashboard`),
            fetch(`${API_BASE}/api/team/${teamId}/captains`),
        ]);
        const teamData = await teamRes.json();
        const dash = await dashRes.json();
        const captains = capRes.ok ? await capRes.json() : null;

        document.getElementById('teamNameHeading').textContent =
            expandTeamName(teamData.team?.name) || 'Mi Equipo';
        document.getElementById('playerCount').textContent =
            `${teamData.players?.length ?? 0} jugadores`;

        const t = teamData.team || {};
        const pAve = t.p_ave !== null && t.p_ave !== undefined ? Number(t.p_ave).toFixed(3) : null;
        const setAve = t.set_ave !== null && t.set_ave !== undefined ? Number(t.set_ave).toFixed(3) : null;

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
                ${pAve ? `<div class="quick-stat"><span class="qs-value">${pAve}</span><span class="qs-label">P Ave</span></div>` : ''}
                ${setAve ? `<div class="quick-stat"><span class="qs-value">${setAve}</span><span class="qs-label">Set Ave</span></div>` : ''}
            `;
        } else {
            quickStats.innerHTML = '';
        }

        renderTeamMetaCard(t, captains);
        renderPlayerRoster(teamData.players || []);

    } catch (e) {
        roster.innerHTML = '<p class="text-muted">Error al cargar el equipo.</p>';
        console.error("Error al cargar equipo:", e);
    }
}

function renderTeamMetaCard(team, captains, hostId = 'teamMetaCard') {
    const host = document.getElementById(hostId);
    if (!host) return;
    if (!team) { host.innerHTML = ''; return; }

    const recent = (team.recent_form || '').slice(-5);
    const formPills = recent
        ? recent.split('').map(l => `<span class="form-pill form-${l.toLowerCase()}">${l}</span>`).join('')
        : '<span class="text-muted">—</span>';

    const protestsTotal = team.protests_total;
    const protestsUsed = team.protests_used ?? 0;
    const protestsAvail = (typeof protestsTotal === 'number')
        ? `${protestsTotal - protestsUsed}/${protestsTotal}`
        : '—';

    const captainCard = (cap, role) => {
        if (!cap || !cap.name) return '';
        const photo = cap.photo_url
            ? (cap.photo_url.startsWith('http') ? cap.photo_url : `https://ctatenis.com${cap.photo_url}`)
            : null;
        const photoHtml = photo
            ? `<img class="cap-avatar" src="${photo}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'cap-avatar-fallback',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
            : `<div class="cap-avatar-fallback"><i class="ri-user-3-line"></i></div>`;
        const links = [];
        if (cap.email) links.push(`<a href="mailto:${cap.email}" title="Email"><i class="ri-mail-line"></i></a>`);
        if (cap.phone) links.push(`<a href="tel:${cap.phone}" title="Teléfono"><i class="ri-phone-line"></i></a>`);
        const onclick = cap.cta_id ? `onclick="openPlayerModal(${cap.cta_id})"` : '';
        return `
        <div class="captain-row clickable" ${onclick}>
            ${photoHtml}
            <div class="cap-info">
                <span class="cap-role">${role}</span>
                <span class="cap-name">${cap.name}</span>
            </div>
            <div class="cap-actions">${links.join('')}</div>
        </div>`;
    };

    const capData = captains || { captain: { name: team.captain_name }, subcaptain: { name: team.subcaptain_name } };

    host.innerHTML = `
    <div class="team-meta-card">
        <div class="team-meta-section">
            <h4 class="team-meta-title"><i class="ri-shield-user-line"></i> Capitanes</h4>
            ${captainCard(capData.captain, 'Capitán')}
            ${captainCard(capData.subcaptain, 'Sub-Capitán')}
        </div>

        <div class="team-meta-section">
            <h4 class="team-meta-title"><i class="ri-pulse-line"></i> Forma reciente</h4>
            <div class="form-pills">${formPills}</div>
        </div>

        <div class="team-meta-section">
            <h4 class="team-meta-title"><i class="ri-flag-2-line"></i> Protestas</h4>
            <div class="protest-stat">
                <span class="protest-big">${protestsAvail}</span>
                <span class="protest-sub">disponibles · ${protestsUsed} usadas</span>
            </div>
        </div>
    </div>`;
}

function renderPlayerRoster(players, containerId = 'playerRoster') {
    const container = document.getElementById(containerId);

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
        const photoUrl = p.photo_url
            ? (p.photo_url.startsWith('http') ? p.photo_url : `https://ctatenis.com${p.photo_url}`)
            : null;
        const avatar = photoUrl
            ? `<img class="player-avatar-img" src="${photoUrl}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'player-avatar',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
            : `<div class="player-avatar"><i class="ri-user-3-line"></i></div>`;
        const delta = s.ranking_delta;
        const deltaHtml = (delta !== null && delta !== undefined)
            ? `<span class="player-delta ${delta >= 0 ? 'delta-up' : 'delta-down'}">${delta >= 0 ? '▲' : '▼'} ${Math.abs(Number(delta)).toFixed(2)}</span>`
            : '';
        return `
        <div class="player-row clickable" onclick="openPlayerModal(${p.cta_id})">
            ${avatar}
            <div class="player-name">${p.name}</div>
            <div class="player-stat-pill">Ranking: <strong>${ranking}</strong> ${deltaHtml}</div>
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
        const [profileRes, rankRes] = await Promise.all([
            fetch(`${API_BASE}/api/player/${ctaId}`),
            fetch(`${API_BASE}/api/player/${ctaId}/ranking-history`),
        ]);
        const data = await profileRes.json();
        const ranking = rankRes.ok ? await rankRes.json() : { history: [] };
        data.ranking_history = ranking.history || [];
        content.innerHTML = renderPlayerModal(data);
        renderRankingSparkline(data.ranking_history);
        wireRefuerzosToggle();
    } catch (e) {
        content.innerHTML = '<p class="text-muted" style="padding:2rem">Error al cargar el jugador.</p>';
    }
}

async function openTeamModal(teamCtaId, teamName, standingsRow = null) {
    const modal = document.getElementById('playerModal');
    const content = document.getElementById('playerModalContent');
    content.innerHTML = '<div class="loading-spinner"></div>';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    try {
        const [teamRes, capRes, matchRes] = await Promise.all([
            fetch(`${API_BASE}/api/team/${teamCtaId}`),
            fetch(`${API_BASE}/api/team/${teamCtaId}/captains`),
            fetch(`${API_BASE}/api/team/${teamCtaId}/matches`),
        ]);
        const teamData = await teamRes.json();
        const capData  = capRes.ok  ? await capRes.json()  : null;
        const matchData = matchRes.ok ? await matchRes.json() : null;

        const team    = teamData.team    || {};
        const players = teamData.players || [];
        const matches = matchData?.matches || [];

        // ── Quick stats (de standings row si viene del click en posiciones) ──
        const sr = standingsRow;
        let quickStatsHtml = '';
        if (sr) {
            const winRate = sr.played > 0 ? Math.round((sr.won / sr.played) * 100) : 0;
            const pAve  = team.p_ave   != null ? Number(team.p_ave).toFixed(3)   : null;
            const setAve = team.set_ave != null ? Number(team.set_ave).toFixed(3) : null;
            quickStatsHtml = `
            <div class="quick-stats-grid team-modal-stats">
                <div class="quick-stat"><span class="qs-value">#${sr.position ?? '—'}</span><span class="qs-label">Posición</span></div>
                <div class="quick-stat"><span class="qs-value">${sr.points ?? '—'}</span><span class="qs-label">Puntos</span></div>
                <div class="quick-stat"><span class="qs-value">${winRate}%</span><span class="qs-label">% Victorias</span></div>
                <div class="quick-stat"><span class="qs-value">${sr.played ?? '—'}</span><span class="qs-label">Partidos</span></div>
                ${pAve  ? `<div class="quick-stat"><span class="qs-value">${pAve}</span><span class="qs-label">P Ave</span></div>` : ''}
                ${setAve ? `<div class="quick-stat"><span class="qs-value">${setAve}</span><span class="qs-label">Set Ave</span></div>` : ''}
            </div>`;
        }

        // ── Capitanes ──
        const capInfo = capData || { captain: { name: team.captain_name }, subcaptain: { name: team.subcaptain_name } };
        const captainCard = (cap, role) => {
            if (!cap || !cap.name) return '';
            const photo = cap.photo_url
                ? (cap.photo_url.startsWith('http') ? cap.photo_url : `https://ctatenis.com${cap.photo_url}`)
                : null;
            const photoHtml = photo
                ? `<img class="cap-avatar" src="${photo}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'cap-avatar-fallback',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
                : `<div class="cap-avatar-fallback"><i class="ri-user-3-line"></i></div>`;
            const links = [];
            if (cap.email) links.push(`<a href="mailto:${cap.email}" title="Email"><i class="ri-mail-line"></i></a>`);
            if (cap.phone) links.push(`<a href="tel:${cap.phone}" title="Teléfono"><i class="ri-phone-line"></i></a>`);
            const onclick = cap.cta_id ? `onclick="openPlayerModal(${cap.cta_id})"` : '';
            return `
            <div class="captain-row clickable" ${onclick}>
                ${photoHtml}
                <div class="cap-info"><span class="cap-role">${role}</span><span class="cap-name">${cap.name}</span></div>
                <div class="cap-actions">${links.join('')}</div>
            </div>`;
        };

        // ── Forma reciente ──
        const recent = (team.recent_form || '').slice(-5);
        const formPills = recent
            ? recent.split('').map(l => `<span class="form-pill form-${l.toLowerCase()}">${l}</span>`).join('')
            : '<span class="text-muted">—</span>';

        // ── Protestas ──
        const protestsUsed  = team.protests_used  ?? capData?.protests?.used  ?? 0;
        const protestsTotal = team.protests_total ?? capData?.protests?.total ?? null;
        const protestsAvail = protestsTotal != null ? `${protestsTotal - protestsUsed}/${protestsTotal}` : '—';

        // ── Roster de jugadores ──
        const playerRows = players.map(p => {
            const s = p.stats || {};
            const mw  = s.matches_won  ?? '-';
            const ml  = s.matches_lost ?? '-';
            const sw  = s.sets_won     ?? '-';
            const sl  = s.sets_lost    ?? '-';
            const ranking = p.ranking || s.ranking || 'N/R';
            const photoUrl = p.photo_url
                ? (p.photo_url.startsWith('http') ? p.photo_url : `https://ctatenis.com${p.photo_url}`)
                : null;
            const avatar = photoUrl
                ? `<img class="player-avatar-img" src="${photoUrl}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'player-avatar',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
                : `<div class="player-avatar"><i class="ri-user-3-line"></i></div>`;
            const delta = s.ranking_delta;
            const deltaHtml = (delta !== null && delta !== undefined)
                ? `<span class="player-delta ${delta >= 0 ? 'delta-up' : 'delta-down'}">${delta >= 0 ? '▲' : '▼'} ${Math.abs(Number(delta)).toFixed(2)}</span>`
                : '';
            return `
            <div class="player-row clickable" onclick="openPlayerModal(${p.cta_id})">
                ${avatar}
                <div class="player-name">${p.name}</div>
                <div class="player-stat-pill">Ranking: <strong>${ranking}</strong> ${deltaHtml}</div>
                <div class="player-stat-pill">Partidos: <strong>${mw}G / ${ml}P</strong></div>
                <div class="player-stat-pill">Sets: <strong>${sw} / ${sl}</strong></div>
                <div class="player-detail-hint"><i class="ri-arrow-right-s-line"></i></div>
            </div>`;
        }).join('') || '<p class="empty-state-msg">Sin jugadores registrados.</p>';

        // ── Partidos (resultados + próximos) ──
        let matchesHtml = '';
        if (matches.length > 0) {
            const past     = matches.filter(m => m.home_score !== null && m.home_score !== '' && m.away_score !== null && m.away_score !== '');
            const upcoming = matches.filter(m => !m.home_score || m.home_score === '');

            const renderMatch = (m) => {
                const isHome = m.home_cta_id === teamCtaId;
                const isAway = m.away_cta_id === teamCtaId;
                let resultBadge = '';
                if (m.home_score !== null && m.home_score !== '' && m.away_score !== null && m.away_score !== '') {
                    const hs = parseInt(m.home_score), as_ = parseInt(m.away_score);
                    const won  = (isHome && hs > as_) || (isAway && as_ > hs);
                    const lost = (isHome && hs < as_) || (isAway && as_ < hs);
                    const cls  = won ? 'result-badge win' : (lost ? 'result-badge loss' : 'result-badge draw');
                    resultBadge = `<span class="${cls}">${m.home_score} - ${m.away_score}</span>`;
                } else {
                    resultBadge = '<span class="result-badge pending">Pendiente</span>';
                }
                let rd = m.raw_detail;
                if (typeof rd === 'string') { try { rd = JSON.parse(rd); } catch(_) { rd = {}; } }
                const sede = rd?.sede || '';
                const hora = rd?.time || '';
                const jor  = rd?.jornada || '';
                return `
                <div class="fixture-row${isHome || isAway ? ' own-fixture' : ''}" onclick="openMatchDetailModal(${m.id})">
                    <div class="fixture-jornada-label">${jor ? `<span class="fixture-jor">${jor}</span>` : ''}${m.match_date ? `<span class="fixture-date-inline">${m.match_date}</span>` : ''}</div>
                    <div class="fixture-teams-row">
                        <span class="fixture-home">${expandTeamName(m.home_team_name) || m.home_team_name}</span>
                        <span class="fixture-vs">vs</span>
                        <span class="fixture-away">${expandTeamName(m.away_team_name) || m.away_team_name}</span>
                    </div>
                    <div class="fixture-meta">
                        ${hora ? `<span class="fixture-time"><i class="ri-time-line"></i> ${hora}</span>` : ''}
                        ${sede ? `<span class="fixture-sede"><i class="ri-map-pin-line"></i> ${sede}</span>` : ''}
                    </div>
                    ${resultBadge}
                </div>`;
            };

            const pastHtml = past.length > 0
                ? `<div class="team-modal-section-title"><i class="ri-history-line"></i> Resultados</div>
                   <div class="fixtures-section modal-fixtures">${past.map(renderMatch).join('')}</div>`
                : '';
            const upcomingHtml = upcoming.length > 0
                ? `<div class="team-modal-section-title"><i class="ri-calendar-line"></i> Próximos partidos</div>
                   <div class="fixtures-section modal-fixtures">${upcoming.map(renderMatch).join('')}</div>`
                : '';
            matchesHtml = pastHtml + upcomingHtml;
        }

        const cat = sr?.categoria_name || team.categoria_name || '';

        content.innerHTML = `
        <div class="team-modal-header">
            <h2>${expandTeamName(teamName)}</h2>
            ${cat ? `<p class="page-subtitle">${cat}</p>` : ''}
        </div>
        ${quickStatsHtml}
        <div class="team-meta-card">
            <div class="team-meta-section">
                <h4 class="team-meta-title"><i class="ri-shield-user-line"></i> Capitanes</h4>
                ${captainCard(capInfo.captain, 'Capitán')}
                ${captainCard(capInfo.subcaptain, 'Sub-Capitán')}
            </div>
            <div class="team-meta-section">
                <h4 class="team-meta-title"><i class="ri-pulse-line"></i> Forma reciente</h4>
                <div class="form-pills">${formPills}</div>
            </div>
            <div class="team-meta-section">
                <h4 class="team-meta-title"><i class="ri-flag-2-line"></i> Protestas</h4>
                <div class="protest-stat">
                    <span class="protest-big">${protestsAvail}</span>
                    <span class="protest-sub">disponibles · ${protestsUsed} usadas</span>
                </div>
            </div>
        </div>
        <div class="team-modal-section-title"><i class="ri-group-line"></i> Jugadores (${players.length})</div>
        <div class="player-roster modal-roster">${playerRows}</div>
        ${matchesHtml}`;

    } catch (e) {
        content.innerHTML = '<p class="empty-state-msg">Error al cargar el equipo.</p>';
        console.error('openTeamModal error:', e);
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

async function openMatchDetailModal(matchId) {
    const modal   = document.getElementById('playerModal');
    const content = document.getElementById('playerModalContent');
    content.innerHTML = '<div class="loading-spinner"></div>';
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    try {
        const res  = await fetch(`${API_BASE}/api/match/${matchId}/details`);
        const data = await res.json();
        if (!res.ok) { content.innerHTML = '<p class="empty-state-msg">No se pudo cargar el partido.</p>'; return; }

        const match   = data.match   || {};
        const rubbers = data.rubbers || [];
        const hs = match.home_score ?? '', as_ = match.away_score ?? '';
        const hasScore = hs !== '' && as_ !== '';
        const scoreBadge = hasScore
            ? `<span class="result-badge ${parseInt(hs) > parseInt(as_) ? 'win' : parseInt(hs) < parseInt(as_) ? 'loss' : 'draw'}">${hs} – ${as_}</span>`
            : '<span class="result-badge pending">Pendiente</span>';

        const renderRubber = r => {
            const cls = r.result === 'W' ? 'win' : 'loss';
            const partner = r.partner_name ? `<span class="rubber-partner">/ ${r.partner_name}</span>` : '';
            return `
            <div class="rubber-card">
                <div class="rubber-players">
                    <span class="rubber-player clickable" onclick="event.stopPropagation();openPlayerModal(${r.player_cta_id})">${r.player_name}</span>
                    ${partner}
                    <span class="rubber-vs">vs</span>
                    <span class="rubber-opponent">${r.opponent_name || '—'}</span>
                </div>
                <div class="rubber-right">
                    <span class="rubber-score">${r.score || '—'}</span>
                    <span class="result-badge ${cls}">${r.result}</span>
                </div>
            </div>`;
        };

        const singles = rubbers.filter(r => r.rubber_type === 'singles');
        const doubles = rubbers.filter(r => r.rubber_type === 'doubles');

        content.innerHTML = `
        <div class="match-detail-header">
            <div class="match-detail-teams">
                <span class="match-detail-team home">${expandTeamName(match.home_team_name)||match.home_team_name}</span>
                <div class="match-detail-score">${scoreBadge}</div>
                <span class="match-detail-team away">${expandTeamName(match.away_team_name)||match.away_team_name}</span>
            </div>
            <div class="match-detail-meta">
                ${match.jornada ? `<span class="fixture-jor">${match.jornada}</span>` : ''}
                ${match.match_date ? `<span class="fixture-date-inline">${match.match_date}</span>` : ''}
            </div>
        </div>
        <div class="rubber-list">
            ${singles.length ? `<div class="rubber-section-title"><i class="ri-user-line"></i> Singles</div>${singles.map(renderRubber).join('')}` : ''}
            ${doubles.length ? `<div class="rubber-section-title"><i class="ri-group-line"></i> Dobles</div>${doubles.map(renderRubber).join('')}` : ''}
            ${rubbers.length === 0 ? '<p class="empty-state-msg">Sin detalles de gomas para este partido.</p>' : ''}
        </div>`;
    } catch(e) {
        content.innerHTML = '<p class="empty-state-msg">Error al cargar el partido.</p>';
        console.error('openMatchDetailModal error:', e);
    }
}

function renderPlayerModal(data) {
    const p = data.player || {};
    const s = data.stats || {};
    const team = data.team || {};
    const history = data.match_history || [];

    const ranking = s.ranking ?? 'N/R';
    const delta = (s.ranking_delta !== null && s.ranking_delta !== undefined) ? Number(s.ranking_delta) : null;
    const deltaCls = delta === null ? '' : (delta >= 0 ? 'delta-up' : 'delta-down');
    const deltaArrow = delta === null ? '' : (delta >= 0 ? '▲' : '▼');
    const deltaTxt = delta === null ? '' :
        `<span class="player-delta ${deltaCls}">${deltaArrow} ${Math.abs(delta).toFixed(2)}</span>`;

    const mw = s.matches_won ?? '-';
    const ml = s.matches_lost ?? '-';
    const total = (s.matches_won || 0) + (s.matches_lost || 0);
    const winPct = total > 0 ? Math.round((s.matches_won / total) * 100) : null;
    const sw = s.sets_won ?? '-';
    const sl = s.sets_lost ?? '-';

    const teamName = expandTeamName(team.name) || team.name || '—';
    const cat = team.categoria_name || '';

    const photoSrc = p.photo_url
        ? (p.photo_url.startsWith('http') ? p.photo_url : `https://ctatenis.com${p.photo_url}`)
        : null;
    const avatarHtml = photoSrc
        ? `<img class="modal-avatar-img" src="${photoSrc}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'modal-avatar',innerHTML:'<i class=\\'ri-user-3-line\\'></i>'}))">`
        : `<div class="modal-avatar"><i class="ri-user-3-line"></i></div>`;

    const chips = Array.isArray(s.chips) ? s.chips : [];
    const chipsHtml = chips.length
        ? `<div class="player-chips">${chips.map(c => `<span class="player-chip">${c}</span>`).join('')}</div>`
        : '';

    const estadoBadge = s.estado
        ? `<span class="status-badge ${s.estado.toLowerCase() === 'aprobado' ? 'ok' : 'warn'}">${s.estado}</span>`
        : '';

    // PII section
    const piiRows = [];
    if (p.email)      piiRows.push(`<div class="pii-row"><i class="ri-mail-line"></i> <a href="mailto:${p.email}">${p.email}</a></div>`);
    if (p.phone)      piiRows.push(`<div class="pii-row"><i class="ri-phone-line"></i> <a href="tel:${p.phone}">${p.phone}</a></div>`);
    if (p.cedula)     piiRows.push(`<div class="pii-row"><i class="ri-user-line"></i> C.I. ${p.cedula}</div>`);
    if (p.birth_date) piiRows.push(`<div class="pii-row"><i class="ri-cake-2-line"></i> ${p.birth_date}</div>`);
    const piiSection = piiRows.length
        ? `<div class="modal-pii-section">${piiRows.join('')}</div>`
        : '';

    const sparklineHtml = (data.ranking_history && data.ranking_history.length > 1)
        ? `<div class="modal-sparkline-wrap"><canvas id="rankingSparkline"></canvas></div>`
        : '';

    const historyRows = history.length > 0 ? history.map(h => {
        const resClass = h.result === 'W' ? 'win' : h.result === 'L' ? 'loss' : '';
        const resLabel = h.result === 'W' ? 'G' : h.result === 'L' ? 'P' : h.result || '?';
        const refIcon = h.is_refuerzo ? `<span class="ref-badge" title="Refuerzo">💪</span>` : '';
        const tempCat = [h.season, h.category_match].filter(Boolean).join(' · ');
        const clubChip = h.club ? `<span class="hist-club">${h.club}</span>` : '';
        const vsClubChip = h.vs_club ? `<span class="hist-vs-club">${h.vs_club}</span>` : '';
        const rankAfter = (h.ranking_after !== null && h.ranking_after !== undefined)
            ? `<span class="hist-rank-after">${Number(h.ranking_after).toFixed(2)}</span>` : '';
        const partner = h.partner_name ? `<small class="hist-partner">+ ${h.partner_name}</small>` : '';
        return `
        <div class="history-row-pmh ${h.is_refuerzo ? 'is-refuerzo' : ''}">
            <span class="hist-jor">${h.jornada || '—'} ${refIcon}</span>
            <span class="hist-temp">${tempCat || '—'}</span>
            ${clubChip}
            <span class="hist-opponent">${h.opponent_name || '—'} ${partner}</span>
            ${vsClubChip}
            <span class="hist-score">${h.score || '—'}</span>
            ${rankAfter}
            <span class="history-result ${resClass}">${resLabel}</span>
        </div>`;
    }).join('') : '<p class="text-muted" style="padding:.5rem 0">Sin historial disponible. Ejecuta un Crawl para obtener datos.</p>';

    return `
    <div class="modal-player-header">
        ${avatarHtml}
        <div class="modal-player-info">
            <h2 class="modal-player-name">${p.name || 'Jugador'} ${estadoBadge}</h2>
            <p class="modal-player-sub">${teamName}${cat ? ' · ' + cat : ''}${p.club_acronym ? ' · ' + p.club_acronym : ''}</p>
            ${chipsHtml}
        </div>
    </div>

    ${piiSection}

    <div class="modal-stats-grid">
        <div class="modal-stat">
            <span class="modal-stat-value">${ranking} ${deltaTxt}</span>
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
        ${s.modalidades !== null && s.modalidades !== undefined ? `
        <div class="modal-stat">
            <span class="modal-stat-value">${s.modalidades}</span>
            <span class="modal-stat-label">Modalidades</span>
        </div>` : ''}
    </div>

    ${sparklineHtml}

    <div class="modal-history-section">
        <div class="modal-history-header">
            <h4 class="modal-section-title"><i class="ri-history-line"></i> Historial</h4>
            <label class="ref-toggle">
                <input type="checkbox" id="refuerzosToggle"> Solo refuerzos
            </label>
        </div>
        <div class="modal-history-list" id="modalHistoryList">${historyRows}</div>
    </div>`;
}

let _rankingChart = null;
function renderRankingSparkline(history) {
    const canvas = document.getElementById('rankingSparkline');
    if (!canvas || !history || history.length < 2) return;
    if (_rankingChart) { try { _rankingChart.destroy(); } catch (_) {} }
    const labels = history.map(h => h.jornada);
    const values = history.map(h => h.ranking);
    _rankingChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: values,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59,130,246,0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 5,
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                y: { grid: { color: 'rgba(148,163,184,0.1)' }, ticks: { color: '#94a3b8' } }
            }
        }
    });
}

function wireRefuerzosToggle() {
    const cb = document.getElementById('refuerzosToggle');
    const list = document.getElementById('modalHistoryList');
    if (!cb || !list) return;
    cb.addEventListener('change', () => {
        const onlyRef = cb.checked;
        list.querySelectorAll('.history-row-pmh').forEach(row => {
            const isRef = row.classList.contains('is-refuerzo');
            row.style.display = (onlyRef && !isRef) ? 'none' : '';
        });
    });
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

            const groupTabs = document.getElementById('groupTabs');
            if (!cat) {
                // Tab "Todas" → ocultar grupos, mostrar todos los equipos por puntos
                if (groupTabs) groupTabs.style.display = 'none';
                fetchTeamRankings(null);
            } else {
                fetchGroupsForCategory(cat);
            }
        });
    });
}

async function fetchGroupsForCategory(cat) {
    const container = document.getElementById('standingsTable');
    const groupTabsWrap = document.getElementById('groupTabs');
    const groupTabsList = document.getElementById('groupTabsList');

    container.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const res = await fetch(`${API_BASE}/api/groups?categoria=${encodeURIComponent(cat)}`);
        const data = await res.json();
        const groups = data.groups || [];

        if (groups.length === 0) {
            if (groupTabsWrap) groupTabsWrap.style.display = 'none';
            container.innerHTML = '<p class="empty-state-msg">No hay grupos registrados para esta categoría. Ejecuta <strong>Actualizar Grupo</strong>.</p>';
            return;
        }

        // Renderizar sub-tabs de grupos
        groupTabsList.innerHTML = groups.map((g, i) =>
            `<button class="group-tab ${i === 0 ? 'active' : ''}"
                     data-group-id="${g.id}"
                     data-group-name="${g.name}"
                     onclick="selectGroupTab(this, ${g.id}, '${g.name}')">
                Grupo ${g.grupo_num}
             </button>`
        ).join('');
        groupTabsWrap.style.display = 'block';

        // Activar Grupo 1 automáticamente
        fetchGroupDetail(groups[0].id, groups[0].name);

    } catch (e) {
        container.innerHTML = '<p class="empty-state-msg">Error al cargar grupos.</p>';
        console.error('Error fetchGroupsForCategory:', e);
    }
}

function selectGroupTab(btn, groupId, groupName) {
    document.querySelectorAll('#groupTabsList .group-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    fetchGroupDetail(groupId, groupName);
}

async function fetchGroupDetail(groupId, groupName) {
    const container = document.getElementById('standingsTable');
    container.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const [standRes, fixRes] = await Promise.all([
            fetch(`${API_BASE}/api/standings?group_id=${groupId}`),
            fetch(`${API_BASE}/api/group/${groupId}/fixtures`),
        ]);
        const standData = await standRes.json();
        const fixData   = await fixRes.json();

        const standings = (standData.standings || []).sort((a, b) => (a.position ?? 99) - (b.position ?? 99));
        const fixtures  = fixData.fixtures || [];

        // ── Tabla de posiciones ──
        const standRows = standings.map((s, i) => {
            const isOwn = s.team_cta_id === (ownTeamId || 7361);
            const winRate = s.played > 0 ? Math.round((s.won / s.played) * 100) : 0;
            const srJson  = `{position:${s.position ?? (i+1)},points:${s.points ?? 0},played:${s.played ?? 0},won:${s.won ?? 0},lost:${s.lost ?? 0},sets_won:${s.sets_won ?? 0},sets_lost:${s.sets_lost ?? 0},categoria_name:'${(s.categoria_name || '').replace(/'/g, "\\'")}'}`;
            return `
            <tr class="${isOwn ? 'own-team' : ''} clickable" onclick="showTeamDetailView(${s.team_cta_id}, '${(s.team_name || '').replace(/'/g, "\\'")}', ${srJson})">
                <td class="pos-cell">${s.position ?? (i + 1)}</td>
                <td class="team-cell">
                    ${expandTeamName(s.team_name) || '?'}
                    ${isOwn ? '<span class="own-badge">TÚ</span>' : ''}
                </td>
                <td>${s.played ?? '-'}</td>
                <td><strong>${s.won ?? '-'}</strong></td>
                <td>${s.lost ?? '-'}</td>
                <td>${s.sets_won ?? '-'}</td>
                <td>${s.sets_lost ?? '-'}</td>
                <td>${winRate}%</td>
                <td class="pts-cell"><strong>${s.points ?? '-'}</strong></td>
            </tr>`;
        }).join('');

        const standHtml = standings.length > 0 ? `
        <div class="table-section">
            <div class="table-header-actions">
                <h3 style="margin:0;">Posiciones — ${groupName}</h3>
                <button class="share-btn" onclick="shareGroupWhatsApp('${groupName}')">
                    <i class="ri-share-forward-line"></i> Compartir
                </button>
            </div>
            <table class="standings-table">
                <thead>
                    <tr>
                        <th>#</th><th>Equipo</th>
                        <th title="Partidos Jugados">PJ</th>
                        <th title="Partidos Ganados">PG</th>
                        <th title="Partidos Perdidos">PP</th>
                        <th title="Sets Ganados">SG</th>
                        <th title="Sets Perdidos">SP</th>
                        <th title="% Victorias">%V</th>
                        <th title="Puntos">Pts</th>
                    </tr>
                </thead>
                <tbody>${standRows}</tbody>
            </table>
        </div>` : '<p class="empty-state-msg">Sin datos de posiciones para este grupo. Ejecuta <strong>Actualizar Grupo</strong>.</p>';

        // ── Calendario ──
        let fixHtml = '';
        if (fixtures.length > 0) {
            // Agrupar por jornada
            const byJornada = {};
            fixtures.forEach(f => {
                const key = f.raw_detail?.jornada || 'J?';
                if (!byJornada[key]) byJornada[key] = [];
                byJornada[key].push(f);
            });

            const ownId = ownTeamId || 7361;
            const jornadas = Object.entries(byJornada).map(([jor, matches]) => {
                const filas = matches.map(f => {
                    const isHome = f.home_cta_id === ownId;
                    const isAway = f.away_cta_id === ownId;
                    let resultBadge = '';
                    if (f.home_score !== null && f.away_score !== null && f.home_score !== '' && f.away_score !== '') {
                        const hs = parseInt(f.home_score), as_ = parseInt(f.away_score);
                        const won = (isHome && hs > as_) || (isAway && as_ > hs);
                        const lost = (isHome && hs < as_) || (isAway && as_ < hs);
                        const cls = won ? 'result-badge win' : (lost ? 'result-badge loss' : 'result-badge draw');
                        resultBadge = `<span class="${cls}">${f.home_score} - ${f.away_score}</span>`;
                    } else {
                        resultBadge = '<span class="result-badge pending">Pendiente</span>';
                    }
                    const sede = f.raw_detail?.sede || '';
                    const hora = f.raw_detail?.time || '';
                    return `
                    <div class="fixture-row ${isHome || isAway ? 'own-fixture' : ''}" onclick="openMatchDetailModal(${f.id})">
                        <span class="fixture-home">${expandTeamName(f.home_team) || f.home_team}</span>
                        <span class="fixture-vs">vs</span>
                        <span class="fixture-away">${expandTeamName(f.away_team) || f.away_team}</span>
                        <div class="fixture-meta">
                            ${hora ? `<span class="fixture-time"><i class="ri-time-line"></i> ${hora}</span>` : ''}
                            ${sede ? `<span class="fixture-sede"><i class="ri-map-pin-line"></i> ${sede}</span>` : ''}
                        </div>
                        ${resultBadge}
                    </div>`;
                }).join('');

                // Tomar fecha del primer match de la jornada
                const firstDate = matches[0]?.match_date || '';
                const headerLabel = firstDate ? `${jor} · ${firstDate}` : jor;
                return `
                <div class="jornada-block">
                    <div class="jornada-header">${headerLabel}</div>
                    ${filas}
                </div>`;
            }).join('');

            fixHtml = `
            <div class="fixtures-section">
                <h3 class="fixtures-title">Calendario — ${groupName}</h3>
                ${jornadas}
            </div>`;
        }

        container.innerHTML = `<div class="classification-wrapper">${standHtml}${fixHtml}</div>`;

    } catch (e) {
        container.innerHTML = '<p class="empty-state-msg">Error al cargar detalle del grupo.</p>';
        console.error('Error fetchGroupDetail:', e);
    }
}

function shareGroupWhatsApp(groupName) {
    const table = document.querySelector('.standings-table');
    if (!table) return;
    const rows = [];
    rows.push(`🎾 POSICIONES ${groupName} — CTA TENNIS\n`);
    rows.push('─'.repeat(40));
    table.querySelectorAll('tbody tr').forEach(row => {
        const tds = row.querySelectorAll('td');
        const pos   = tds[0]?.textContent?.trim() || '';
        const team  = tds[1]?.textContent?.replace(/TÚ/g, '').trim() || '';
        const pts   = tds[8]?.textContent?.trim() || '-';
        const won   = tds[3]?.textContent?.trim() || '-';
        const lost  = tds[4]?.textContent?.trim() || '-';
        rows.push(`${pos}. ${team.padEnd(25)} ${pts} pts (${won}-${lost})`);
    });
    rows.push('─'.repeat(40));
    rows.push(`📅 ${new Date().toLocaleString('es-VE')}`);
    rows.push('#JDMRules #CTAMonitor');
    window.open(`https://wa.me/?text=${encodeURIComponent(rows.join('\n'))}`, '_blank');
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
            const srJson2  = `{position:${s.position ?? (i+1)},points:${s.points ?? 0},played:${s.played ?? 0},won:${s.won ?? 0},lost:${s.lost ?? 0},sets_won:${s.sets_won ?? 0},sets_lost:${s.sets_lost ?? 0},categoria_name:'${(s.categoria_name || '').replace(/'/g, "\\'")}'}`;
            return `
            <tr class="${isOwn ? 'own-team' : ''} clickable" onclick="showTeamDetailView(${s.team_cta_id}, '${(s.team_name || '').replace(/'/g, "\\'")}', ${srJson2})">
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

// ─────────────────────────────────────────────
// VISTA: CLASIFICACIÓN DE EQUIPOS
// ─────────────────────────────────────────────
async function fetchTeamRankings(categoria = null) {
    const container = document.getElementById('standingsTable');
    container.innerHTML = '<div class="loading-spinner"></div>';

    const url = categoria
        ? `${API_BASE}/api/standings?categoria=${encodeURIComponent(categoria)}`
        : `${API_BASE}/api/standings`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        const standings = (data.standings || []).sort((a, b) => (b.points || 0) - (a.points || 0));

        if (standings.length === 0) {
            container.innerHTML =
                '<p class="text-muted" style="padding:1.5rem">Sin datos de posiciones. Ejecuta una sincronización.</p>';
            return;
        }

        // Tabla completa
        const showCat = !categoria;
        const rows = standings.map((s, i) => {
            const isOwn = s.team_cta_id === (ownTeamId || 7361);
            const catBadge = showCat && s.categoria_name
                ? `<span class="cat-badge cat-${s.categoria_name}">${s.categoria_name}</span>` : '';
            const winRate = s.played > 0 ? Math.round((s.won / s.played) * 100) : 0;
            const srJson3  = `{position:${i+1},points:${s.points ?? 0},played:${s.played ?? 0},won:${s.won ?? 0},lost:${s.lost ?? 0},sets_won:${s.sets_won ?? 0},sets_lost:${s.sets_lost ?? 0},categoria_name:'${(s.categoria_name || '').replace(/'/g, "\\'")}'}`;

            return `
            <tr class="${isOwn ? 'own-team' : ''} clickable" onclick="showTeamDetailView(${s.team_cta_id}, '${(s.team_name || '').replace(/'/g, "\\'")}', ${srJson3})">
                <td class="pos-cell">${i + 1}</td>
                <td class="team-cell">
                    ${catBadge}${expandTeamName(s.team_name) || '?'}
                    ${isOwn ? '<span class="own-badge">TÚ</span>' : ''}
                </td>
                <td>${s.played ?? '-'}</td>
                <td><strong>${s.won ?? '-'}</strong></td>
                <td>${s.lost ?? '-'}</td>
                <td>${s.sets_won ?? '-'}</td>
                <td>${s.sets_lost ?? '-'}</td>
                <td>${winRate}%</td>
                <td class="pts-cell"><strong>${s.points ?? '-'}</strong></td>
            </tr>`;
        }).join('');

        container.innerHTML = `
        <div class="classification-wrapper">
            <div class="table-section">
                <div class="table-header-actions">
                    <h3 style="margin: 0;">Tabla Completa</h3>
                    <button class="share-btn" onclick="shareClassificationWhatsApp()">
                        <i class="ri-share-forward-line"></i> Compartir
                    </button>
                </div>
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
                            <th title="% Victorias">%V</th>
                            <th title="Puntos">Pts</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>`;

    } catch (e) {
        container.innerHTML = '<p class="text-muted" style="padding:1.5rem">Error al cargar clasificación.</p>';
        console.error("Error al cargar clasificación:", e);
    }
}

function shareClassificationWhatsApp() {
    const table = document.querySelector('.standings-table');
    if (!table) return;

    const rows = [];
    rows.push('🎾 CLASIFICACIÓN CTA TENNIS\n');
    rows.push('─'.repeat(40));

    const cells = table.querySelectorAll('tbody tr');
    cells.slice(0, 10).forEach((row) => {
        const tds = row.querySelectorAll('td');
        const pos    = tds[0]?.textContent?.trim() || '';
        const team   = tds[1]?.textContent?.replace(/TÚ|[0-9A-Z]{2}[FM]/g, '').trim() || '';
        const points = tds[8]?.textContent?.trim() || '-';
        const won    = tds[3]?.textContent?.trim() || '-';
        const lost   = tds[4]?.textContent?.trim() || '-';
        rows.push(`${pos}. ${team.padEnd(25)} ${points} pts (${won}-${lost})`);
    });

    rows.push('─'.repeat(40));
    rows.push(`📅 Actualizado: ${new Date().toLocaleString('es-VE')}`);
    rows.push('#JDMRules #CTAMonitor');

    const encoded = encodeURIComponent(rows.join('\n'));
    window.open(`https://wa.me/?text=${encoded}`, '_blank');
}
