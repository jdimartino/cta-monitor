from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import config
import database
import rival_analyzer
import draw_predictor

app = FastAPI(title="CTA Monitor API")

# Add CORS so our dev setup can connect
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

@app.on_event("startup")
def startup_event():
    database.init_db()

@app.get("/api/dashboard")
def get_dashboard_summary():
    """Provides high-level stats for the KPI cards and chart."""
    own_team = database.get_own_team()
    if not own_team:
        return {"error": "Own team not initialized. Run sync first."}
    
    standings = database.get_latest_standings()
    position = None
    points = None
    total_played = 0
    total_won = 0
    has_standings = False

    for s in standings:
        if s["team_cta_id"] == own_team["cta_id"]:
            position   = s.get("position")
            points     = s.get("points")
            total_played = s.get("played", 0) or 0
            total_won    = s.get("won", 0) or 0
            has_standings = True
            break

    win_rate = round((total_won / total_played * 100), 1) if total_played > 0 else None

    # Contar partidos programados aunque no haya standings
    all_matches = database.get_team_matches(own_team["cta_id"], limit=100)
    scheduled   = [m for m in all_matches if m.get("status") == "scheduled"]
    played_matches = [m for m in all_matches if m.get("status") != "scheduled"]

    recent_matches = rival_analyzer.get_recent_matches(own_team["cta_id"], limit=8)

    return {
        "team_name":      own_team["name"],
        "position":       position,
        "points":         points,
        "win_rate":       win_rate,
        "matches_played": total_played,
        "scheduled_count": len(scheduled),
        "data_missing":   not has_standings,
        "recent_matches": recent_matches,
    }

@app.get("/api/standings")
def get_standings():
    """Full standings table."""
    standings = database.get_latest_standings()
    return {"standings": standings}


@app.get("/api/teams")
def get_all_teams():
    """All teams in the league (for rival selector)."""
    teams = database.get_all_teams()
    return {"teams": teams}


@app.get("/api/last-sync")
def get_last_sync():
    """Timestamp of the last data sync."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(scraped_at) as ts FROM standings"
        ).fetchone()
    return {"last_sync": row["ts"] if row else None}


@app.post("/api/sync")
def trigger_sync():
    """Trigger a data sync (standings + own team)."""
    try:
        script = str(Path(__file__).parent / "main.py")
        result = subprocess.run(
            [sys.executable, script, "sync"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path(__file__).parent),
        )
        success = result.returncode == 0
        return {
            "success": success,
            "message": "Sincronización completada" if success else "Error en sincronización",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado (>2 min)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/group")
def trigger_group():
    """Trigger a fast group crawl (standings + fixtures only)."""
    try:
        script = str(Path(__file__).parent / "main.py")
        result = subprocess.run(
            [sys.executable, script, "group"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).parent),
        )
        success = result.returncode == 0
        return {
            "success": success,
            "message": "Grupo actualizado" if success else "Error al actualizar grupo",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado (>1 min)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/crawl")
def trigger_crawl():
    """Trigger a full crawl (all teams + all players)."""
    try:
        script = str(Path(__file__).parent / "main.py")
        result = subprocess.run(
            [sys.executable, script, "crawl", "--full"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).parent),
        )
        success = result.returncode == 0
        return {
            "success": success,
            "message": "Crawl completo finalizado" if success else "Error en crawl",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado (>10 min)"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/team/{cta_id}")
def get_team_details(cta_id: int):
    """Team details including players."""
    team = database.get_team(cta_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
        
    players = database.get_team_players(cta_id)
    # Add stats to players
    player_list = []
    for p in players:
        stats = database.get_latest_player_stats(p["cta_id"])
        player_list.append({
            "name": p["name"],
            "cta_id": p["cta_id"],
            "ranking": stats.get("ranking") if stats else None,
            "stats": stats
        })
        
    return {
        "team": team,
        "players": player_list
    }

@app.get("/api/lineup-predictor/{rival_cta_id}")
def predict_lineup(rival_cta_id: int):
    """Predict draw."""
    try:
        report = draw_predictor.suggest_own_lineup(rival_cta_id)
        predict_rival = draw_predictor.predict_rival_lineup(rival_cta_id)
        return {
            "rival_predicted": predict_rival,
            "our_suggestions": report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
