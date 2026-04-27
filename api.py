from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

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

    # League metadata
    league = None
    if own_team.get("league_id"):
        with database.get_connection() as conn:
            row = conn.execute("SELECT * FROM leagues WHERE id=?", (own_team["league_id"],)).fetchone()
            league = dict(row) if row else None

    standings = database.get_latest_standings(own_team.get("league_id"))
    position = None
    points = None
    total_played = 0
    total_won = 0
    has_standings = False
    total_teams = len(standings)

    for s in standings:
        if s["team_cta_id"] == own_team["cta_id"]:
            position     = s.get("position")
            points       = s.get("points")
            total_played = s.get("played", 0) or 0
            total_won    = s.get("won", 0) or 0
            has_standings = True
            break

    win_rate = round((total_won / total_played * 100), 1) if total_played > 0 else None

    all_matches = database.get_team_matches(own_team["cta_id"], limit=100)
    scheduled = [m for m in all_matches if m.get("status") == "scheduled"]

    recent_matches = rival_analyzer.get_recent_matches(own_team["cta_id"], limit=8)

    return {
        "team_name":      own_team["name"],
        "team_cta_id":    own_team["cta_id"],
        "categoria_name": league["categoria_name"] if league else None,
        "liga_id":        league["liga_id"] if league else config.LIGA_ID,
        "position":       position,
        "total_teams":    total_teams,
        "points":         points,
        "win_rate":       win_rate,
        "matches_played": total_played,
        "scheduled_count": len(scheduled),
        "data_missing":   not has_standings,
        "recent_matches": recent_matches,
    }

@app.get("/api/clubs")
def get_clubs():
    """All clubs with their acronym→name mapping."""
    return {"clubs": database.get_all_clubs()}


@app.get("/api/categories")
def get_categories():
    """All known categories for this liga."""
    return {"categories": config.CATEGORIES}


@app.get("/api/standings")
def get_standings(categoria: str = None, group_id: int = None):
    """Full standings table. Filter by ?categoria=6M or ?group_id=1282"""
    if group_id:
        standings = database.get_group_standings(group_id)
        return {"standings": standings}
    league_id = None
    if categoria:
        cat = next((c for c in config.CATEGORIES if c["name"] == categoria), None)
        if cat:
            league = database.get_league(config.LIGA_ID, cat["id"])
            league_id = league["id"] if league else None
    standings = database.get_latest_standings(league_id)
    return {"standings": standings}


@app.get("/api/groups")
def get_groups(categoria: str = None):
    """List groups. Filter by ?categoria=6M"""
    if categoria:
        groups = database.get_groups_by_categoria(categoria)
    else:
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM groups ORDER BY categoria_name, CAST(grupo_num AS INTEGER)"
            ).fetchall()
            groups = [dict(r) for r in rows]
    return {"groups": groups}


@app.get("/api/group/{group_id}/fixtures")
def get_group_fixtures(group_id: int):
    """Fixtures (calendar) for a specific group."""
    fixtures = database.get_group_fixtures(group_id)
    import json as _json
    result = []
    for f in fixtures:
        row = dict(f)
        if row.get("raw_detail"):
            try:
                row["raw_detail"] = _json.loads(row["raw_detail"])
            except Exception:
                pass
        result.append(row)
    return {"fixtures": result}


@app.get("/api/teams")
def get_all_teams(categoria: str = None):
    """All teams. Optionally filter by ?categoria=6M. Includes categoria_name/gender."""
    with database.get_connection() as conn:
        if categoria:
            cat = next((c for c in config.CATEGORIES if c["name"] == categoria), None)
            if cat:
                rows = conn.execute(
                    """SELECT t.*, l.categoria_name, l.gender, l.level
                       FROM teams t LEFT JOIN leagues l ON t.league_id = l.id
                       WHERE l.liga_id=? AND l.categoria_id=?
                       ORDER BY t.name""",
                    (config.LIGA_ID, cat["id"]),
                ).fetchall()
            else:
                rows = []
        else:
            rows = conn.execute(
                """SELECT t.*, l.categoria_name, l.gender, l.level
                   FROM teams t LEFT JOIN leagues l ON t.league_id = l.id
                   ORDER BY l.level, l.gender, t.name"""
            ).fetchall()
    teams = [dict(r) for r in rows]
    return {"teams": teams}


