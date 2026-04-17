// ═══════════════════════════════════════════════════════
//  CTA Monitor — app.js
//  Router SPA + handlers de todas las vistas
// ═══════════════════════════════════════════════════════

let performanceChartInstance = null;
let cachedTeams = [];      // Cache global de equipos para el buscador
let ownTeamPlayers = [];   // Cache de jugadores propios

document.addEventListener("DOMContentLoaded", () => {
    // Conectar navegación
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            navigateTo(item.dataset.view);
        });
    });

    // Carga inicial
    fetchDashboardData();
    fetchLastSync();
    initSearch();
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

    // Precarga equipos en segundo plano
    try {
        const res = await fetch('/api/teams');
        const data = await res.json();
        cachedTeams = data.teams || [];
    } catch (e) { /* silencioso, el buscador simplemente no mostrará equipos */ }

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

    // Filtrar equipos (excluye el propio equipo del resultado de rivals)
    const teamResults = cachedTeams
        .filter(t => t.name.toLowerCase().includes(q))
        .slice(0, 8);

    const bar = document.getElementById('searchBar');
    if (!bar) return;

    let html = '';

    if (teamResults.length === 0) {
        html = `<div class="search-empty">Sin resultados para "<strong>${query}</strong>"</div>`;
    } else {
        html += '<div class="search-group-label">Equipos</div>';
        teamResults.forEach(t => {
            const isOwn = t.is_own_team;
            html += `
            <div class="search-result-item" data-id="${t.cta_id}" data-own="${isOwn}" onclick="searchSelectTeam(${t.cta_id}, '${t.name.replace(/'/g,"\\'")}', ${isOwn})">
                <i class="ri-${isOwn ? 'home' : 'team'}-line search-result-icon"></i>
                <div class="search-result-text">
                    <div class="search-result-name">${highlightMatch(t.name, query)}</div>
                    <div class="search-result-sub">${isOwn ? 'Tu equipo' : 'Rival · ID ' + t.cta_id}</div>
                </div>
                <span class="search-result-action">${isOwn ? 'Ver equipo →' : 'Predecir draw →'}</span>
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
    else if (viewId === 'posiciones') fetchStandings();
    else if (viewId === 'predictor') fetchRivalTeams();
}

// ─────────────────────────────────────────────
// SINCRONIZACIÓN
// ─────────────────────────────────────────────
async function syncData() {
    const btn = document.getElementById('syncBtn');
    const status = document.getElementById('syncStatus');

    btn.disabled = true;
    btn.innerHTML = '<i class="ri-loader-4-line spin"></i> Sincronizando...';
    status.textContent = '';
    status.className = 'sync-status';

    try {
        const res = await fetch('/api/sync', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            status.textContent = '✓ Sincronizado';
            status.className = 'sync-status ok';
            // Refrescar la vista actual con datos nuevos
            const currentViewId = document.querySelector('.view-section.active')?.id?.replace('view-', '');
            if (currentViewId) navigateTo(currentViewId);
            fetchLastSync();
        } else {
            status.textContent = '✗ ' + (data.message || 'Error desconocido');
            status.className = 'sync-status error';
        }
    } catch (e) {
        status.textContent = '✗ Sin conexión con el servidor';
        status.className = 'sync-status error';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="ri-refresh-line"></i> Sincronizar';
        setTimeout(() => {
            if (status.className !== 'sync-status muted') {
                status.textContent = '';
                status.className = 'sync-status';
            }
            fetchLastSync();
        }, 5000);
    }
}

async function groupSync() {
    const btn = document.getElementById('groupBtn');
    const status = document.getElementById('syncStatus');

    btn.disabled = true;
    btn.innerHTML = '<i class="ri-loader-4-line spin"></i> Actualizando...';
    status.textContent = 'Actualizando grupo...';
    status.className = 'sync-status muted';

    try {
        const res = await fetch('/api/group', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            status.textContent = '✓ Grupo actualizado';
            status.className = 'sync-status ok';
            const currentViewId = document.querySelector('.view-section.active')?.id?.replace('view-', '');
            if (currentViewId) navigateTo(currentViewId);
            fetchLastSync();
        } else {
            status.textContent = '✗ ' + (data.message || 'Error desconocido');
            status.className = 'sync-status error';
        }
    } catch (e) {
        status.textContent = '✗ Sin conexión con el servidor';
        status.className = 'sync-status error';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="ri-calendar-check-line"></i> Actualizar Grupo';
        setTimeout(() => {
            if (status.className !== 'sync-status muted') {
                status.textContent = '';
                status.className = 'sync-status';
            }
            fetchLastSync();
        }, 5000);
    }
}

async function crawlFull() {
    const btn = document.getElementById('crawlBtn');
    const status = document.getElementById('syncStatus');

    btn.disabled = true;
    btn.innerHTML = '<i class="ri-loader-4-line spin"></i> Descargando...';
    status.textContent = 'Crawl en progreso (puede tardar ~5 min)...';
    status.className = 'sync-status muted';

    try {
        const res = await fetch('/api/crawl', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            status.textContent = '✓ Crawl completo finalizado';
            status.className = 'sync-status ok';
            const currentViewId = document.querySelector('.view-section.active')?.id?.replace('view-', '');
            if (currentViewId) navigateTo(currentViewId);
            fetchLastSync();
        } else {
            status.textContent = '✗ ' + (data.message || 'Error desconocido');
            status.className = 'sync-status error';
        }
    } catch (e) {
        status.textContent = '✗ Sin conexión con el servidor';
        status.className = 'sync-status error';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="ri-database-2-line"></i> Crawl Completo';
        setTimeout(() => {
            if (status.className !== 'sync-status muted') {
                status.textContent = '';
                status.className = 'sync-status';
            }
            fetchLastSync();
        }, 6000);
    }
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
        const res = await fetch('/api/last-sync');
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
            fetch('/api/last-sync'),
            fetch('/api/dashboard'),
            fetch('/api/teams'),
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
        const res = await fetch('/api/dashboard');
        const data = await res.json();

        if (data.error) {
            console.error("Error de API:", data.error);
            document.getElementById('matchesList').innerHTML =
                '<p class="text-muted">Sin datos. Ejecuta una sincronización primero.</p>';
            return;
        }

        document.getElementById('userNameLabel').textContent = data.team_name || 'Mi Equipo';

        if (data.data_missing) {
            // Sin entrada en standings — mostrar estado real en vez de ceros falsos
            document.getElementById('valPosition').textContent = '–';
            document.querySelector('#valPosition').closest('.kpi-card')
                .querySelector('.kpi-footer .trend').innerHTML =
                '<i class="ri-information-line"></i> Sin datos de tabla';

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
                <div class="match-opp">${m.opponent || 'Rival'}</div>
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
        dataPoints.push(50, 60, 55, 75, 70, 90);
        labels.push("Ene", "Feb", "Mar", "Abr", "May", "Jun");
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
    const ownTeamId = 7361;
    const roster = document.getElementById('playerRoster');
    const quickStats = document.getElementById('teamQuickStats');
    roster.innerHTML = '<div class="loading-spinner"></div>';
    quickStats.innerHTML = '<div class="loading-inline"></div>';

    try {
        const [teamRes, dashRes] = await Promise.all([
            fetch(`/api/team/${ownTeamId}`),
            fetch('/api/dashboard')
        ]);
        const teamData = await teamRes.json();
        const dash = await dashRes.json();

        document.getElementById('teamNameHeading').textContent =
            teamData.team?.name || 'Mi Equipo';
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
        <div class="player-row">
            <div class="player-avatar"><i class="ri-user-3-line"></i></div>
            <div class="player-name">${p.name}</div>
            <div class="player-stat-pill">Ranking: <strong>${ranking}</strong></div>
            <div class="player-stat-pill">Partidos: <strong>${mw}V / ${ml}D</strong></div>
            <div class="player-stat-pill">Sets: <strong>${sw} / ${sl}</strong></div>
        </div>`;
    }).join('');

    container.innerHTML = rows;
}

