document.addEventListener("DOMContentLoaded", () => {
    fetchDashboardData();
});

async function fetchDashboardData() {
    try {
        const response = await fetch('/api/dashboard');
        const data = await response.json();

        if (data.error) {
            console.error("Error de API:", data.error);
            return;
        }

        // Update User Profile
        document.getElementById('userNameLabel').textContent = data.team_name;

        // Update KPIs
        document.getElementById('valPosition').textContent = `#${data.position}`;
        document.getElementById('valPoints').textContent = data.points;
        document.getElementById('valWinRate').textContent = `${data.win_rate}%`;
        document.getElementById('valMatchesPlayed').textContent = `${data.matches_played} Partidos Jugados`;

        // Render Recent Matches
        renderMatches(data.recent_matches);

        // Render Chart
        renderChart(data.recent_matches);

    } catch (e) {
        console.error("Error al cargar el dashboard:", e);
    }
}

function renderMatches(matches) {
    const container = document.getElementById('matchesList');
    container.innerHTML = '';
    
    if(!matches || matches.length === 0) {
        container.innerHTML = '<p class="text-muted">Sin partidos recientes.</p>';
        return;
    }

    matches.forEach(m => {
        let resClass = 'pending';
        let resText = '-';
        if(m.result === 'W') { resClass = 'win'; resText = 'W'; }
        else if(m.result === 'L') { resClass = 'loss'; resText = 'L'; }

        const div = document.createElement('div');
        div.className = 'match-item';
        div.innerHTML = `
            <div class="match-result-badge ${resClass}">${resText}</div>
            <div class="match-info">
                <div class="match-opp">${m.opponent}</div>
                <div class="match-date">${m.date || 'Fecha Pendiente'}</div>
            </div>
            <div class="match-score">${m.score || ''}</div>
        `;
        container.appendChild(div);
    });
}

function renderChart(matches) {
    const ctx = document.getElementById('performanceChart').getContext('2d');
    
    // We will map Recent matches (oldest to newest) to a cumulative point chart or just win/loss binary
    // Since matches is sorted newest first, reverse it
    const reversed = [...matches].reverse();
    const labels = reversed.map(m => m.date || 'Unknown');
    
    let currentScore = 50; // Starting baseline
    const dataPoints = [];
    reversed.forEach(m => {
        if(m.result === 'W') currentScore += 10;
        else if(m.result === 'L') currentScore -= 5;
        dataPoints.push(currentScore);
    });

    if(dataPoints.length === 0) {
        dataPoints.push(50, 60, 55, 75, 70, 90); // Dummy data if empty
        labels.push("Ene", "Feb", "Mar", "Abr", "May", "Jun");
    }

    // Gradient definition
    let gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(0, 228, 255, 0.4)');   
    gradient.addColorStop(1, 'rgba(0, 228, 255, 0.0)');

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
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
                tension: 0.4 // Smooth curves
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    display: false, // hide Y axis for cleaner look
                    min: Math.min(...dataPoints) - 10,
                    max: Math.max(...dataPoints) + 10
                },
                x: {
                    grid: {
                        color: 'rgba(255,255,255,0.05)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#64748B'
                    }
                }
            }
        }
    });
}

async function runPredictor(rivalId) {
    const content = document.getElementById('predictorContent');
    content.innerHTML = '<div class="loading-spinner">Calculando alineación óptima...</div>';
    
    try {
        const response = await fetch(`/api/lineup-predictor/${rivalId}`);
        const data = await response.json();

        if(!data.our_suggestions || data.our_suggestions.length === 0) {
            content.innerHTML = '<p>Sin datos para predecir.</p>';
            return;
        }

        let html = '';
        data.our_suggestions.forEach(s => {
            const p1 = s.player ? s.player.name : '?';
            const vsName = s.vs ? s.vs : 'Rival';
            
            if(s.type === 'singles') {
                html += `
                <div class="matchup-row">
                    <div class="matchup-pos">S${s.position}</div>
                    <div class="player-box">
                        <span>${p1}</span>
                    </div>
                    <div class="vs-badge">VS</div>
                    <div class="player-box">
                        <span style="color:#94A3B8">${vsName}</span>
                    </div>
                </div>
                `;
            } else {
                const partner = s.partner ? s.partner.name : '?';
                html += `
                <div class="matchup-row">
                    <div class="matchup-pos">Dbl</div>
                    <div class="player-box">
                        <span>${p1} & ${partner}</span>
                    </div>
                </div>
                `;
            }
        });
        
        content.innerHTML = html;
        
    } catch(e) {
        content.innerHTML = `<p class="text-muted">Error al calcular: ${e.message}</p>`;
    }
}