@app.get("/api/last-sync")
def get_last_sync():
    """Timestamp of the last data sync."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(scraped_at) as ts FROM standings"
        ).fetchone()
    return {"last_sync": row["ts"] if row else None}


def _stream_command(cmd: list[str], timeout: int):
    """Generator that runs a subprocess and yields SSE lines."""
    script_dir = str(Path(__file__).parent)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=script_dir,
        )
        # Enforce timeout via a daemon thread that kills the process
        def _kill():
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
        t = threading.Thread(target=_kill, daemon=True)
        t.start()

        for line in proc.stdout:
            clean = line.rstrip()
            if clean:
                yield f"data: {clean}\n\n"

        proc.wait()
        status = "ok" if proc.returncode == 0 else "error"
        yield f"data: __DONE__{status}\n\n"
    except Exception as e:
        yield f"data: ERROR: {e}\n\n"
        yield "data: __DONE__error\n\n"


@app.get("/api/sync/stream")
def sync_stream():
    """SSE stream: sync standings + own team."""
    script = str(Path(__file__).parent / "main.py")
    return StreamingResponse(
        _stream_command([sys.executable, "-u", script, "sync"], timeout=120),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/group/stream")
def group_stream():
    """SSE stream: group crawl (standings + fixtures)."""
    script = str(Path(__file__).parent / "main.py")
    return StreamingResponse(
        _stream_command([sys.executable, "-u", script, "group"], timeout=60),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/crawl/stream")
def crawl_stream():
    """SSE stream: full crawl (all categories + all players)."""
    script = str(Path(__file__).parent / "main.py")
    return StreamingResponse(
        _stream_command([sys.executable, "-u", script, "crawl", "--full"], timeout=10800),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sync")
def trigger_sync():
    """Trigger a data sync (backwards-compat, non-streaming)."""
    script = str(Path(__file__).parent / "main.py")
    try:
        result = subprocess.run(
            [sys.executable, script, "sync"],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(__file__).parent),
        )
        return {"success": result.returncode == 0, "message": "Sincronización completada" if result.returncode == 0 else "Error en sincronización"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/group")
def trigger_group():
    """Trigger a fast group crawl (backwards-compat, non-streaming)."""
    script = str(Path(__file__).parent / "main.py")
    try:
        result = subprocess.run(
            [sys.executable, script, "group"],
            capture_output=True, text=True, timeout=60,
            cwd=str(Path(__file__).parent),
        )
        return {"success": result.returncode == 0, "message": "Grupo actualizado" if result.returncode == 0 else "Error al actualizar grupo"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/crawl")
def trigger_crawl():
    """Trigger a full crawl (backwards-compat, non-streaming)."""
    script = str(Path(__file__).parent / "main.py")
    try:
        result = subprocess.run(
            [sys.executable, script, "crawl", "--full"],
            capture_output=True, text=True, timeout=10800,
            cwd=str(Path(__file__).parent),
        )
        return {"success": result.returncode == 0, "message": "Crawl completo finalizado" if result.returncode == 0 else "Error en crawl"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Tiempo de espera agotado (>10 min)"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/players")
def get_all_players():
    """All players with their team info for search."""
    with database.get_connection() as conn:
        rows = conn.execute(
            """SELECT p.cta_id, p.name, t.name as team_name, t.cta_id as team_cta_id,
                      l.categoria_name, l.gender
               FROM players p
               JOIN teams t ON p.team_id = t.id
               LEFT JOIN leagues l ON t.league_id = l.id
               ORDER BY p.name"""
        ).fetchall()
    return {"players": [dict(r) for r in rows]}


def _compute_sets(history: list) -> tuple[int, int]:
    """Parse scores like '6-4 7-5' from match history → (sets_won, sets_lost)."""
    import re
    sw = sl = 0
    for m in history:
        for part in re.split(r"[,\s]+", m.get("score", "") or ""):
            sm = re.match(r"(\d+)-(\d+)", part)
            if sm:
                a, b = int(sm.group(1)), int(sm.group(2))
                if a > b:
                    sw += 1
                elif b > a:
                    sl += 1
    return sw, sl


def _enrich_stats_from_raw(stats_out: dict) -> dict:
    """Extrae ranking del raw_data JSON cuando el campo estructurado es NULL.
    También deserializa `chips` (almacenado como JSON string) a lista."""
    import re, json as _json

    chips = stats_out.get("chips")
    if isinstance(chips, str) and chips:
        try:
            stats_out["chips"] = _json.loads(chips)
        except Exception:
            pass

    raw = stats_out.get("raw_data")
    if not raw:
        return stats_out
    try:
        raw_dict = _json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return stats_out

    if stats_out.get("ranking") is None:
        # Buscar en la clave que contenga "Rank\d+,\d+" o "Ranking1383,20"
        for v in raw_dict.values():
            m = re.search(r"[Rr]ank(?:ing)?(?: actual)?\s*(\d+(?:[,.]\d+)?)", str(v))
            if m:
                stats_out["ranking"] = m.group(1).replace(",", ".")
                break

    if stats_out.get("matches_won") is None or stats_out.get("matches_lost") is None:
        for v in raw_dict.values():
            m = re.search(r"(\d+)G\s*·\s*(\d+)P", str(v))
            if not m:
                continue
            twu = m.group(1)
            lost = int(m.group(2))
            won = None
            for i in range(1, len(twu)):
                won_candidate = int(twu[-i:])
                total_candidate = int(twu[:-i])
                if total_candidate == won_candidate + lost:
                    won = won_candidate
                    break
            if won is None:
                won = int(twu) if int(twu) >= lost else 0
            stats_out["matches_won"] = won
            stats_out["matches_lost"] = lost
            break

    return stats_out


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
        stats_out = dict(stats) if stats else {}
        # Enriquecer con raw_data si faltan campos estructurados
        stats_out = _enrich_stats_from_raw(stats_out)
        history = None
        if stats_out.get("matches_won") is None:
            history = database.get_player_history(p["cta_id"], limit=200)
            if history:
                stats_out["matches_won"] = sum(1 for m in history if m.get("result") == "W")
                stats_out["matches_lost"] = sum(1 for m in history if m.get("result") == "L")
        if stats_out.get("sets_won") is None:
            if not history:
                history = database.get_player_history(p["cta_id"], limit=200)
            if history:
                sw, sl = _compute_sets(history)
                if sw or sl:
                    stats_out["sets_won"] = sw
                    stats_out["sets_lost"] = sl
        player_list.append({
            "name": p["name"],
            "cta_id": p["cta_id"],
            "ranking": stats_out.get("ranking"),
            "photo_url": p.get("photo_url") if isinstance(p, dict) else (p["photo_url"] if "photo_url" in p.keys() else None),
            "stats": stats_out or None
        })
        
    return {
        "team": team,
        "players": player_list
    }

@app.get("/api/player/{cta_id}")
def get_player_profile(cta_id: int):
    """Full player profile: stats + match history."""
    player = database.get_player(cta_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    stats = database.get_latest_player_stats(cta_id)
    history = database.get_player_history(cta_id, limit=200)
    team = database.get_team_by_player(cta_id)

    stats_out = dict(stats) if stats else {}
    # Enriquecer con raw_data si faltan campos estructurados
    stats_out = _enrich_stats_from_raw(stats_out)
    # If match counts are missing, compute from history
    if history and stats_out.get("matches_won") is None:
        stats_out["matches_won"] = sum(1 for m in history if m.get("result") == "W")
        stats_out["matches_lost"] = sum(1 for m in history if m.get("result") == "L")
    # If set counts are missing, compute from history
    if stats_out.get("sets_won") is None:
        sw, sl = _compute_sets(history)
        if sw or sl:
            stats_out["sets_won"] = sw
            stats_out["sets_lost"] = sl

    return {
        "player": dict(player),
        "stats": stats_out or None,
        "match_history": history,
        "team": dict(team) if team else None,
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


# ─────────────────────────────────────────────
# NEW: data-rich endpoints for redesigned profile
# ─────────────────────────────────────────────
@app.get("/api/player/{cta_id}/ranking-history")
def player_ranking_history(cta_id: int):
    """Ranking evolution per jornada (sparkline source)."""
    player = database.get_player(cta_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return {
        "cta_id": cta_id,
        "history": database.get_player_ranking_history(cta_id),
    }


@app.get("/api/team/{cta_id}/form")
def team_recent_form(cta_id: int, n: int = 5):
    """Recent W/L/D form for the team. Reads stored recent_form (W/L letters
    parsed from the team page) and falls back to computing from match table."""
    team = database.get_team(cta_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    stored = team.get("recent_form")
    letters = list(stored) if stored else []
    return {
        "cta_id": cta_id,
        "form": letters[-n:] if letters else [],
        "raw": stored,
    }


@app.get("/api/team/{cta_id}/captains")
def team_captains(cta_id: int):
    """Captain + sub-captain with contact info if available."""
    team = database.get_team(cta_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    def _player_card(player_id):
        if not player_id:
            return None
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT cta_id, name, photo_url, email, phone FROM players WHERE id=?",
                (player_id,),
            ).fetchone()
        return dict(row) if row else None

    return {
        "cta_id": cta_id,
        "captain":    {"name": team.get("captain_name"),    **(_player_card(team.get("captain_player_id"))    or {})},
        "subcaptain": {"name": team.get("subcaptain_name"), **(_player_card(team.get("subcaptain_player_id")) or {})},
        "protests": {
            "used":  team.get("protests_used"),
            "total": team.get("protests_total"),
        },
    }


@app.get("/api/team/{cta_id}/matches")
def get_team_matches(cta_id: int):
    """All matches (past + upcoming) for a team."""
    team = database.get_team(cta_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    matches = database.get_team_matches(cta_id)
    return {"cta_id": cta_id, "matches": matches}


@app.get("/api/match/{match_id}/details")
def get_match_details(match_id: int):
    """Get match header + rubber details from player_match_history."""
    data = database.get_match_details(match_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return data


@app.get("/api/refuerzos")
def refuerzos(categoria: str = None, limit: int = 200):
    """List refuerzo appearances (a player suiting up for a team that's not
    their own). Optionally filter by category code (e.g. 6M)."""
    sql = """
        SELECT pmh.id, pmh.jornada, pmh.season, pmh.category_match,
               pmh.club AS played_for, pmh.vs_club, pmh.score, pmh.result,
               pmh.opponent_name, pmh.partner_name, pmh.rubber_type,
               p.cta_id AS player_cta_id, p.name AS player_name, p.photo_url,
               t.name AS home_team_name, t.cta_id AS home_team_cta_id
        FROM player_match_history pmh
        JOIN players p ON pmh.player_id = p.id
        LEFT JOIN teams t ON p.team_id = t.id
        WHERE pmh.is_refuerzo = 1
    """
    args = []
    if categoria:
        sql += " AND pmh.category_match = ?"
        args.append(categoria)
    sql += " ORDER BY pmh.id DESC LIMIT ?"
    args.append(limit)

    with database.get_connection() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    return {"count": len(rows), "items": rows}
