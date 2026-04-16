from __future__ import annotations

import logging
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
    # Find our position
    position = "-"
    points = 0
    total_played = 0
    total_won = 0
    for s in standings:
        if s["team_cta_id"] == own_team["cta_id"]:
            position = s.get("position", "-")
            points = s.get("points", 0)
            total_played = s.get("played", 0)
            total_won = s.get("won", 0)
            break
            
    win_rate = round((total_won / total_played * 100), 1) if total_played > 0 else 0
    
    recent_matches = rival_analyzer.get_recent_matches(own_team["cta_id"], limit=5)
    
    return {
        "team_name": own_team["name"],
        "position": position,
        "points": points,
        "win_rate": win_rate,
        "matches_played": total_played,
        "recent_matches": recent_matches
    }

@app.get("/api/standings")
def get_standings():
    """Full standings table."""
    standings = database.get_latest_standings()
    return {"standings": standings}

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
