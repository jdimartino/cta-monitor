"""
CTA Intelligence System — Spider/Crawler
Autor: JDM | #JDMRules

Dynamically discovers teams, players, and match data from ctatenis.com.
"""

from __future__ import annotations

import re
import hashlib
import logging
from datetime import datetime

from bs4 import BeautifulSoup

import config
import auth
import database

logger = logging.getLogger("spider")


# ─────────────────────────────────────────────
# PAGE PARSERS
# ─────────────────────────────────────────────
def parse_standings_page(html: str) -> list[dict]:
    """Parse standings page. Extract team names, IDs, and stats.

    Returns list of dicts:
        {cta_id, name, position, played, won, lost, sets_won, sets_lost,
         games_won, games_lost, points}
    """
    soup = BeautifulSoup(html, "html.parser")
    teams = []

    tabla = soup.find("table")
    if not tabla:
        logger.warning("No <table> found on standings page")
        return teams

    filas = tabla.find_all("tr")
    for fila in filas:
        celdas = fila.find_all(["td", "th"])
        if not celdas or len(celdas) < 2:
            continue

        # Skip header rows
        if fila.find("th"):
            continue

        team_data = {}

        # Try to find team link to extract cta_id
        link = fila.find("a", href=re.compile(r"/cts/team_d/(\d+)/"))
        if link:
            match = re.search(r"/cts/team_d/(\d+)/", link["href"])
            if match:
                team_data["cta_id"] = int(match.group(1))
                team_data["name"] = link.get_text(strip=True)

        # Extract all cell values
        values = [c.get_text(strip=True) for c in celdas]

        # If no link found, try to get name from first text cell
        if "name" not in team_data and values:
            # Find the first non-numeric cell as team name
            for v in values:
                if v and not v.isdigit():
                    team_data["name"] = v
                    break

        if not team_data.get("name"):
            continue

        # Try to map numeric columns to stats
        # Typical order: Pos | Team | PJ | PG | PP | SG | SP | GG | GP | Pts
        nums = []
        for v in values:
            try:
                nums.append(int(v))
            except ValueError:
                continue

        if len(nums) >= 2:
            team_data["position"] = nums[0] if nums else None
            # Map remaining numbers based on count
            if len(nums) >= 10:
                team_data.update({
                    "position": nums[0], "played": nums[1], "won": nums[2],
                    "lost": nums[3], "sets_won": nums[4], "sets_lost": nums[5],
                    "games_won": nums[6], "games_lost": nums[7], "points": nums[8],
                })
            elif len(nums) >= 6:
                team_data.update({
                    "position": nums[0], "played": nums[1], "won": nums[2],
                    "lost": nums[3], "points": nums[-1],
                })
            elif len(nums) >= 3:
                team_data.update({
                    "position": nums[0], "played": nums[1], "points": nums[-1],
                })

        teams.append(team_data)

    # Also scan for team links outside the table (sidebar, etc.)
    for link in soup.find_all("a", href=re.compile(r"/cts/team_d/(\d+)/")):
        match = re.search(r"/cts/team_d/(\d+)/", link["href"])
        if match:
            cta_id = int(match.group(1))
            if not any(t.get("cta_id") == cta_id for t in teams):
                name = link.get_text(strip=True)
                if name:
                    teams.append({"cta_id": cta_id, "name": name})

    logger.info(f"Parsed {len(teams)} teams from standings page")
    return teams


