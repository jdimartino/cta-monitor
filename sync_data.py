#!/usr/bin/env python3
"""sync_data.py — Compara y sincroniza la DB local con ctatenis.com.

Uso:
    python sync_data.py                    # Todas las categorías (~40s)
    python sync_data.py --category 6M     # Solo una categoría (~10s)
    python sync_data.py --compare-only    # Sin escribir a DB
"""

import argparse
import sys
import time
import builtins

# Global print override to handle closed stdout/stderr (e.g. when terminal closes)
_orig_print = builtins.print
def _safe_print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except OSError:
        pass
builtins.print = _safe_print

import requests

import auth
import config
import database
import spider

COMPARE_FIELDS = ["position", "played", "won", "lost",
                  "sets_won", "sets_lost", "games_won", "games_lost"]

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _make_fast_session(auth_session):
    fast = requests.Session()
    fast.cookies.update(auth_session.cookies)
    fast.headers.update({"User-Agent": config.USER_AGENT})
    return fast


def _fetch_group_html(session, group_id: int):
    url = f"{config.BASE_URL}/cts/grupo_d/{group_id}/"
    try:
        resp = session.get(url, timeout=20, allow_redirects=True)
        if "/accounts/login/" in resp.url:
            return None, "session_expired"
        resp.raise_for_status()
        return resp.text, None
    except Exception as e:
        return None, str(e)


def _compare_standings(live_list, db_list):
    """Returns (discrepancies, only_in_live, only_in_db)."""
    db_by_cta   = {r["team_cta_id"]: r for r in db_list}
    live_by_cta = {r["cta_id"]: r      for r in live_list}

    discrepancies = []
    only_in_live  = []
    only_in_db    = []

    for cta_id, live in live_by_cta.items():
        if cta_id not in db_by_cta:
            only_in_live.append(live["name"])
            continue
        db = db_by_cta[cta_id]
        diffs = {}
        for field in COMPARE_FIELDS:
            lv, dv = live.get(field), db.get(field)
            if lv is None or dv is None:
                continue
            if lv != dv:
                diffs[field] = {"live": lv, "db": dv}
        if diffs:
            discrepancies.append({"team": live["name"], "cta_id": cta_id, "diffs": diffs})

    for cta_id, db in db_by_cta.items():
        if cta_id not in live_by_cta:
            only_in_db.append(db["team_name"])

    return discrepancies, only_in_live, only_in_db


def _compare_fixtures(live_list, db_list):
    """Returns (score_mismatches, missing_in_db) for completed matches."""
    db_by_pair  = {(r["home_cta_id"], r["away_cta_id"]): r for r in db_list}
    mismatches  = []
    missing     = []

    for f in live_list:
        if f["status"] != "completed":
            continue
        pair = (f["home_cta_id"], f["away_cta_id"])
        if pair not in db_by_pair:
            missing.append(f)
            continue
        db_f       = db_by_pair[pair]
        live_score = f"{f['home_score']}-{f['away_score']}"
        db_score   = f"{db_f['home_score'] or ''}-{db_f['away_score'] or ''}"
        if live_score != db_score or db_f["status"] != "completed":
            mismatches.append({
                "home":      db_f["home_team"],
                "away":      db_f["away_team"],
                "date":      f["date"],
                "live":      live_score,
                "db":        db_score,
                "db_status": db_f["status"],
            })

    return mismatches, missing


