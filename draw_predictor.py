"""
CTA Intelligence System — Draw Predictor
Autor: JDM | #JDMRules

Predicts rival lineup and suggests optimal response lineup.
"""

from __future__ import annotations

import logging

import config
import database
import rival_analyzer

logger = logging.getLogger("draw_predictor")


def predict_rival_lineup(rival_cta_id: int) -> list[dict]:
    """Predict which players the rival will field, based on position history.

    Returns list of predicted lineup entries:
        [{position: 1, player: {name, cta_id}, confidence: 0.8}, ...]
    """
    prefs = rival_analyzer.get_position_analysis(rival_cta_id)
    players_used = rival_analyzer.get_habitual_players(rival_cta_id)

    lineup = []

    for pos in [1, 2, 3]:
        candidates = prefs.get(pos, [])
        if candidates:
            top = candidates[0]
            total_for_pos = sum(c["count"] for c in candidates)
            confidence = top["count"] / total_for_pos if total_for_pos > 0 else 0

            # Find full player data
            player_data = next(
                (p for p in players_used if p["name"] == top["name"]), None
            )
            lineup.append({
                "position": pos,
                "type": "singles",
                "player": player_data or {"name": top["name"]},
                "confidence": round(confidence, 2),
            })
        else:
            # Pick from most used players not yet assigned
            assigned_names = {e["player"]["name"] for e in lineup if e.get("player")}
            for p in players_used:
                if p["name"] not in assigned_names:
                    lineup.append({
                        "position": pos,
                        "type": "singles",
                        "player": p,
                        "confidence": 0.3,
                    })
                    break

    # Doubles
    doubles_candidates = prefs.get("doubles", [])
    if len(doubles_candidates) >= 2:
        lineup.append({
            "position": 4,
            "type": "doubles",
            "player": {"name": doubles_candidates[0]["name"]},
            "partner": {"name": doubles_candidates[1]["name"]},
            "confidence": round(
                doubles_candidates[0]["count"]
                / max(sum(c["count"] for c in doubles_candidates), 1),
                2,
            ),
        })

    return lineup


def suggest_own_lineup(rival_cta_id: int) -> list[dict]:
    """Suggest optimal lineup for Club Tachira B against the predicted rival lineup.

    Strategy:
    - Compare head-to-head records where available
    - Match strongest available player against rival's weakest line
    - Factor in recent form (win rate)
    """
    rival_lineup = predict_rival_lineup(rival_cta_id)
    own_team = database.get_own_team()

    if not own_team:
        return [{"error": "Equipo propio no encontrado en la DB"}]

    own_players = rival_analyzer.get_habitual_players(own_team["cta_id"])
    if not own_players:
        return [{"error": "Sin datos de jugadores propios"}]

    suggestions = []
    assigned = set()

    # For each position, find the best matchup
    for entry in rival_lineup:
        if entry["type"] != "singles":
            continue

        pos = entry["position"]
        rival_player = entry.get("player", {})
        rival_name = rival_player.get("name", "Desconocido")
        rival_cta = rival_player.get("cta_id")

        best_choice = None
        best_score = -1
        best_reasoning = ""

        for own_p in own_players:
            if own_p["name"] in assigned:
                continue

            score = 0
            reasoning_parts = []

            # Factor 1: Head-to-head
            if rival_cta and own_p.get("cta_id"):
                h2h = database.get_player_head_to_head(own_p["cta_id"], rival_cta)
                if h2h:
                    h2h_wins = sum(
                        1 for r in h2h if _player_won_rubber(r, own_p["cta_id"])
                    )
                    h2h_total = len(h2h)
                    if h2h_total > 0:
                        h2h_rate = h2h_wins / h2h_total
                        score += h2h_rate * 40
                        reasoning_parts.append(
                            f"H2H: {h2h_wins}-{h2h_total - h2h_wins}"
                        )

            # Factor 2: Overall win rate
            if own_p.get("win_rate", 0) > 0:
                score += own_p["win_rate"] * 30
                reasoning_parts.append(
                    f"Win rate: {own_p['win_rate']*100:.0f}%"
                )

            # Factor 3: Activity level (more appearances = more reliable)
            if own_p.get("appearances", 0) > 0:
                activity_score = min(own_p["appearances"] / 10, 1.0) * 20
                score += activity_score
                reasoning_parts.append(
                    f"{own_p['appearances']} partidos"
                )

            # Factor 4: Position familiarity
            own_prefs = rival_analyzer.get_position_analysis(own_team["cta_id"])
            pos_players = own_prefs.get(pos, [])
            if any(pp["name"] == own_p["name"] for pp in pos_players):
                score += 10
                reasoning_parts.append(f"Juega posicion {pos}")

            if score > best_score:
                best_score = score
                best_choice = own_p
                best_reasoning = " | ".join(reasoning_parts)

        if best_choice:
            assigned.add(best_choice["name"])
            suggestions.append({
                "position": pos,
                "type": "singles",
                "player": best_choice,
                "vs": rival_name,
                "confidence_score": round(best_score, 1),
                "reasoning": best_reasoning,
            })

    # Doubles suggestion: pick best remaining 2 players
    remaining = [p for p in own_players if p["name"] not in assigned]
    if len(remaining) >= 2:
        suggestions.append({
            "position": 4,
            "type": "doubles",
            "player": remaining[0],
            "partner": remaining[1],
            "reasoning": "Mejores jugadores disponibles",
        })

    return suggestions