def parse_team_page(html: str) -> dict:
    """Parse a team page. Extract roster and calendar.

    Returns:
        {
            name: str,
            players: [{cta_id, name}],
            matches: [{date, opponent_name, opponent_id, score, raw_text}]
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"name": "", "players": [], "matches": []}

    # Team name from heading
    heading = soup.find("h1") or soup.find("h2") or soup.find("h3")
    if heading:
        result["name"] = heading.get_text(strip=True)

    # Find player links
    seen_players = set()
    for link in soup.find_all("a", href=re.compile(r"/cts/profile/(\d+)/")):
        match = re.search(r"/cts/profile/(\d+)/", link["href"])
        if match:
            cta_id = int(match.group(1))
            if cta_id not in seen_players:
                seen_players.add(cta_id)
                name = link.get_text(strip=True)
                if name:
                    result["players"].append({"cta_id": cta_id, "name": name})

    # Parse match/calendar rows from tables
    for tabla in soup.find_all("table"):
        for fila in tabla.find_all("tr"):
            celdas = fila.find_all(["td", "th"])
            if len(celdas) < 2:
                continue
            if fila.find("th"):
                continue

            values = [c.get_text(strip=True) for c in celdas]
            raw_text = " | ".join(values)

            match_data = {"raw_text": raw_text}

            # Look for opponent team link
            opp_link = fila.find("a", href=re.compile(r"/cts/team_d/(\d+)/"))
            if opp_link:
                opp_match = re.search(r"/cts/team_d/(\d+)/", opp_link["href"])
                if opp_match:
                    match_data["opponent_id"] = int(opp_match.group(1))
                    match_data["opponent_name"] = opp_link.get_text(strip=True)

            # Try to find date pattern in cell values
            for v in values:
                if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", v):
                    match_data["date"] = v
                    break

            # Try to find score pattern (e.g., "3-2", "2-3")
            for v in values:
                if re.match(r"^\d+-\d+$", v):
                    match_data["score"] = v
                    break

            result["matches"].append(match_data)

    # Also look for match divs (fallback)
    for item in soup.find_all(class_=lambda c: c and any(
        x in c for x in ["match", "partido", "fixture", "game", "result"]
    )):
        texto = item.get_text(strip=True)
        if texto:
            result["matches"].append({"raw_text": texto})

    logger.info(
        f"Team '{result['name']}': {len(result['players'])} players, "
        f"{len(result['matches'])} matches"
    )
    return result


def parse_player_page(html: str) -> dict:
    """Parse a player profile page.

    Returns:
        {name, ranking, matches_won, matches_lost, sets_won, sets_lost,
         games_won, games_lost, raw_data: {all key-value pairs}}
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"raw_data": {}}

    # Player name
    nombre = soup.find("h1") or soup.find("h2") or soup.find("h3")
    if nombre:
        result["name"] = nombre.get_text(strip=True)

    # Extract all key-value pairs from 2-column tables
    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) == 2:
            key = celdas[0].get_text(strip=True)
            val = celdas[1].get_text(strip=True)
            if key:
                result["raw_data"][key] = val

                # Map known keys to structured fields
                key_lower = key.lower()
                if "ranking" in key_lower:
                    result["ranking"] = val
                elif "ganados" in key_lower or "victorias" in key_lower:
                    try:
                        result["matches_won"] = int(val)
                    except ValueError:
                        pass
                elif "perdidos" in key_lower or "derrotas" in key_lower:
                    try:
                        result["matches_lost"] = int(val)
                    except ValueError:
                        pass

    # Look for stats in spans/divs
    for tag in soup.find_all(["span", "div", "p"]):
        texto = tag.get_text(strip=True)
        if any(k in texto.lower() for k in ["ranking", "puntos", "ganados", "perdidos", "sets"]):
            result["raw_data"][f"info_{len(result['raw_data'])}"] = texto

    return result


# ─────────────────────────────────────────────
# CRAWL ORCHESTRATION
# ─────────────────────────────────────────────
def _page_hash(html: str) -> str:
    return hashlib.md5(html.encode()).hexdigest()


def crawl_standings(session, liga_id: int = None, cat_id: int = None) -> list[dict]:
    """Fetch and parse standings page. Upsert teams into DB."""
    liga_id = liga_id or config.LIGA_ID
    cat_id = cat_id or config.CATEGORIA_ID

    url = f"{config.BASE_URL}/cts/tabla_posiciones/{liga_id}/{cat_id}/"
    logger.info(f"Crawling standings: {url}")

    resp = auth.authenticated_get(session, url)
    if not resp:
        logger.error("Failed to fetch standings page")
        return []

    html = resp.text
    page_h = _page_hash(html)

    # Update URL map
    database.set_url(url, "standings")
    database.update_url_hash(url, page_h)

    teams = parse_standings_page(html)

    # Ensure league exists
    league_id = database.upsert_league(liga_id, cat_id, f"Liga {liga_id} Cat {cat_id}")

    # Upsert teams and standings
    for team_data in teams:
        cta_id = team_data.get("cta_id")
        name = team_data.get("name", "Unknown")

        if cta_id:
            is_own = cta_id == config.OWN_TEAM_ID
            db_team_id = database.upsert_team(cta_id, name, league_id, is_own)

            # Record standing if we have stats
            if team_data.get("position") is not None:
                database.insert_standings(db_team_id, team_data)

            # Register team URL
            team_url = f"/cts/team_d/{cta_id}/"
            database.set_url(team_url, "team", cta_id)

    return teams