// ─────────────────────────────────────────────
// VISTA: POSICIONES
// ─────────────────────────────────────────────
async function fetchStandings() {
    const container = document.getElementById('standingsTable');
    container.innerHTML = '<div class="loading-spinner"></div>';

    try {
        const res = await fetch('/api/standings');
        const data = await res.json();
        const standings = data.standings || [];

        if (standings.length === 0) {
            container.innerHTML =
                '<p class="text-muted" style="padding:1.5rem">Sin datos de posiciones. Ejecuta una sincronización.</p>';
            return;
        }

        const ownTeamId = 7361;

        const rows = standings.map((s, i) => {
            const isOwn = s.team_cta_id === ownTeamId;
            return `
            <tr class="${isOwn ? 'own-team' : ''}">
                <td class="pos-cell">${s.position ?? (i + 1)}</td>
                <td class="team-cell">
                    ${s.team_name || '?'}
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
        const res = await fetch('/api/teams');
        const data = await res.json();
        const rivals = (data.teams || []).filter(t => !t.is_own_team);

        select.innerHTML = '<option value="">-- Selecciona un rival --</option>';
        rivals.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.cta_id;
            opt.textContent = t.name;
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

    const rivalName = select.options[select.selectedIndex].text;
    content.innerHTML = `
        <div style="text-align:center;padding:2rem">
            <div class="loading-spinner" style="margin:0 auto 1rem"></div>
            <p class="text-muted">Calculando alineación óptima contra <strong>${rivalName}</strong>...</p>
        </div>`;

    try {
        const res = await fetch(`/api/lineup-predictor/${rivalId}`);
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