def _print_group_result(group_label, live_standings, db_standings,
                        disc, only_live, only_db,
                        fix_mismatches, fix_missing,
                        synced, compare_only):
    db_ts = db_standings[0]["scraped_at"][:10] if db_standings else "—"
    print(f"\n  {BOLD}── {group_label}  (DB: {db_ts}) {'─' * 30}{RESET}")

    has_any = bool(disc or only_live or only_db or fix_mismatches or fix_missing)
    if not has_any:
        print(f"  {GREEN}✓ Ya coincide con ctatenis.com{RESET}")
        return

    for d in disc:
        diff_str = "  ".join(
            f"{k}: DB={v['db']} LIVE={v['live']}" for k, v in d["diffs"].items()
        )
        print(f"  {RED}POSICIÓN DIFF{RESET}  {d['team']:<22} {diff_str}")

    for name in only_live:
        print(f"  {YELLOW}SOLO EN LIVE{RESET}   {name}")

    for name in only_db:
        print(f"  {YELLOW}SOLO EN DB  {RESET}   {name}")

    for m in fix_mismatches:
        print(f"  {RED}SCORE DIFF{RESET}     {m['home']} vs {m['away']} ({m['date']})  "
              f"DB={m['db']}  LIVE={m['live']}")

    for f in fix_missing:
        ht = next((s["name"] for s in live_standings if s["cta_id"] == f["home_cta_id"]),
                  str(f["home_cta_id"]))
        at = next((s["name"] for s in live_standings if s["cta_id"] == f["away_cta_id"]),
                  str(f["away_cta_id"]))
        print(f"  {YELLOW}FALTA EN DB{RESET}    {ht} vs {at} ({f['date']}) "
              f"{f['home_score']}-{f['away_score']}")

    if compare_only:
        total = len(disc) + len(only_live) + len(fix_mismatches) + len(fix_missing)
        print(f"  {YELLOW}→ {total} diferencia(s) (no escrito — modo comparación){RESET}")
    elif synced:
        print(f"  {GREEN}✓ Sincronizados: {synced['standings']} equipos, "
              f"{synced['fixtures']} partidos{RESET}")


def _get_league_id(cat_name: str):
    """Lookup leagues.id by categoria_name (e.g. '6M' → 1)."""
    import sqlite3 as _sq3
    try:
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM leagues WHERE categoria_name=? LIMIT 1", (cat_name,)
            ).fetchone()
            return row["id"] if row else None
    except Exception:
        return None


def _sync_group(session, group_id, cat_name, compare_only):
    """Fetch, compare, and optionally write one group. Returns result dict."""
    html, err = _fetch_group_html(session, group_id)
    if err:
        return {"error": err}

    time.sleep(1.5)

    data           = spider.parse_group_page(html)
    live_standings = data["standings"]
    live_fixtures  = data["fixtures"]

    db_standings = database.get_group_standings(group_id)
    db_fixtures  = database.get_group_fixtures(group_id)

    disc, only_live, only_db = _compare_standings(live_standings, db_standings)
    fix_mismatches, fix_missing = _compare_fixtures(live_fixtures, db_fixtures)

    has_diff = bool(disc or only_live or fix_mismatches or fix_missing)
    synced   = None

    if has_diff and not compare_only:
        league_id = _get_league_id(cat_name)
        n_s = 0
        for s in live_standings:
            team_id = database.upsert_team(s["cta_id"], s["name"], league_id)
            database.insert_standings(team_id, {
                "position":   s["position"],
                "played":     s["played"],
                "won":        s["won"],
                "lost":       s["lost"],
                "sets_won":   s["sets_won"],
                "sets_lost":  s["sets_lost"],
                "games_won":  s["games_won"],
                "games_lost": s.get("games_lost"),
                "points":     s["won"],
            }, group_id=group_id)
            n_s += 1

        n_f = 0
        for f in live_fixtures:
            home_team = database.get_team(f["home_cta_id"])
            away_team = database.get_team(f["away_cta_id"]) if f["away_cta_id"] else None
            if not home_team or not away_team:
                continue
            database.upsert_match(
                home_team_id=home_team["id"],
                away_team_id=away_team["id"],
                match_date=f["date"],
                home_score=f["home_score"] or None,
                away_score=f["away_score"] or None,
                status=f["status"],
                group_id=group_id,
                raw_detail={
                    "jornada":    f.get("jornada", ""),
                    "time":       f.get("time", ""),
                    "sede":       f.get("sede", ""),
                    "fixture_id": f.get("fixture_id"),
                },
            )
            n_f += 1

        synced = {"standings": n_s, "fixtures": n_f}

    return {
        "live_standings": live_standings,
        "db_standings":   db_standings,
        "live_fixtures":  live_fixtures,
        "db_fixtures":    db_fixtures,
        "disc":           disc,
        "only_live":      only_live,
        "only_db":        only_db,
        "fix_mismatches": fix_mismatches,
        "fix_missing":    fix_missing,
        "synced":         synced,
        "has_diff":       has_diff,
    }


