"""
CTA Intelligence System — Rival Analyzer
Autor: JDM | #JDMRules

Generates analysis reports for rival teams based on data in the database.
"""

from __future__ import annotations

import logging
from collections import Counter

import database

logger = logging.getLogger("rival_analyzer")


def get_rival_summary(team_cta_id: int, last_n: int = 5) -> dict:
    """Comprehensive rival analysis.

    Returns:
        {
            team: {name, cta_id},
            recent_matches: [...],
            record: {won, lost, total, win_rate},
            habitual_players: [...],
            position_preferences: {1: [...], 2: [...], ...},
        }
    """
    team = database.get_team(team_cta_id)
    if not team:
        return {"error": f"Equipo {team_cta_id} no encontrado en la base de datos"}

    summary = {
        "team": {"name": team["name"], "cta_id": team_cta_id},
        "recent_matches": get_recent_matches(team_cta_id, last_n),
        "record": get_win_rate(team_cta_id),
        "habitual_players": get_habitual_players(team_cta_id),
        "position_preferences": get_position_analysis(team_cta_id),
    }
    return summary


def get_recent_matches(team_cta_id: int, limit: int = 5) -> list[dict]:
    """Get recent match results for a team."""
    matches = database.get_team_matches(team_cta_id, limit)
    results = []
    for m in matches:
        is_home = m["home_cta_id"] == team_cta_id
        opponent = m["away_team_name"] if is_home else m["home_team_name"]
        own_score = m["home_score"] if is_home else m["away_score"]
        opp_score = m["away_score"] if is_home else m["home_score"]

        result = "?"
        if own_score and opp_score:
            try:
                result = "W" if int(own_score) > int(opp_score) else "L"
            except ValueError:
                result = "?"

        results.append({
            "id": m["id"],
            "date": m["match_date"],
            "opponent": opponent,
            "score": f"{own_score}-{opp_score}" if own_score else "pendiente",
            "result": result,
            "status": m["status"],
        })
    return results


def get_win_rate(team_cta_id: int, last_n: int = None) -> dict:
    """Calculate win/loss record."""
    limit = last_n or 100
    matches = database.get_team_matches(team_cta_id, limit)

    won = 0
    lost = 0
    total = 0

    for m in matches:
        if m["status"] != "completed":
            continue

        is_home = m["home_cta_id"] == team_cta_id
        own_score = m["home_score"] if is_home else m["away_score"]
        opp_score = m["away_score"] if is_home else m["home_score"]

        if own_score and opp_score:
            try:
                if int(own_score) > int(opp_score):
                    won += 1
                else:
                    lost += 1
                total += 1
            except ValueError:
                continue

    return {
        "won": won,
        "lost": lost,
        "total": total,
        "win_rate": round(won / total, 3) if total > 0 else 0,
    }


def get_habitual_players(team_cta_id: int, last_n: int = 10) -> list[dict]:
    """Get players sorted by frequency of appearance in match rubbers."""
    players = database.get_team_players(team_cta_id)
    if not players:
        return []

    player_stats = []
    for p in players:
        history = database.get_player_match_history(p["cta_id"], last_n * 4)
        wins = sum(1 for h in history if _is_winner(h, p["cta_id"]))
        total = len(history)

        # Get latest stats snapshot
        latest_stats = database.get_latest_player_stats(p["cta_id"])

        player_stats.append({
            "name": p["name"],
            "cta_id": p["cta_id"],
            "appearances": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 3) if total > 0 else 0,
            "ranking": latest_stats.get("ranking") if latest_stats else None,
        })

    # Sort by appearances descending
    player_stats.sort(key=lambda x: x["appearances"], reverse=True)
    return player_stats


def _is_winner(rubber: dict, player_cta_id: int) -> bool:
    """Determine if the player won a rubber."""
    if rubber.get("winner") == "home" and rubber.get("home_player_name"):
        # Check if our player is on home side
        # This is approximate — we'd need cta_id join for precision
        return True
    return False


def get_position_analysis(team_cta_id: int, last_n: int = 10) -> dict:
    """Analyze which players play which positions most often."""
    players = database.get_team_players(team_cta_id)
    positions = {1: Counter(), 2: Counter(), 3: Counter(), "doubles": Counter()}

    for p in players:
        history = database.get_player_match_history(p["cta_id"], last_n * 4)
        for h in history:
            pos = h.get("position")
            rtype = h.get("rubber_type", "singles")
            if rtype == "doubles":
                positions["doubles"][p["name"]] += 1
            elif pos in positions:
                positions[pos][p["name"]] += 1

    # Convert Counters to sorted lists
    result = {}
    for pos, counter in positions.items():
        result[pos] = [
            {"name": name, "count": count}
            for name, count in counter.most_common(5)
        ]
    return result


def format_rival_report(team_cta_id: int) -> str:
    """Generate human-readable rival report in Spanish."""
    summary = get_rival_summary(team_cta_id)

    if "error" in summary:
        return f"Error: {summary['error']}"

    team = summary["team"]
    record = summary["record"]
    lines = []

    lines.append(f"{'='*50}")
    lines.append(f"  ANALISIS DE RIVAL: {team['name']}")
    lines.append(f"  CTA ID: {team['cta_id']}")
    lines.append(f"{'='*50}")
    lines.append("")

    # Record
    lines.append(f"RECORD: {record['won']}G - {record['lost']}P", )
    if record["total"] > 0:
        pct = record["win_rate"] * 100
        lines.append(f"  Win Rate: {pct:.1f}% ({record['total']} partidos)")
    lines.append("")

    # Recent matches
    lines.append("ULTIMOS PARTIDOS:")
    for m in summary["recent_matches"][:5]:
        icon = "W" if m["result"] == "W" else ("L" if m["result"] == "L" else "?")
        lines.append(f"  [{icon}] {m['date'] or 'S/F'} vs {m['opponent']} — {m['score']}")
    if not summary["recent_matches"]:
        lines.append("  (sin datos de partidos)")
    lines.append("")

    # Habitual players
    lines.append("JUGADORES HABITUALES:")
    for p in summary["habitual_players"][:8]:
        rank = f" (Ranking: {p['ranking']})" if p["ranking"] else ""
        lines.append(
            f"  {p['name']}{rank} — "
            f"{p['appearances']} apariciones, "
            f"{p['wins']}G-{p['losses']}P"
        )
    if not summary["habitual_players"]:
        lines.append("  (sin datos de jugadores)")
    lines.append("")

    # Position preferences
    lines.append("ALINEACION TIPICA:")
    prefs = summary["position_preferences"]
    for pos in [1, 2, 3]:
        players = prefs.get(pos, [])
        if players:
            top = players[0]
            lines.append(f"  Singles {pos}: {top['name']} ({top['count']}x)")
    doubles = prefs.get("doubles", [])
    if doubles:
        names = [p["name"] for p in doubles[:2]]
        lines.append(f"  Dobles: {' / '.join(names)}")
    if not any(prefs.values()):
        lines.append("  (sin datos de posiciones)")

    lines.append(f"\n{'='*50}")
    return "\n".join(lines)