def _player_won_rubber(rubber: dict, player_cta_id: int) -> bool:
    """Determine if the player won a rubber match."""
    # Simplified logic — would need full CTA ID mapping for precision
    return rubber.get("winner") == "home"


def get_head_to_head_matrix(own_team_cta_id: int, rival_team_cta_id: int) -> dict:
    """Build matrix of all known H2H between players of both teams."""
    own_players = database.get_team_players(own_team_cta_id)
    rival_players = database.get_team_players(rival_team_cta_id)

    matrix = {}
    for own_p in own_players:
        for rival_p in rival_players:
            h2h = database.get_player_head_to_head(own_p["cta_id"], rival_p["cta_id"])
            if h2h:
                own_wins = sum(
                    1 for r in h2h if _player_won_rubber(r, own_p["cta_id"])
                )
                matrix[(own_p["name"], rival_p["name"])] = {
                    "own_wins": own_wins,
                    "rival_wins": len(h2h) - own_wins,
                    "total": len(h2h),
                }
    return matrix


def format_draw_report(rival_cta_id: int) -> str:
    """Generate draw prediction report in Spanish."""
    rival_team = database.get_team(rival_cta_id)
    if not rival_team:
        return f"Error: Equipo rival {rival_cta_id} no encontrado en la base de datos"

    own_team = database.get_own_team()
    own_name = own_team["name"] if own_team else "Club Tachira B"

    lines = []
    lines.append(f"{'='*55}")
    lines.append(f"  PREDICCION DE DRAW")
    lines.append(f"  {own_name} vs {rival_team['name']}")
    lines.append(f"{'='*55}")
    lines.append("")

    # Predicted rival lineup
    lines.append("ALINEACION PROBABLE DEL RIVAL:")
    rival_lineup = predict_rival_lineup(rival_cta_id)
    for entry in rival_lineup:
        player_name = entry.get("player", {}).get("name", "?")
        conf = entry.get("confidence", 0) * 100
        if entry["type"] == "singles":
            lines.append(f"  Singles {entry['position']}: {player_name} ({conf:.0f}% prob.)")
        else:
            partner = entry.get("partner", {}).get("name", "?")
            lines.append(f"  Dobles: {player_name} / {partner} ({conf:.0f}% prob.)")
    if not rival_lineup:
        lines.append("  (sin datos suficientes)")
    lines.append("")

    # Our suggested lineup
    lines.append("ALINEACION SUGERIDA:")
    suggestions = suggest_own_lineup(rival_cta_id)
    for s in suggestions:
        player_name = s.get("player", {}).get("name", "?")
        if s["type"] == "singles":
            vs = s.get("vs", "?")
            lines.append(f"  Singles {s['position']}: {player_name} vs {vs}")
            if s.get("reasoning"):
                lines.append(f"    Razon: {s['reasoning']}")
        else:
            partner = s.get("partner", {}).get("name", "?")
            lines.append(f"  Dobles: {player_name} / {partner}")
    if not suggestions:
        lines.append("  (sin datos suficientes para sugerencias)")
    lines.append("")

    # H2H matrix
    if own_team:
        matrix = get_head_to_head_matrix(own_team["cta_id"], rival_cta_id)
        if matrix:
            lines.append("HEAD TO HEAD CONOCIDO:")
            for (own_name, rival_name), data in matrix.items():
                lines.append(
                    f"  {own_name} vs {rival_name}: "
                    f"{data['own_wins']}-{data['rival_wins']} ({data['total']} partidos)"
                )
            lines.append("")

    lines.append(f"{'='*55}")
    return "\n".join(lines)