def main():
    parser = argparse.ArgumentParser(description="Compara y sincroniza DB con ctatenis.com")
    parser.add_argument("--category", "-c", default=None,
                        help="Categoría a procesar (ej: 6M, 5F). Default: todas.")
    parser.add_argument("--compare-only", action="store_true",
                        help="Solo compara, NO escribe a DB.")
    args = parser.parse_args()

    cat_filter = None
    if args.category:
        cat_filter = args.category.upper()
        valid = [c["name"] for c in config.CATEGORIES]
        if cat_filter not in valid:
            print(f"Categoría inválida: '{cat_filter}'. Válidas: {', '.join(valid)}")
            sys.exit(1)

    print(f"{BOLD}Autenticando con ctatenis.com...{RESET}")
    auth_session = auth.get_session()
    if not auth_session:
        print(f"{RED}Error: no se pudo autenticar.{RESET}")
        sys.exit(1)
    session = _make_fast_session(auth_session)

    mode = "COMPARANDO (sin escribir)" if args.compare_only else "SINCRONIZANDO"
    print(f"\n{BOLD}══ {mode}: ctatenis.com → DB {'═' * 30}{RESET}")

    total_groups        = 0
    total_with_diff     = 0
    total_teams_synced  = 0
    total_fix_synced    = 0
    errors              = []

    cats = [c for c in config.CATEGORIES
            if not cat_filter or c["name"] == cat_filter]

    for cat in cats:
        groups = config.GROUPS.get(cat["id"], [])
        print(f"\n{CYAN}{BOLD}Categoría {cat['name']} — {len(groups)} grupo(s){RESET}")

        for grupo_num, group_id in groups:
            group_label = f"{cat['name']}{grupo_num} (id={group_id})"
            total_groups += 1

            result = _sync_group(session, group_id, cat["name"], args.compare_only)

            if "error" in result:
                if result["error"] == "session_expired":
                    print(f"  {YELLOW}Sesión expirada, reautenticando...{RESET}")
                    auth_session = auth.get_session()
                    if not auth_session:
                        print(f"  {RED}Reautenticación fallida — abortando.{RESET}")
                        sys.exit(1)
                    session = _make_fast_session(auth_session)
                    result  = _sync_group(session, group_id, cat["name"], args.compare_only)

                if "error" in result:
                    errors.append(group_label)
                    print(f"  {RED}Error en {group_label}: {result['error']}{RESET}")
                    continue

            if result["has_diff"]:
                total_with_diff += 1
            if result["synced"]:
                total_teams_synced += result["synced"]["standings"]
                total_fix_synced   += result["synced"]["fixtures"]

            _print_group_result(
                group_label,
                result["live_standings"],
                result["db_standings"],
                result["disc"],
                result["only_live"],
                result["only_db"],
                result["fix_mismatches"],
                result["fix_missing"],
                result["synced"],
                args.compare_only,
            )

    sep = "═" * 60
    print(f"\n{BOLD}{sep}{RESET}")
    print(f"{BOLD}RESUMEN{RESET}")
    print(f"  Grupos procesados:      {total_groups}")
    print(f"  Grupos con diferencias: {total_with_diff}")
    if not args.compare_only:
        print(f"  Equipos actualizados:   {total_teams_synced}")
        print(f"  Partidos actualizados:  {total_fix_synced}")
    if errors:
        print(f"  {RED}Errores ({len(errors)}): {', '.join(errors)}{RESET}")
    if total_with_diff == 0:
        print(f"  {GREEN}✓ DB ya estaba correcta (0 diferencias){RESET}")
    elif not args.compare_only:
        print(f"  {GREEN}✓ DB sincronizada{RESET}")
    print(f"{BOLD}{sep}{RESET}\n")


if __name__ == "__main__":
    main()
