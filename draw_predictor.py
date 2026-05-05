"""
CTA Monitor — Draw Predictor v2
Autor: JDM | #JDMRules

Predice la alineación rival (slots D1-D4 dobles + S1 singlista) usando
historial de match_rubbers con ponderación por recencia y score de consolidación.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime

import database

logger = logging.getLogger("draw_predictor")

# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────
SLOTS: tuple[str, ...] = ("D1", "D2", "D3", "D4", "S1")
RECENT_WINDOW: int = 3       # últimos N matches pesan RECENT_WEIGHT
RECENT_WEIGHT: float = 2.0
THRESHOLDS = {"fija": 0.6, "rotativa": 0.3}
S1_PRIORITY_MULTIPLIER: float = 1.2   # S1 vale más al sugerir alineación


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────
def _position_to_slot(position: int, rubber_type: str) -> str | None:
    """Convierte posición numérica + tipo → slot semántico.

    Convención del torneo: position 1-4 + doubles → D1..D4;
    position 5 + singles → S1. Cualquier otra combinación → None.
    """
    if rubber_type == "doubles" and 1 <= position <= 4:
        return f"D{position}"
    if rubber_type == "singles" and position == 5:
        return "S1"
    return None


def _extract_jornada(raw_detail: str | None) -> str | None:
    if not raw_detail:
        return None
    try:
        return json.loads(raw_detail).get("jornada")
    except (json.JSONDecodeError, TypeError):
        return None


def _resolve_players(row: dict, perspective: str) -> tuple[list[int], list[str]]:
    """Extrae cta_ids y nombres del equipo según perspectiva home/away."""
    if perspective == "home":
        cta_ids = [
            cid for cid in [
                row.get("home_player_cta_id"),
                row.get("home_partner_cta_id"),
            ] if cid
        ]
        names = [
            n for n in [
                row.get("home_player_name"),
                row.get("home_partner_name"),
            ] if n
        ]
    else:
        cta_ids = [
            cid for cid in [
                row.get("away_player_cta_id"),
                row.get("away_partner_cta_id"),
            ] if cid
        ]
        names = [
            n for n in [
                row.get("away_player_name"),
                row.get("away_partner_name"),
            ] if n
        ]
    return cta_ids, names


def _slot_order(slot: str) -> int:
    """D1 < D2 < D3 < D4 < S1 (D1 = más importante en dobles)."""
    return {"D1": 1, "D2": 2, "D3": 3, "D4": 4, "S1": 5}.get(slot, 9)


# ─────────────────────────────────────────────
# HISTORIA DE SLOTS
# ─────────────────────────────────────────────
def get_team_slot_history(team_cta_id: int, last_n: int = 10) -> list[dict]:
    """Retorna el historial de rubbers del equipo, enriquecido con slot semántico.

    Cada entrada: {match_id, match_date, jornada, slot, players:[cta_id],
                   player_names:[str], won:bool, score:str}.
    Ordenado por match_date DESC (el más reciente primero).
    """
    rows = database.get_rubbers_by_team(team_cta_id, last_n=last_n)
    history: list[dict] = []

    for row in rows:
        slot = _position_to_slot(row["position"], row["rubber_type"])
        if slot is None:
            continue

        perspective: str = row["perspective"]
        cta_ids, names = _resolve_players(row, perspective)

        if not cta_ids:
            continue

        won = (
            (row.get("winner") == "home" and perspective == "home") or
            (row.get("winner") == "away" and perspective == "away")
        )

        history.append({
            "match_id":    row["match_id"],
            "match_date":  row["match_date"],
            "jornada":     _extract_jornada(row.get("raw_detail")),
            "slot":        slot,
            "players":     cta_ids,
            "player_names": names,
            "won":         won,
            "score":       row.get("score") or "",
        })

    return history


# ─────────────────────────────────────────────
# SCORING DE CONSOLIDACIÓN POR SLOT
# ─────────────────────────────────────────────
def compute_slot_consolidation(history: list[dict], slot: str) -> dict:
    """Calcula la consolidación de candidatos para un slot dado.

    Para dobles agrupa por frozenset de cta_ids de la pareja.
    Para S1 agrupa por cta_id individual.
    Los últimos RECENT_WINDOW matches únicos pesan RECENT_WEIGHT, el resto 1.0.

    Retorna:
        {candidates: [{key, players, player_names, appearances, weighted, score, badge}],
         total_matches: int, weighted_total: float, low_data: bool}
    """
    slot_entries = [h for h in history if h["slot"] == slot]
    if not slot_entries:
        return {
            "candidates": [],
            "total_matches": 0,
            "weighted_total": 0.0,
            "low_data": True,
        }

    # Orden de matches únicos en este slot (0 = más reciente)
    seen_match_ids: list[int] = []
    seen_set: set[int] = set()
    for h in slot_entries:
        mid = h["match_id"]
        if mid not in seen_set:
            seen_set.add(mid)
            seen_match_ids.append(mid)
    match_rank = {mid: i for i, mid in enumerate(seen_match_ids)}

    counts: dict = {}
    weighted_total = 0.0

    for entry in slot_entries:
        weight = (
            RECENT_WEIGHT
            if match_rank.get(entry["match_id"], RECENT_WINDOW) < RECENT_WINDOW
            else 1.0
        )

        if slot == "S1":
            key = entry["players"][0] if entry["players"] else None
        else:
            key = frozenset(entry["players"]) if len(entry["players"]) >= 2 else None

        if key is None:
            continue

        weighted_total += weight
        if key not in counts:
            counts[key] = {
                "key":          key,
                "players":      entry["players"],
                "player_names": entry["player_names"],
                "appearances":  0,
                "weighted":     0.0,
            }
        counts[key]["appearances"] += 1
        counts[key]["weighted"] += weight
        # Keep the latest player_names (first encounter is most recent due to DESC order)

    if not counts:
        return {
            "candidates": [],
            "total_matches": len(seen_match_ids),
            "weighted_total": 0.0,
            "low_data": True,
        }

    candidates = sorted(counts.values(), key=lambda x: x["weighted"], reverse=True)
    for c in candidates:
        score = c["weighted"] / max(weighted_total, 1.0)
        c["score"] = round(score, 3)
        c["badge"] = (
            "fija" if score >= THRESHOLDS["fija"] else
            "rotativa" if score >= THRESHOLDS["rotativa"] else
            "incierta"
        )

    return {
        "candidates":     candidates[:5],
        "total_matches":  len(seen_match_ids),
        "weighted_total": round(weighted_total, 2),
        "low_data":       len(seen_match_ids) < RECENT_WINDOW,
    }


# ─────────────────────────────────────────────
# PREDICCIÓN DE ALINEACIÓN RIVAL v2
# ─────────────────────────────────────────────
def predict_rival_lineup_v2(rival_cta_id: int, last_n: int = 10) -> list[dict]:
    """Predice la alineación rival por slot (D1-D4, S1) con scoring de consolidación.

    Retorna lista de 5 entradas (una por slot):
        [{slot, type, players:[{name,cta_id}], confidence, badge,
          candidates:[top5], low_data}]
    """
    history = get_team_slot_history(rival_cta_id, last_n=last_n)
    lineup = []

    for slot in SLOTS:
        consolidation = compute_slot_consolidation(history, slot)
        candidates = consolidation["candidates"]

        if candidates:
            top = candidates[0]
            entry = {
                "slot":        slot,
                "type":        "singles" if slot == "S1" else "doubles",
                "players":     [
                    {"name": n, "cta_id": cid}
                    for n, cid in zip(top["player_names"], top["players"])
                ],
                "confidence":  top["score"],
                "badge":       top["badge"],
                "candidates":  [
                    {
                        "players": [
                            {"name": n, "cta_id": cid}
                            for n, cid in zip(c["player_names"], c["players"])
                        ],
                        "appearances": c["appearances"],
                        "confidence":  c["score"],
                        "badge":       c["badge"],
                    }
                    for c in candidates
                ],
                "low_data":    consolidation["low_data"],
            }
        else:
            entry = {
                "slot":       slot,
                "type":       "singles" if slot == "S1" else "doubles",
                "players":    [],
                "confidence": 0.0,
                "badge":      "incierta",
                "candidates": [],
                "low_data":   True,
            }

        lineup.append(entry)

    return lineup


# ─────────────────────────────────────────────
# SUGERENCIA DE ALINEACIÓN PROPIA v2
# ─────────────────────────────────────────────
def _player_ranking(cta_id: int) -> float | None:
    """Ranking actual del jugador, o None si no disponible."""
    stats = database.get_latest_player_stats(cta_id)
    if stats and stats.get("ranking") is not None:
        return float(stats["ranking"])
    return None


def _win_prob_estimate(
    own_players: list[int],
    rival_players: list[int],
    rankings_cache: dict[int, float | None] | None = None,
    h2h_cache: dict[tuple[int, int], list[dict]] | None = None,
) -> float:
    """Estima probabilidad de victoria basada en ranking diferencial + H2H.

    rankings_cache: dict {cta_id: ranking} para evitar N+1 queries.
    h2h_cache: dict {(own_cta_id, rival_cta_id): [rubbers]} pre-cargado.

    Retorna valor 0.0–1.0 (0.5 = paridad / sin datos).
    """
    score = 0.5

    # Ranking diferencial (promedio de la pareja si aplica)
    if rankings_cache is not None:
        own_ranks = [rankings_cache.get(p) for p in own_players if rankings_cache.get(p) is not None]
        riv_ranks = [rankings_cache.get(p) for p in rival_players if rankings_cache.get(p) is not None]
    else:
        own_ranks = [r for r in [_player_ranking(p) for p in own_players] if r is not None]
        riv_ranks = [r for r in [_player_ranking(p) for p in rival_players] if r is not None]

    if own_ranks and riv_ranks:
        own_avg = sum(own_ranks) / len(own_ranks)
        riv_avg = sum(riv_ranks) / len(riv_ranks)
        # En CTA el ranking es "menor = mejor". Diferencial positivo = rival más fuerte.
        diff = riv_avg - own_avg
        # Normalizar: cada punto de ranking ≈ 0.02 de prob shift, cap a ±0.35
        shift = max(-0.35, min(0.35, diff * 0.02))
        score = 0.5 + shift

    # H2H entre cada jugador propio vs cada jugador rival
    h2h_wins = h2h_total = 0
    for own_id in own_players:
        for riv_id in rival_players:
            if h2h_cache is not None:
                rubbers = h2h_cache.get((own_id, riv_id), [])
            else:
                rubbers = database.get_player_head_to_head(own_id, riv_id)
            for r in rubbers:
                h2h_total += 1
                home_cta_ids = {r.get("home_player_cta_id"), r.get("home_partner_cta_id")}
                won = (
                    (r.get("winner") == "home" and own_id in home_cta_ids) or
                    (r.get("winner") == "away" and own_id not in home_cta_ids)
                )
                if won:
                    h2h_wins += 1

    if h2h_total > 0:
        h2h_rate = h2h_wins / h2h_total
        # Ponderar H2H con 40% y ranking con 60% si tenemos ambos datos
        score = score * 0.6 + h2h_rate * 0.4

    return round(min(1.0, max(0.0, score)), 3)


def suggest_own_lineup_v2(
    rival_cta_id: int,
    *,
    available_player_ids: list[int] | None = None,
    own_team_cta_id: int | None = None,
) -> list[dict]:
    """Sugiere alineación propia orientada a asegurar 3 de 5 encuentros.

    Si available_player_ids es None usa todos los jugadores del equipo propio.
    S1 tiene multiplicador de prioridad S1_PRIORITY_MULTIPLIER.

    Retorna lista de 5 entradas (una por slot):
        [{slot, our_players:[{name,cta_id}], vs_players:[{name,cta_id}],
          expected_win_prob, priority:'primario'|'secundario', reasoning, alternatives}]
    """
    own_team = database.get_team(own_team_cta_id) if own_team_cta_id else database.get_own_team()
    if not own_team:
        return [{"error": "Equipo propio no encontrado en la DB"}]

    # Resolver roster propio disponible
    if available_player_ids is not None:
        own_all = database.get_team_players(own_team["cta_id"])
        own_players_meta = [p for p in own_all if p["cta_id"] in available_player_ids]
    else:
        own_players_meta = database.get_team_players(own_team["cta_id"])

    if not own_players_meta:
        return [{"error": "Sin jugadores propios disponibles"}]

    rival_prediction = predict_rival_lineup_v2(rival_cta_id)
    own_history = get_team_slot_history(own_team["cta_id"], last_n=10)

    # Pares propios habituales por slot (para alternatives)
    own_pairs_by_slot: dict[str, list[list[int]]] = defaultdict(list)
    for h in own_history:
        if h["players"] not in own_pairs_by_slot[h["slot"]]:
            own_pairs_by_slot[h["slot"]].append(h["players"])

    # Candidatos propios: para dobles usamos pares históricos + random combos
    # Para S1 usamos jugadores individuales
    all_own_cta_ids = [p["cta_id"] for p in own_players_meta]
    own_meta_by_cta = {p["cta_id"]: p for p in own_players_meta}

    # Pre-cargar rankings y H2H para evitar N+1 queries
    rival_ids = list({
        p["cta_id"]
        for e in rival_prediction
        for p in e.get("players", [])
        if p.get("cta_id")
    })
    all_player_ids = list(set(all_own_cta_ids + rival_ids))
    rankings_cache: dict[int, float | None] = {cid: None for cid in all_player_ids}
    if all_player_ids:
        rankings_cache.update(database.get_bulk_player_rankings(all_player_ids))
    h2h_cache: dict[tuple[int, int], list[dict]] = {}
    if rival_ids:
        h2h_cache = database.get_bulk_head_to_head_matches(all_own_cta_ids, rival_ids)

    # Construir candidatos propios por slot
    def own_candidates_for_slot(slot: str) -> list[list[int]]:
        if slot == "S1":
            return [[cid] for cid in all_own_cta_ids]
        # Para dobles: pares históricos del equipo propios en ese slot primero,
        # luego todos los pares posibles de jugadores disponibles
        historical = [
            p for p in own_pairs_by_slot.get(slot, [])
            if all(cid in all_own_cta_ids for cid in p)
        ]
        seen = {frozenset(p) for p in historical}
        extras = [
            [a, b]
            for i, a in enumerate(all_own_cta_ids)
            for b in all_own_cta_ids[i + 1:]
            if frozenset([a, b]) not in seen
        ]
        return historical + extras

    # Para cada slot calcular el mejor candidato propio
    slot_scores: list[dict] = []
    for pred_entry in rival_prediction:
        slot = pred_entry["slot"]
        rival_players = [p["cta_id"] for p in pred_entry["players"]]

        # Recolectar todos los combos con su probabilidad
        combo_scores: list[tuple[list[int], float]] = []
        for combo in own_candidates_for_slot(slot):
            if not all(cid in all_own_cta_ids for cid in combo):
                continue
            prob = _win_prob_estimate(combo, rival_players, rankings_cache, h2h_cache)
            combo_scores.append((combo, prob))

        combo_scores.sort(key=lambda x: x[1], reverse=True)

        best_combo: list[int] = []
        best_prob: float = 0.0
        alternatives: list[dict] = []
        if combo_scores:
            best_combo, best_prob = combo_scores[0]
            alternatives = [
                {
                    "players": [
                        {"name": own_meta_by_cta[c]["name"], "cta_id": c}
                        for c in combo if c in own_meta_by_cta
                    ],
                    "expected_win_prob": prob,
                }
                for combo, prob in combo_scores[1:4]
            ]

        priority_score = best_prob * (S1_PRIORITY_MULTIPLIER if slot == "S1" else 1.0)

        slot_scores.append({
            "slot":              slot,
            "our_cta_ids":       best_combo,
            "vs_players":        pred_entry["players"],
            "expected_win_prob": best_prob,
            "priority_score":    priority_score,
            "alternatives":      alternatives,
        })

    # Greedy assignment: ordenar por priority_score DESC para marcar primario/secundario
    slot_scores_sorted = sorted(slot_scores, key=lambda x: x["priority_score"], reverse=True)
    used: set[int] = set()
    primarios = 0
    suggestions = []

    for entry in slot_scores_sorted:
        assigned_cta_ids = [
            cid for cid in entry["our_cta_ids"] if cid not in used
        ]
        # Para dobles necesitamos 2 libres
        needed = 1 if entry["slot"] == "S1" else 2
        if len(assigned_cta_ids) < needed:
            # Fallback: rellenar con cualquier disponible
            extras = [c for c in all_own_cta_ids if c not in used]
            assigned_cta_ids = extras[:needed]

        for cid in assigned_cta_ids:
            used.add(cid)

        priority = "primario" if primarios < 3 else "secundario"
        if priority == "primario":
            primarios += 1

        # Build reasoning
        reasoning_parts = []
        if entry["expected_win_prob"] >= 0.6:
            reasoning_parts.append("ventaja por ranking/H2H")
        elif entry["expected_win_prob"] >= 0.5:
            reasoning_parts.append("paridad")
        else:
            reasoning_parts.append("rival favorable")
        if entry["slot"] == "S1":
            reasoning_parts.append("S1 es el desempate del 2-2")

        suggestions.append({
            "slot":              entry["slot"],
            "our_players":       [
                {"name": own_meta_by_cta[c]["name"], "cta_id": c}
                for c in assigned_cta_ids if c in own_meta_by_cta
            ],
            "vs_players":        entry["vs_players"],
            "expected_win_prob": entry["expected_win_prob"],
            "priority":          priority,
            "reasoning":         " | ".join(reasoning_parts),
            "alternatives":      entry["alternatives"],
        })

    # Devolver en orden de slot (D1, D2, D3, D4, S1)
    suggestions.sort(key=lambda x: _slot_order(x["slot"]))
    return suggestions


# ─────────────────────────────────────────────
# ALERTAS TÁCTICAS
# ─────────────────────────────────────────────
def detect_alerts(rival_cta_id: int, prediction: list[dict]) -> list[dict]:
    """Genera alertas tácticas sobre la alineación predicha del rival.

    Kinds: first_time_pair | promoted_slot | versatile | inactive | unusual_s1
    """
    history = get_team_slot_history(rival_cta_id, last_n=10)
    alerts: list[dict] = []

    if not history:
        return alerts

    # Match IDs ordenados DESC (el más reciente primero)
    match_order: list[int] = []
    seen_mids: set[int] = set()
    for h in history:
        if h["match_id"] not in seen_mids:
            seen_mids.add(h["match_id"])
            match_order.append(h["match_id"])

    # ── 1. First time pair (o singlista) ────────────────────────────────────
    for entry in prediction:
        if not entry["players"]:
            continue
        slot = entry["slot"]
        key = (
            frozenset(p["cta_id"] for p in entry["players"])
            if slot != "S1"
            else entry["players"][0]["cta_id"]
        )
        # Solo cuenta histórico anterior a los últimos 3 matches
        older_history = [
            h for h in history
            if match_order.index(h["match_id"]) >= RECENT_WINDOW
            and h["slot"] == slot
        ]
        if slot == "S1":
            appeared = any(h["players"] and h["players"][0] == key for h in older_history)
        else:
            appeared = any(frozenset(h["players"]) == key for h in older_history)

        if not appeared:
            # Solo alertar si realmente hay historia antigua contra la cual comparar
            if not older_history and len(match_order) <= RECENT_WINDOW:
                continue
            names = " / ".join(p["name"] for p in entry["players"])
            alerts.append({
                "kind":     "first_time_pair",
                "slot":     slot,
                "severity": "warning",
                "title":    "Primera vez juntos" if slot != "S1" else "Singlista sin antecedentes",
                "detail":   f"{names} no tiene historial en {slot} más allá de los últimos partidos.",
                "players":  entry["players"],
            })

    # ── 2. Promoted slot (pareja jugó >60% en slot inferior) ───────────────
    slot_rank = {"D1": 1, "D2": 2, "D3": 3, "D4": 4}
    for entry in prediction:
        if entry["slot"] == "S1" or not entry["players"]:
            continue
        predicted_rank = slot_rank[entry["slot"]]
        player_cta_ids = {p["cta_id"] for p in entry["players"]}

        slot_counter: dict[str, int] = defaultdict(int)
        for h in history:
            if h["slot"] == "S1":
                continue
            if player_cta_ids & set(h["players"]):
                slot_counter[h["slot"]] += 1

        total = sum(slot_counter.values())
        if total < 3:
            continue

        lower_slots = {s for s, r in slot_rank.items() if r > predicted_rank}
        lower_count = sum(slot_counter.get(s, 0) for s in lower_slots)
        if total > 0 and lower_count / total >= 0.6:
            names = " / ".join(p["name"] for p in entry["players"])
            usual = max(slot_counter, key=slot_counter.get)
            alerts.append({
                "kind":     "promoted_slot",
                "slot":     entry["slot"],
                "severity": "info",
                "title":    "Ascendieron de posición",
                "detail":   f"{names} suele jugar {usual} pero aparece en {entry['slot']}.",
                "players":  entry["players"],
            })

    # ── 3. Jugador polivalente (3+ slots distintos en últimos 5 matches) ────
    recent_5 = [h for h in history if match_order.index(h["match_id"]) < 5]
    player_slots: dict[int, set[str]] = defaultdict(set)
    for h in recent_5:
        for cta_id in h["players"]:
            player_slots[cta_id].add(h["slot"])

    for cta_id, slots_used in player_slots.items():
        if len(slots_used) >= 3:
            player_row = database.get_player(cta_id)
            name = player_row["name"] if player_row else str(cta_id)
            alerts.append({
                "kind":     "versatile",
                "slot":     None,
                "severity": "info",
                "title":    "Jugador polivalente",
                "detail":   f"{name} jugó en {len(slots_used)} posiciones distintas en los últimos 5 partidos.",
                "players":  [{"name": name, "cta_id": cta_id}],
            })

    # ── 4. Jugador sin actividad reciente (no aparece en últimos 2 matches) ─
    last_2_mids = match_order[:2]
    active_in_last_2: set[int] = set()
    for h in history:
        if h["match_id"] in last_2_mids:
            active_in_last_2.update(h["players"])

    for entry in prediction:
        for player in entry["players"]:
            cta_id = player["cta_id"]
            if cta_id and cta_id not in active_in_last_2:
                # Solo alertar si tiene historial previo (no es primera vez)
                has_history = any(cta_id in h["players"] for h in history)
                if has_history:
                    alerts.append({
                        "kind":     "inactive",
                        "slot":     entry["slot"],
                        "severity": "warning",
                        "title":    "Sin actividad reciente",
                        "detail":   f"{player['name']} no jugó en los últimos 2 partidos del equipo rival.",
                        "players":  [player],
                    })

    # ── 5. Singlista inusual ─────────────────────────────────────────────────
    s1_pred = next((e for e in prediction if e["slot"] == "S1"), None)
    if s1_pred and s1_pred["players"]:
        s1_pred_cta = s1_pred["players"][0]["cta_id"]
        # Singlista más frecuente histórico (excluyendo últimos 3)
        older_s1 = [h for h in history if h["slot"] == "S1"
                    and match_order.index(h["match_id"]) >= RECENT_WINDOW]
        if older_s1:
            s1_counter: dict[int, int] = defaultdict(int)
            for h in older_s1:
                if h["players"]:
                    s1_counter[h["players"][0]] += 1
            usual_s1 = max(s1_counter, key=s1_counter.get, default=None)
            if usual_s1 and usual_s1 != s1_pred_cta:
                usual_row = database.get_player(usual_s1)
                usual_name = usual_row["name"] if usual_row else str(usual_s1)
                alerts.append({
                    "kind":     "unusual_s1",
                    "slot":     "S1",
                    "severity": "critical",
                    "title":    "Singlista inusual",
                    "detail":   (
                        f"Se predice {s1_pred['players'][0]['name']} en S1, "
                        f"pero históricamente suele ser {usual_name}. "
                        "S1 decide la jornada en escenarios 2-2."
                    ),
                    "players": s1_pred["players"],
                })

    return alerts


# ─────────────────────────────────────────────
# H2H EQUIPO VS EQUIPO
# ─────────────────────────────────────────────
def get_h2h_team_vs_team(own_cta_id: int, rival_cta_id: int) -> dict:
    """H2H entre equipo propio y rival a nivel de partido."""
    matches = database.get_head_to_head(own_cta_id, rival_cta_id)
    current_year = datetime.now().year

    all_time = {"won": 0, "lost": 0, "draws": 0}
    season = {"won": 0, "lost": 0, "draws": 0}
    last_meetings: list[dict] = []

    for m in matches:
        is_home = m.get("home_cta_id") == own_cta_id
        own_score = m["home_score"] if is_home else m["away_score"]
        opp_score = m["away_score"] if is_home else m["home_score"]

        if own_score is None or opp_score is None:
            continue
        try:
            own_s, opp_s = int(own_score), int(opp_score)
        except (ValueError, TypeError):
            continue

        if own_s > opp_s:
            result, key = "W", "won"
        elif own_s < opp_s:
            result, key = "L", "lost"
        else:
            result, key = "D", "draws"

        all_time[key] += 1

        match_date = m.get("match_date") or ""
        if str(current_year) in match_date:
            season[key] += 1

        last_meetings.append({
            "date":        match_date,
            "score":       f"{own_score}-{opp_score}",
            "result":      result,
            "home_team":   m.get("home_team_name"),
            "away_team":   m.get("away_team_name"),
        })

    return {
        "all_time":      all_time,
        "season":        season,
        "last_meetings": last_meetings[:5],
    }


# ─────────────────────────────────────────────
# TIMELINE (últimas N jornadas del rival)
# ─────────────────────────────────────────────
def get_timeline(rival_cta_id: int, last_n: int = 5) -> list[dict]:
    """Retorna alineaciones del rival en sus últimos N partidos.

    Cada entrada: {match_id, match_date, jornada, opponent, result,
                   lineup:{D1:[...], D2:[...], D3:[...], D4:[...], S1:[...]}}
    """
    rows = database.get_rubbers_by_team(rival_cta_id, last_n=last_n)
    matches_dict: dict[int, dict] = {}

    for row in rows:
        mid = row["match_id"]
        if mid not in matches_dict:
            perspective = row["perspective"]
            opponent = (
                row.get("away_team_cta_id") if perspective == "home"
                else row.get("home_team_cta_id")
            )
            own_score = row.get("home_score") if perspective == "home" else row.get("away_score")
            opp_score = row.get("away_score") if perspective == "home" else row.get("home_score")
            result = "?"
            if own_score is not None and opp_score is not None:
                try:
                    result = "W" if int(own_score) > int(opp_score) else "L"
                except (ValueError, TypeError):
                    pass

            # Resolver nombre del oponente
            opp_team = database.get_team(opponent) if opponent else None
            opp_name = opp_team["name"] if opp_team else f"Equipo {opponent}"

            matches_dict[mid] = {
                "match_id":   mid,
                "match_date": row["match_date"],
                "jornada":    _extract_jornada(row.get("raw_detail")),
                "opponent":   opp_name,
                "result":     result,
                "lineup":     {s: [] for s in SLOTS},
            }

        slot = _position_to_slot(row["position"], row["rubber_type"])
        if slot is None:
            continue
        cta_ids, names = _resolve_players(row, row["perspective"])
        matches_dict[mid]["lineup"][slot] = [
            {"name": n, "cta_id": cid}
            for n, cid in zip(names, cta_ids)
        ]

    # Devolver en orden cronológico DESC (más reciente primero)
    return sorted(matches_dict.values(), key=lambda x: x["match_date"] or "", reverse=True)


# ─────────────────────────────────────────────
# HEATMAP jugador × slot
# ─────────────────────────────────────────────
def get_heatmap(rival_cta_id: int) -> dict:
    """Retorna matriz de apariciones jugador × slot como porcentajes.

    Shape: {players:[{cta_id,name}], slots:[...SLOTS...], cells:[[pct,...]]}
    cells[i][j] = porcentaje de veces que player[i] jugó en slot[j].
    """
    history = get_team_slot_history(rival_cta_id, last_n=50)

    # Contar apariciones por (player_cta_id, slot)
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {s: 0 for s in SLOTS})
    names_by_cta: dict[int, str] = {}

    for h in history:
        for cta_id, name in zip(h["players"], h["player_names"]):
            counts[cta_id][h["slot"]] += 1
            names_by_cta[cta_id] = name

    if not counts:
        return {"players": [], "slots": list(SLOTS), "cells": []}

    # Normalizar por jugador (% de sus apariciones totales en cada slot)
    players_out = []
    cells = []

    for cta_id in sorted(counts.keys()):
        total = sum(counts[cta_id].values())
        if total == 0:
            continue
        players_out.append({"cta_id": cta_id, "name": names_by_cta.get(cta_id, str(cta_id))})
        cells.append([round(counts[cta_id][s] / total, 3) for s in SLOTS])

    return {
        "players": players_out,
        "slots":   list(SLOTS),
        "cells":   cells,
    }


# ─────────────────────────────────────────────
# REPORTE COMPLETO (one-shot)
# ─────────────────────────────────────────────
def build_draw_report(rival_cta_id: int, available_player_ids: list[int] | None = None, own_team_cta_id: int | None = None, last_n: int = 10) -> dict:
    """Genera el reporte completo del predictor en un solo dict.

    Incluye: rival, prediction, suggestion, alerts, h2h, low_data, generated_at.
    """
    rival_team = database.get_team(rival_cta_id)
    if not rival_team:
        return {"error": f"Equipo {rival_cta_id} no encontrado"}

    own_team = database.get_team(own_team_cta_id) if own_team_cta_id else database.get_own_team()

    prediction = predict_rival_lineup_v2(rival_cta_id, last_n=last_n)
    suggestion = suggest_own_lineup_v2(rival_cta_id, available_player_ids=available_player_ids, own_team_cta_id=own_team_cta_id)
    alerts = detect_alerts(rival_cta_id, prediction)
    h2h = get_h2h_team_vs_team(own_team["cta_id"], rival_cta_id) if own_team else {}
    low_data = any(e.get("low_data") for e in prediction)

    return {
        "rival":        {"name": rival_team["name"], "cta_id": rival_cta_id},
        "prediction":   prediction,
        "suggestion":   suggestion,
        "alerts":       alerts,
        "h2h":          h2h,
        "low_data":     low_data,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────────────────────────────
# WRAPPERS DE COMPATIBILIDAD (mantiene CLI viejo)
# ─────────────────────────────────────────────
def predict_rival_lineup(rival_cta_id: int) -> list[dict]:
    """Wrapper de compatibilidad → predict_rival_lineup_v2."""
    return predict_rival_lineup_v2(rival_cta_id)


def suggest_own_lineup(rival_cta_id: int) -> list[dict]:
    """Wrapper de compatibilidad → suggest_own_lineup_v2."""
    return suggest_own_lineup_v2(rival_cta_id)


def get_head_to_head_matrix(own_team_cta_id: int, rival_team_cta_id: int) -> dict:
    """Compatibilidad: devuelve H2H a nivel equipo formateado como matrix."""
    h2h = get_h2h_team_vs_team(own_team_cta_id, rival_team_cta_id)
    return {
        ("Equipo Propio", "Rival"): {
            "own_wins":   h2h["all_time"]["won"],
            "rival_wins": h2h["all_time"]["lost"],
            "total":      sum(h2h["all_time"].values()),
        }
    }


def format_draw_report(rival_cta_id: int, last_n: int = 10) -> str:
    """Genera reporte textual en español para el CLI."""
    rival_team = database.get_team(rival_cta_id)
    if not rival_team:
        return f"Error: Equipo rival {rival_cta_id} no encontrado en la base de datos"

    own_team = database.get_own_team()
    own_name = own_team["name"] if own_team else "Equipo Propio"

    lines = [
        "=" * 58,
        f"  PREDICTOR DE DRAW — v2",
        f"  {own_name} vs {rival_team['name']}",
        "=" * 58,
        "",
    ]

    prediction = predict_rival_lineup_v2(rival_cta_id, last_n=last_n)
    badge_icon = {"fija": "●", "rotativa": "◐", "incierta": "○"}

    lines.append("ALINEACION PROBABLE DEL RIVAL:")
    for entry in prediction:
        slot = entry["slot"]
        icon = badge_icon.get(entry["badge"], "○")
        conf = entry["confidence"] * 100
        players_str = " / ".join(p["name"] for p in entry["players"]) or "(sin datos)"
        low = " ⚠ pocos datos" if entry.get("low_data") else ""
        lines.append(f"  {slot}: {players_str}  {icon} {conf:.0f}%{low}")
    lines.append("")

    suggestion = suggest_own_lineup_v2(rival_cta_id)
    lines.append("ALINEACION SUGERIDA (objetivo: ganar 3 de 5):")
    for s in suggestion:
        slot = s["slot"]
        own_str = " / ".join(p["name"] for p in s["our_players"]) or "(sin datos)"
        vs_str = " / ".join(p["name"] for p in s["vs_players"]) or "?"
        prob = s["expected_win_prob"] * 100
        prio = "[PRIM]" if s["priority"] == "primario" else "[sec] "
        lines.append(f"  {prio} {slot}: {own_str}  vs  {vs_str}  ({prob:.0f}% prob)")
    lines.append("")

    alerts = detect_alerts(rival_cta_id, prediction)
    if alerts:
        lines.append("ALERTAS TACTICAS:")
        icon_map = {
            "first_time_pair": "⚠ ",
            "promoted_slot":   "↑ ",
            "versatile":       "↔ ",
            "inactive":        "✗ ",
            "unusual_s1":      "★ ",
        }
        for a in alerts:
            slot_str = f"[{a['slot']}] " if a["slot"] else ""
            icon = icon_map.get(a["kind"], "· ")
            lines.append(f"  {icon}{slot_str}{a['title']}: {a['detail']}")
        lines.append("")

    own_h2h = get_h2h_team_vs_team(own_team["cta_id"], rival_cta_id) if own_team else {}
    if own_h2h.get("all_time", {}).get("won", 0) + own_h2h.get("all_time", {}).get("lost", 0) > 0:
        at = own_h2h["all_time"]
        lines.append(f"H2H: {at['won']}V - {at['lost']}D ({at.get('draws',0)} empates, all time)")
        for m in own_h2h.get("last_meetings", [])[:3]:
            lines.append(f"  {m['date']}: {m['score']} ({m['result']})")
        lines.append("")

    lines.append("=" * 58)
    return "\n".join(lines)
