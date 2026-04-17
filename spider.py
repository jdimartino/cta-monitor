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

# Patrones de fecha ordenados de más específico a más general
_DATE_PATTERNS = [
    re.compile(r"\d{4}-\d{2}-\d{2}"),                                   # 2026-04-14
    re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"),                       # 14/04/2026
    re.compile(r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}", re.I),               # 14 de abril de 2026
    re.compile(r"\d{1,2}\s+\w{4,}\s+\d{4}", re.I),                      # 14 abril 2026
    re.compile(r"(?:lun|mar|mié|jue|vie|sáb|dom)\w*[\s.]+\d{1,2}[/-]\d{1,2}", re.I),  # Lun 14/04
]

def _try_parse_date(values: list[str]) -> str:
    """Busca cualquier cadena de fecha en la lista de valores de una fila."""
    full_text = " ".join(values)
    for pat in _DATE_PATTERNS:
        m = pat.search(full_text)
        if m:
            return m.group(0).strip()
    return ""


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
    """Parse /cts/team_d/{id}/ — exact page structure discovered 2026-04-16.

    The page always has exactly 3 tables:
      Table 0: Group standings  cols: Equipo|PJ|PG|PP|P Ave|Set G|Set P|Set Ave|GG|GP|G Ave
      Table 1: Fixtures         cols: Jor.|EquiposFecha|Sede|Resultados
               Resultados has W/L prefix for completed rows: "W TACB: 8 - CLCA: 2"
               Links per row: completed=[create_result, home, away, create_result]
                              pending  =[home, away]
                              BYE      =[self] (sede=='BYE', skipped)
      Table 2: Players          cols: Apellidos,Nombre|Categoria|Ranking

    Returns:
        {name, club, group,
         standings: [{cta_id, name, position, played, won, lost,
                      sets_won, sets_lost, games_won}],
         fixtures:  [{jornada, date, time, home_cta_id, away_cta_id,
                      sede, home_score, away_score, status, fixture_id}],
         players:   [{cta_id, name, category}]}
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"name": "", "club": "", "group": "", "standings": [], "fixtures": [], "players": []}

    # ── Header: club and team abbreviation ──
    h3 = soup.find("h3")
    if h3:
        # "Club: TAC - Club Tachira"
        cm = re.search(r"Club:\s*\S+\s*-\s*(.+)", h3.get_text(strip=True))
        if cm:
            result["club"] = cm.group(1).strip()

    for h4 in soup.find_all("h4"):
        t = h4.get_text(" ", strip=True)
        gm = re.search(r"Grupo:\s*(\S+)", t)
        em = re.search(r"Equipo:\s*(\S+)", t)
        if gm:
            result["group"] = gm.group(1)
        if em:
            result["name"] = em.group(1)

    tables = soup.find_all("table")

    def _num(v):
        try:
            return int(v.replace(",", ".").split(".")[0])
        except (ValueError, IndexError):
            return None

    # ── Table 0: Group standings ──
    if tables:
        for pos_idx, row in enumerate(tables[0].find_all("tr")[1:], start=1):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            link = row.find("a", href=re.compile(r"/cts/team_d/(\d+)/"))
            if not link:
                continue
            m = re.search(r"/cts/team_d/(\d+)/", link["href"])
            if not m:
                continue
            vals = [c.get_text(strip=True) for c in cells]
            # cols: 0=Equipo 1=PJ 2=PG 3=PP 4=P Ave 5=Set G 6=Set P 7=Set Ave 8=GG 9=GP 10=G Ave
            result["standings"].append({
                "cta_id":    int(m.group(1)),
                "name":      link.get_text(strip=True),
                "position":  pos_idx,
                "played":    _num(vals[1]) if len(vals) > 1 else None,
                "won":       _num(vals[2]) if len(vals) > 2 else None,
                "lost":      _num(vals[3]) if len(vals) > 3 else None,
                "sets_won":  _num(vals[5]) if len(vals) > 5 else None,
                "sets_lost": _num(vals[6]) if len(vals) > 6 else None,
                "games_won": _num(vals[8]) if len(vals) > 8 else None,
            })

    # ── Table 1: Fixtures ──
    if len(tables) >= 2:
        for row in tables[1].find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue

            jornada   = cells[0].get_text(strip=True)
            fecha_cell = cells[1].get_text(strip=True)
            sede      = cells[2].get_text(strip=True)
            resultado = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            if sede.upper() == "BYE":
                continue

            all_hrefs  = [a["href"] for a in row.find_all("a", href=True)]
            team_links = [h for h in all_hrefs if "/cts/team_d/" in h]
            res_links  = [h for h in all_hrefs if "/cts/create_result/" in h]

            if len(team_links) < 2:
                continue  # need home + away

            hm = re.search(r"/cts/team_d/(\d+)/", team_links[0])
            am = re.search(r"/cts/team_d/(\d+)/", team_links[1])
            if not hm or not am:
                continue

            home_cta_id = int(hm.group(1))
            away_cta_id = int(am.group(1))
            fixture_id  = None
            if res_links:
                fm = re.search(r"/cts/create_result/(\d+)/", res_links[0])
                if fm:
                    fixture_id = int(fm.group(1))

            date_m   = re.search(r"(\d{1,2}/\d{2})", fecha_cell)
            raw_date = f"{date_m.group(1)}/{datetime.now().year}" if date_m else ""
            time_m   = re.search(r"\d{1,2}:\d{2}\s*[ap]\.m\.", fecha_cell)
            hora     = time_m.group(0).strip() if time_m else ""

            # Strip W/L prefix then parse score
            home_score, away_score = "", ""
            res_clean = re.sub(r"^[WL]\s+", "", resultado).strip()
            if res_clean:
                sm = re.match(r"(\w+):\s*(\d+)\s*-\s*(\w+):\s*(\d+)", res_clean)
                if sm:
                    home_score = sm.group(2)
                    away_score = sm.group(4)

            result["fixtures"].append({
                "jornada":     jornada,
                "date":        raw_date,
                "time":        hora,
                "home_cta_id": home_cta_id,
                "away_cta_id": away_cta_id,
                "sede":        sede,
                "home_score":  home_score,
                "away_score":  away_score,
                "status":      "completed" if home_score else "scheduled",
                "fixture_id":  fixture_id,
            })

    # ── Table 2: Players ──
    if len(tables) >= 3:
        for row in tables[2].find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            link = row.find("a", href=re.compile(r"/cts/profile/(\d+)/"))
            if not link:
                continue
            pm = re.search(r"/cts/profile/(\d+)/", link["href"])
            if not pm:
                continue
            category = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            result["players"].append({
                "cta_id":   int(pm.group(1)),
                "name":     link.get_text(strip=True),
                "category": category,
            })

    logger.info(
        f"parse_team_page '{result['name']}': "
        f"{len(result['standings'])} standings, "
        f"{len(result['fixtures'])} fixtures, "
        f"{len(result['players'])} players"
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

    # Upsert group standings from Table 0
    for s in data.get("standings", []):
        db_team_id = database.upsert_team(s["cta_id"], s["name"])
        database.insert_standings(db_team_id, {
            "position":  s["position"],
            "played":    s["played"],
            "won":       s["won"],
            "lost":      s["lost"],
            "sets_won":  s["sets_won"],
            "sets_lost": s["sets_lost"],
            "games_won": s["games_won"],
            "points":    s["won"],  # no Pts column; use wins as proxy
        })

    # Upsert fixtures from Table 1 (precise home/away from links)
    for f in data.get("fixtures", []):
        home_team = database.get_team(f["home_cta_id"])
        away_team = database.get_team(f["away_cta_id"]) if f["away_cta_id"] else None
        if not home_team or not away_team:
            continue
        database.upsert_match(
            home_team["id"], away_team["id"],
            f["date"],
            home_score=f["home_score"] or None,
            away_score=f["away_score"] or None,
            status=f["status"],
        )

    # Upsert players from Table 2
    for player in data.get("players", []):
        database.upsert_player(player["cta_id"], player["name"], team_db_id)
        database.set_url(f"/cts/profile/{player['cta_id']}/", "player", player["cta_id"])

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


def parse_group_page(html: str) -> dict:
    """Parse /cts/grupo_d/{id}/ — 2 tablas exactas.

    Tabla 0: Posiciones  — Equipo|PJ|PG|PP|P Ave|Set G|Set P|Set Ave|GG|GP|G Ave
    Tabla 1: Calendario  — Jor.|FechaEquipos|Sede|Resultados

    Returns:
        {
          standings: [{cta_id, name, position, played, won, lost,
                       p_ave, sets_won, sets_lost, games_won}],
          fixtures:  [{jornada, date, time, home_cta_id, away_cta_id,
                       sede, home_score, away_score, status, fixture_id}]
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    result = {"standings": [], "fixtures": []}

    # ── Tabla 0: Posiciones ──
    if len(tables) >= 1:
        for pos_idx, row in enumerate(tables[0].find_all("tr")[1:], start=1):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            link = row.find("a", href=re.compile(r"/cts/team_d/(\d+)/"))
            if not link:
                continue
            m = re.search(r"/cts/team_d/(\d+)/", link["href"])
            if not m:
                continue

            vals = [c.get_text(strip=True) for c in cells]
            # Convertir números con coma decimal
            def _num(v):
                try:
                    return int(v.replace(",", ".").split(".")[0])
                except (ValueError, IndexError):
                    return None

            def _float(v):
                try:
                    return float(v.replace(",", "."))
                except ValueError:
                    return None

            # Columnas: 0=Equipo 1=PJ 2=PG 3=PP 4=P Ave 5=Set G 6=Set P 7=Set Ave 8=GG 9=GP 10=G Ave
            result["standings"].append({
                "cta_id":    int(m.group(1)),
                "name":      link.get_text(strip=True),
                "position":  pos_idx,
                "played":    _num(vals[1]) if len(vals) > 1 else None,
                "won":       _num(vals[2]) if len(vals) > 2 else None,
                "lost":      _num(vals[3]) if len(vals) > 3 else None,
                "p_ave":     _float(vals[4]) if len(vals) > 4 else None,
                "sets_won":  _num(vals[5]) if len(vals) > 5 else None,
                "sets_lost": _num(vals[6]) if len(vals) > 6 else None,
                "games_won": _num(vals[8]) if len(vals) > 8 else None,
            })

    # ── Tabla 1: Calendario ──
    if len(tables) >= 2:
        for row in tables[1].find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            vals = [c.get_text(strip=True) for c in cells]
            jornada     = vals[0] if vals else ""
            fecha_cell  = vals[1] if len(vals) > 1 else ""
            sede        = vals[2] if len(vals) > 2 else ""
            resultado   = vals[3] if len(vals) > 3 else ""

            # BYE
            if sede.upper() == "BYE":
                continue

            # Links: [#, /team_d/home, /team_d/away, /create_result/id]
            links = [a["href"] for a in row.find_all("a", href=True)]
            home_cta_id, away_cta_id, fixture_id = None, None, None
            for href in links:
                tm = re.search(r"/cts/team_d/(\d+)/", href)
                if tm:
                    if home_cta_id is None:
                        home_cta_id = int(tm.group(1))
                    elif away_cta_id is None:
                        away_cta_id = int(tm.group(1))
                fm = re.search(r"/cts/create_result/(\d+)/", href)
                if fm:
                    fixture_id = int(fm.group(1))

            if home_cta_id is None:
                continue

            # Fecha DD/MM dentro de FechaEquipos
            date_m = re.search(r"(\d{1,2}/\d{2})", fecha_cell)
            raw_date = date_m.group(1) if date_m else ""
            # Agregar año actual si hay fecha
            if raw_date:
                current_year = datetime.now().year
                raw_date = f"{raw_date}/{current_year}"  # → "15/03/2026"

            # Hora
            time_m = re.search(r"\d{1,2}:\d{2}\s*[ap]\.m\.", fecha_cell)
            hora = time_m.group(0).strip() if time_m else ""

            # Resultado → score
            home_score, away_score = "", ""
            if resultado:
                sm = re.match(r"(\w+):\s*(\d+)\s*-\s*(\w+):\s*(\d+)", resultado)
                if sm:
                    home_score = sm.group(2)
                    away_score = sm.group(4)

            status = "completed" if home_score else "scheduled"

            result["fixtures"].append({
                "jornada":      jornada,
                "date":         raw_date,
                "time":         hora,
                "home_cta_id":  home_cta_id,
                "away_cta_id":  away_cta_id,
                "sede":         sede,
                "home_score":   home_score,
                "away_score":   away_score,
                "status":       status,
                "fixture_id":   fixture_id,
            })

    logger.info(
        f"parse_group_page: {len(result['standings'])} equipos, "
        f"{len(result['fixtures'])} fixtures"
    )
    return result


def crawl_group(group_id: int, session=None) -> dict:
    """Crawl /cts/grupo_d/{group_id}/ y guarda posiciones + fixtures en la DB."""
    if session is None:
        session = auth.get_session()
        if not session:
            return {"error": "Could not authenticate"}

    url = f"{config.BASE_URL}/cts/grupo_d/{group_id}/"
    logger.info(f"[Group] Crawling {url}")
    resp = auth.authenticated_get(session, url)
    data = parse_group_page(resp.text)

    # Upsert standings
    for s in data["standings"]:
        team_id = database.upsert_team(s["cta_id"], s["name"])
        database.insert_standings(team_id, {
            "position":   s["position"],
            "played":     s["played"],
            "won":        s["won"],
            "lost":       s["lost"],
            "sets_won":   s["sets_won"],
            "sets_lost":  s["sets_lost"],
            "games_won":  s["games_won"],
            "points":     s["won"],   # sin columna Pts, usamos victorias
        })

    # Upsert fixtures
    saved = 0
    for f in data["fixtures"]:
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
        )
        saved += 1

    logger.info(f"[Group] Guardados: {len(data['standings'])} standings, {saved} fixtures")
    return {"standings": len(data["standings"]), "fixtures": saved}


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