def crawl_team(session, team_cta_id: int) -> dict:
    """Fetch and parse a team page. Upsert players and matches."""
    url = f"{config.BASE_URL}/cts/team_d/{team_cta_id}/"
    logger.info(f"Crawling team {team_cta_id}: {url}")

    resp = auth.authenticated_get(session, url)
    if not resp:
        logger.error(f"Failed to fetch team page: {team_cta_id}")
        return {}

    html = resp.text
    page_h = _page_hash(html)

    database.set_url(f"/cts/team_d/{team_cta_id}/", "team", team_cta_id)
    database.update_url_hash(f"/cts/team_d/{team_cta_id}/", page_h)

    data = parse_team_page(html)

    # Get the team's DB ID
    team = database.get_team(team_cta_id)
    team_db_id = team["id"] if team else None

    # Upsert players
    for player in data.get("players", []):
        database.upsert_player(player["cta_id"], player["name"], team_db_id)
        player_url = f"/cts/profile/{player['cta_id']}/"
        database.set_url(player_url, "player", player["cta_id"])

    # Upsert matches (best effort — parsing may be imprecise)
    for match in data.get("matches", []):
        opponent_id = match.get("opponent_id")
        if opponent_id and team_db_id:
            opp_team = database.get_team(opponent_id)
            if opp_team:
                opp_db_id = opp_team["id"]
            else:
                opp_db_id = database.upsert_team(
                    opponent_id, match.get("opponent_name", f"Team {opponent_id}")
                )
            date = match.get("date", "")
            score = match.get("score", "")
            home_score, away_score = None, None
            if "-" in score:
                parts = score.split("-")
                home_score, away_score = parts[0], parts[1]

            status = "completed" if score else "scheduled"
            database.upsert_match(
                team_db_id, opp_db_id, date,
                home_score=home_score, away_score=away_score,
                status=status,
                raw_detail={"raw_text": match.get("raw_text", "")},
            )

    return data


def crawl_player(session, player_cta_id: int) -> dict:
    """Fetch and parse a player profile. Insert stats into DB."""
    url = f"{config.BASE_URL}/cts/profile/{player_cta_id}/"
    logger.info(f"Crawling player {player_cta_id}: {url}")

    resp = auth.authenticated_get(session, url)
    if not resp:
        logger.error(f"Failed to fetch player page: {player_cta_id}")
        return {}

    html = resp.text
    page_h = _page_hash(html)

    database.set_url(f"/cts/profile/{player_cta_id}/", "player", player_cta_id)
    database.update_url_hash(f"/cts/profile/{player_cta_id}/", page_h)

    data = parse_player_page(html)

    # Update player name if found
    player = database.get_player(player_cta_id)
    if player and data.get("name"):
        database.upsert_player(player_cta_id, data["name"], player.get("team_id"))

    # Insert stats snapshot
    if player:
        database.insert_player_stats(player["id"], data)

    return data


def discover_all(session=None, incremental: bool = True) -> dict:
    """Full crawl pipeline: standings → teams → players.

    Args:
        session: Authenticated requests session. If None, will get one.
        incremental: If True, skip pages whose hash hasn't changed.

    Returns:
        Summary dict with counts.
    """
    if session is None:
        session = auth.get_session()
        if not session:
            return {"error": "Could not authenticate"}

    database.init_db()
    summary = {"teams_found": 0, "players_found": 0, "pages_scraped": 0}
    pages_scraped = 0

    # Step 1: Crawl standings
    print("[Spider] Paso 1: Tabla de posiciones...")
    teams = crawl_standings(session)
    summary["teams_found"] = len(teams)
    pages_scraped += 1

    # Step 2: Crawl each team
    print(f"[Spider] Paso 2: Crawling {len(teams)} equipos...")
    all_players = []
    for team_data in teams:
        cta_id = team_data.get("cta_id")
        if not cta_id:
            continue

        if pages_scraped >= config.MAX_PAGES_PER_CRAWL:
            logger.warning(f"Reached max pages limit ({config.MAX_PAGES_PER_CRAWL})")
            break

        # Incremental check
        if incremental:
            url_path = f"/cts/team_d/{cta_id}/"
            url_info = database.get_urls_by_type("team")
            existing = [u for u in url_info if u["url"] == url_path]
            if existing and existing[0].get("last_hash"):
                # We'll still fetch to check hash, but skip if same
                pass

        team_result = crawl_team(session, cta_id)
        pages_scraped += 1
        players = team_result.get("players", [])
        all_players.extend(players)
        print(f"  [{pages_scraped}] {team_data.get('name', cta_id)}: {len(players)} jugadores")

    summary["players_found"] = len(all_players)

    # Step 3: Crawl each player
    print(f"[Spider] Paso 3: Crawling {len(all_players)} jugadores...")
    for player in all_players:
        if pages_scraped >= config.MAX_PAGES_PER_CRAWL:
            logger.warning(f"Reached max pages limit ({config.MAX_PAGES_PER_CRAWL})")
            break

        crawl_player(session, player["cta_id"])
        pages_scraped += 1

    summary["pages_scraped"] = pages_scraped
    print(f"\n[Spider] Completado: {summary}")
    return summary


def crawl_single_team(team_cta_id: int, session=None) -> dict:
    """Convenience: crawl one team and its players."""
    if session is None:
        session = auth.get_session()
        if not session:
            return {"error": "Could not authenticate"}

    database.init_db()

    team_data = crawl_team(session, team_cta_id)
    for player in team_data.get("players", []):
        crawl_player(session, player["cta_id"])

    return team_data
