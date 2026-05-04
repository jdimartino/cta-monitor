"""
CTA Intelligence System — Spider/Crawler
Autor: JDM | #JDMRules

Dynamically discovers teams, players, and match data from ctatenis.com.
"""

from __future__ import annotations

import json
import re
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
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
    """Parse /cts/team_d/{id}/ — redesigned site (2026-04).

    Primary path uses CSS classes from the new design:
      .team-hero (code, club, meta items), .team-kpi (label/value/sub),
      .form-card .form-box.[w|l|d], .match-row (.match-jor-*, .match-code.is-us,
      .match-sede-chip, .match-venue-label, .match-result-pill), .match-bye-label,
      #jugadores-table tbody tr (avatar img + profile link + cells).

    Fallback path handles the legacy 3-table layout.

    Returns:
        {name, club, group,
         captain_name, subcaptain_name,
         p_ave, set_ave, protests_used, protests_total, recent_form,
         bye_teams,
         standings: [{cta_id, name, position, played, won, lost,
                      sets_won, sets_lost, games_won, games_lost}],
         fixtures:  [{jornada, date, time, home_cta_id, away_cta_id,
                      sede, home_score, away_score, status, fixture_id}],
         players:   [{cta_id, name, category, photo_url, form_str, ranking}]}
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "name": "", "club": "", "group": "",
        "captain_name": None, "subcaptain_name": None,
        "p_ave": None, "set_ave": None,
        "protests_used": None, "protests_total": None,
        "recent_form": None,
        "bye_teams": [],
        "standings": [], "fixtures": [], "players": [],
    }

    # ── Hero (new design) ──
    hero = soup.select_one(".team-hero")
    if hero:
        code_el = hero.select_one(".team-hero-code, .team-hero-tile")
        if code_el:
            result["name"] = code_el.get_text(strip=True)
        club_el = hero.select_one(".team-hero-club")
        if club_el:
            # "TAC · Club Tachira"  → "Club Tachira"
            txt = club_el.get_text(" ", strip=True)
            m = re.search(r"[·\-]\s*(.+)$", txt)
            result["club"] = m.group(1).strip() if m else txt

        for item in hero.select(".team-hero-meta-item"):
            lbl_el = item.select_one(".label")
            val_el = item.select_one(".value")
            if not lbl_el or not val_el:
                continue
            lbl = lbl_el.get_text(strip=True).lower()
            val = val_el.get_text(strip=True)
            if lbl.startswith("modalidad"):
                # Modalidad may override name if name is empty
                if not result["name"]:
                    result["name"] = val
            elif lbl.startswith("grupo"):
                result["group"] = val
            elif lbl.startswith("capit"):
                result["captain_name"] = val
            elif lbl.startswith("sub"):
                result["subcaptain_name"] = val

    # ── Fallback header (old design) ──
    if not result["club"]:
        h3 = soup.find("h3")
        if h3:
            cm = re.search(r"Club:\s*\S+\s*-\s*(.+)", h3.get_text(strip=True))
            if cm:
                result["club"] = cm.group(1).strip()
    if not result["name"] or not result["group"]:
        for h4 in soup.find_all("h4"):
            t = h4.get_text(" ", strip=True)
            gm = re.search(r"Grupo:\s*(\S+)", t)
            em = re.search(r"Equipo:\s*(\S+)", t)
            if gm and not result["group"]:
                result["group"] = gm.group(1)
            if em and not result["name"]:
                result["name"] = em.group(1)

    # ── KPI cards (new design) ──
    def _parse_float(txt):
        if not txt:
            return None
        m = re.search(r"([\d]+[.,]?\d*)", txt)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None

    for kpi in soup.select(".team-kpi"):
        lbl_el = kpi.select_one(".label")
        val_el = kpi.select_one(".value")
        sub_el = kpi.select_one(".sub")
        if not lbl_el or not val_el:
            continue
        lbl = lbl_el.get_text(strip=True).lower()
        val_txt = val_el.get_text(strip=True)
        sub_txt = sub_el.get_text(" ", strip=True) if sub_el else ""
        if "p ave" in lbl:
            result["p_ave"] = _parse_float(val_txt)
        elif "set ave" in lbl:
            result["set_ave"] = _parse_float(val_txt)
        elif "protesta" in lbl:
            used = _parse_float(val_txt)
            result["protests_used"] = int(used) if used is not None else None
            tm = re.search(r"de\s+(\d+)", sub_txt)
            if tm:
                result["protests_total"] = int(tm.group(1))

    # ── Recent form ──
    form_boxes = soup.select(".form-card .form-box")
    if form_boxes:
        letters = []
        for b in form_boxes:
            classes = b.get("class") or []
            if "w" in classes:
                letters.append("W")
            elif "l" in classes:
                letters.append("L")
            elif "d" in classes:
                letters.append("D")
            else:
                letters.append(b.get_text(strip=True)[:1].upper() or "?")
        result["recent_form"] = "".join(letters)

    # ── Bye fixtures (captured before match rows so we can skip those rows below) ──
    for b in soup.select(".match-bye-label"):
        m = re.match(r"(\w+)\s+descansa", b.get_text(strip=True))
        if not m:
            continue
        team_code = m.group(1)
        # Try to grab the parent row's jornada/date
        parent = b.find_parent(class_="match-row")
        jornada = ""
        raw_date = ""
        if parent:
            jor_el = parent.select_one(".match-jor-num, .match-jornada-num")
            date_el = parent.select_one(".match-jor-date, .match-date")
            if jor_el:
                jornada = jor_el.get_text(strip=True)
            if date_el:
                date_txt = date_el.get_text(" ", strip=True)
                date_m = re.search(r"(\d{1,2}/\d{1,2})", date_txt)
                if date_m:
                    raw_date = f"{date_m.group(1)}/{datetime.now().year}"
        result["bye_teams"].append({"team": team_code, "jornada": jornada, "date": raw_date})

    # ── Fixtures via .match-row (new design) ──
    for mr in soup.select(".match-row"):
        team_links = mr.select("a[href*='/cts/team_d/']")
        if len(team_links) < 2:
            continue
        hm = re.search(r"/cts/team_d/(\d+)/", team_links[0].get("href") or "")
        am = re.search(r"/cts/team_d/(\d+)/", team_links[1].get("href") or "")
        if not hm or not am:
            continue
        jor_el = mr.select_one(".match-jor-num, .match-jornada-num")
        date_el = mr.select_one(".match-jor-date, .match-date")
        sede_el = mr.select_one(".match-sede-chip")
        result_el = mr.select_one(".match-result-pill")
        create_link = mr.select_one("a[href*='/cts/create_result/']")

        jornada = jor_el.get_text(strip=True) if jor_el else ""
        date_txt = date_el.get_text(" ", strip=True) if date_el else ""
        date_m = re.search(r"(\d{1,2}/\d{1,2})", date_txt)
        raw_date = f"{date_m.group(1)}/{datetime.now().year}" if date_m else ""
        time_m = re.search(r"\d{1,2}:\d{2}\s*[ap]\.m\.", date_txt)
        hora = time_m.group(0).strip() if time_m else ""
        sede = sede_el.get_text(strip=True) if sede_el else ""

        home_score, away_score = "", ""
        if result_el:
            rtxt = result_el.get_text(" ", strip=True)
            sm = re.search(r"(\w+)\s*(\d+)\s*[–\-]\s*(\w+)\s*(\d+)", rtxt)
            if sm:
                home_score = sm.group(2)
                away_score = sm.group(4)

        fixture_id = None
        if create_link:
            fm = re.search(r"/cts/create_result/(\d+)/", create_link.get("href") or "")
            if fm:
                fixture_id = int(fm.group(1))

        result["fixtures"].append({
            "jornada":     jornada,
            "date":        raw_date,
            "time":        hora,
            "home_cta_id": int(hm.group(1)),
            "away_cta_id": int(am.group(1)),
            "sede":        sede,
            "home_score":  home_score,
            "away_score":  away_score,
            "status":      "completed" if home_score else "scheduled",
            "fixture_id":  fixture_id,
        })

    # ── Roster via #jugadores-table (new design) ──
    jt = soup.select_one("#jugadores-table")
    if jt:
        for row in jt.select("tbody tr"):
            link = row.select_one("a[href*='/cts/profile/']")
            if not link:
                continue
            pm = re.search(r"/cts/profile/(\d+)/", link.get("href") or "")
            if not pm:
                continue
            img = row.select_one("img")
            photo_url = img.get("src") if img else None
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            # cells: [name, form_str, category, ranking]
            name = link.get_text(strip=True) or (cells[0] if cells else "")
            form_str = cells[1] if len(cells) > 1 else ""
            category = cells[2] if len(cells) > 2 else ""
            ranking_txt = cells[3] if len(cells) > 3 else ""
            ranking_val = None
            rm = re.search(r"([\d]+[.,]?\d*)", ranking_txt.replace(".", ""))
            if rm:
                try:
                    ranking_val = float(rm.group(1).replace(",", "."))
                except ValueError:
                    pass
            result["players"].append({
                "cta_id":    int(pm.group(1)),
                "name":      name,
                "category":  category,
                "photo_url": photo_url,
                "form_str":  form_str if form_str != "—" else "",
                "ranking":   ranking_val,
            })

    tables = soup.find_all("table")

    def _num(v):
        try:
            return int(v.replace(",", ".").split(".")[0])
        except (ValueError, IndexError):
            return None

    # ── Table 0: Group standings (header-keyed; supports old and new column sets) ──
    standings_table = soup.select_one("table.pos-table") or (tables[0] if tables else None)
    if standings_table:
        rows_all = standings_table.find_all("tr")
        if rows_all:
            head_cells = rows_all[0].find_all(["th", "td"])
            headers = [h.get_text(" ", strip=True).lower() for h in head_cells]

            def _idx(*needles):
                for n in needles:
                    for i, h in enumerate(headers):
                        if n in h:
                            return i
                return -1

            i_pj    = _idx("pj", "partidos jugados")
            i_pg    = _idx("pg", "partidos ganados")
            i_pp    = _idx("pp", "partidos perdidos")
            i_setg  = _idx("set g", "sets g")
            i_setp  = _idx("set p", "sets p")
            i_gg    = _idx("gg", "games g")
            i_gp    = _idx("gp", "games p")

            for pos_idx, row in enumerate(rows_all[1:], start=1):
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                link = row.find("a", href=re.compile(r"/cts/team_d/(\d+)/"))
                if not link:
                    continue
                m = re.search(r"/cts/team_d/(\d+)/", link["href"])
                if not m:
                    continue
                vals = [c.get_text(" ", strip=True) for c in cells]

                def _val(i):
                    return _num(vals[i]) if 0 <= i < len(vals) else None

                result["standings"].append({
                    "cta_id":     int(m.group(1)),
                    "name":       link.get_text(strip=True),
                    "position":   pos_idx,
                    "played":     _val(i_pj),
                    "won":        _val(i_pg),
                    "lost":       _val(i_pp),
                    "sets_won":   _val(i_setg),
                    "sets_lost":  _val(i_setp),
                    "games_won":  _val(i_gg),
                    "games_lost": _val(i_gp),
                })

    # ── Table 1: Fixtures (fallback to legacy table layout) ──
    if not result["fixtures"] and len(tables) >= 2:
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

    # ── Table 2: Players (fallback to legacy table layout) ──
    if not result["players"] and len(tables) >= 3:
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

    # Fallback: if table-based parser found no players, scan entire page for profile links
    # (handles redesigned team pages where players moved to div-based layout)
    if not result["players"]:
        seen_ids: set[int] = set()
        for link in soup.find_all("a", href=re.compile(r"/cts/profile/(\d+)/")):
            pm = re.search(r"/cts/profile/(\d+)/", link["href"])
            if not pm:
                continue
            name = link.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            cta_id = int(pm.group(1))
            if cta_id in seen_ids:
                continue
            seen_ids.add(cta_id)
            result["players"].append({
                "cta_id":   cta_id,
                "name":     name,
                "category": "",
            })

    logger.info(
        f"parse_team_page '{result['name']}': "
        f"{len(result['standings'])} standings, "
        f"{len(result['fixtures'])} fixtures, "
        f"{len(result['players'])} players"
    )
    return result


def parse_player_page(html: str) -> dict:
    """Parse a player profile page (redesigned 2026-04).

    Returns:
        {name, ranking, ranking_delta, matches_won, matches_lost,
         sets_won, sets_lost, games_won, games_lost,
         photo_url, club_acronym, email, phone, cedula, birth_date,
         chips: [str], estado, modalidades,
         ranking_history: [{jornada, ranking}],
         match_history: [{...}],
         raw_data: {all key-value pairs}}
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "raw_data": {}, "match_history": [],
        "photo_url": None, "club_acronym": None,
        "email": None, "phone": None, "cedula": None, "birth_date": None,
        "chips": [], "estado": None, "modalidades": None,
        "ranking_delta": None, "ranking_history": [],
    }

    # ── Header (new design) ──
    name_el = soup.select_one(".profile-name") or soup.select_one("h1") or soup.select_one("h2")
    if name_el:
        result["name"] = name_el.get_text(" ", strip=True)

    avatar = soup.select_one(".profile-avatar img")
    if avatar:
        result["photo_url"] = avatar.get("src")

    eyebrow = soup.select_one(".profile-eyebrow")
    if eyebrow:
        em = re.search(r"Afiliado\s*[·\-]?\s*(\w+)", eyebrow.get_text(" ", strip=True))
        if em:
            result["club_acronym"] = em.group(1)

    # ── Chips (modalidad/categoría/club) ──
    result["chips"] = [c.get_text(strip=True) for c in soup.select(".profile-chip") if c.get_text(strip=True)]

    # ── Contact / PII ──
    contact_root = soup.select_one(".profile-contact")
    if contact_root:
        mail = contact_root.select_one('a[href^="mailto:"]')
        if mail:
            result["email"] = (mail.get("href") or "").replace("mailto:", "").strip() or mail.get_text(strip=True)
        tel = contact_root.select_one('a[href^="tel:"]')
        if tel:
            result["phone"] = (tel.get("href") or "").replace("tel:", "").strip() or tel.get_text(strip=True)
        for it in contact_root.select(".profile-contact-item"):
            txt = it.get_text(" ", strip=True)
            cm = re.search(r"C\.?\s*I\.?\s*([\d.\-]+)", txt)
            if cm and not result["cedula"]:
                result["cedula"] = re.sub(r"\D", "", cm.group(1))
            dm = re.search(r"(\d{2}/\d{2}/\d{4})", txt)
            if dm and not result["birth_date"]:
                result["birth_date"] = dm.group(1)

    # ── Ranking + delta ──
    rank_card = soup.select_one(".profile-rank")
    if rank_card:
        rval = rank_card.select_one(".value")
        if rval:
            rtxt = rval.get_text(strip=True)
            rm = re.search(r"([\d]+[.,]?\d*)", rtxt.replace(".", ""))
            if rm:
                try:
                    result["ranking"] = float(rm.group(1).replace(",", "."))
                except ValueError:
                    result["ranking"] = rtxt
        delta = rank_card.select_one(".delta")
        if delta:
            dtxt = delta.get_text(" ", strip=True)
            dm = re.search(r"([▲▼])?\s*([+\-]?[\d]+[,.]?\d*)", dtxt)
            if dm:
                sign = -1 if (dm.group(1) == "▼" or "-" in dm.group(2)) else 1
                num = re.sub(r"[+\-]", "", dm.group(2)).replace(",", ".")
                try:
                    result["ranking_delta"] = sign * float(num)
                except ValueError:
                    pass

    # ── Status card ("Aprobado") ──
    for card in soup.select(".status-card"):
        title = card.select_one(".card-title") or card.select_one("h3, h4")
        if title:
            result["estado"] = title.get_text(strip=True)
            break

    # Extract all key-value pairs from 2-column tables
    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) == 2:
            key = celdas[0].get_text(strip=True)
            val = celdas[1].get_text(strip=True)
            if key:
                result["raw_data"][key] = val

                key_lower = key.lower()
                if "ranking" in key_lower:
                    result["ranking"] = val
                elif "partido" in key_lower and ("ganado" in key_lower or "victoria" in key_lower):
                    try:
                        result["matches_won"] = int(val)
                    except ValueError:
                        pass
                elif "partido" in key_lower and ("perdido" in key_lower or "derrota" in key_lower):
                    try:
                        result["matches_lost"] = int(val)
                    except ValueError:
                        pass
                elif ("ganado" in key_lower or "victoria" in key_lower) and "set" not in key_lower and "juego" not in key_lower:
                    try:
                        result["matches_won"] = int(val)
                    except ValueError:
                        pass
                elif ("perdido" in key_lower or "derrota" in key_lower) and "set" not in key_lower and "juego" not in key_lower:
                    try:
                        result["matches_lost"] = int(val)
                    except ValueError:
                        pass
                elif "set" in key_lower and ("ganado" in key_lower or "won" in key_lower):
                    try:
                        result["sets_won"] = int(val)
                    except ValueError:
                        pass
                elif "set" in key_lower and ("perdido" in key_lower or "lost" in key_lower):
                    try:
                        result["sets_lost"] = int(val)
                    except ValueError:
                        pass
                elif "juego" in key_lower and ("ganado" in key_lower or "won" in key_lower):
                    try:
                        result["games_won"] = int(val)
                    except ValueError:
                        pass
                elif "juego" in key_lower and ("perdido" in key_lower or "lost" in key_lower):
                    try:
                        result["games_lost"] = int(val)
                    except ValueError:
                        pass

    # Extract stats from new KPI cards (.profile-kpi)
    for kpi in soup.select(".profile-kpi"):
        label = kpi.select_one(".label")
        value = kpi.select_one(".value")
        sub = kpi.select_one(".sub")
        if not label:
            continue
        lbl_text = label.get_text(strip=True).lower()
        val_text = value.get_text(strip=True) if value else ""
        sub_text = sub.get_text(strip=True).lower() if sub else ""

        if "partidos" in lbl_text:
            sm = re.search(r"(\d+)\s*g\s*[·\.]?\s*(\d+)\s*p", sub_text)
            if sm:
                result["matches_won"] = int(sm.group(1))
                result["matches_lost"] = int(sm.group(2))
        elif "ranking" in lbl_text and val_text and result.get("ranking") is None:
            rm = re.search(r"([\d]+[.,]?\d*)", val_text)
            if rm:
                try:
                    result["ranking"] = float(rm.group(1).replace(",", "."))
                except ValueError:
                    result["ranking"] = val_text
        elif "modalidad" in lbl_text:
            try:
                result["modalidades"] = int(re.sub(r"\D", "", val_text))
            except ValueError:
                pass
        elif "win rate" in lbl_text or "winrate" in lbl_text:
            wm = re.search(r"(\d+)", val_text)
            if wm:
                result["win_rate"] = int(wm.group(1))

    # ── Ranking history (chart data) ──
    for sc in soup.find_all("script"):
        if not sc.string:
            continue
        if "raw" not in sc.string:
            continue
        m = re.search(r"raw\s*=\s*\[(.*?)\]\s*;", sc.string, re.DOTALL)
        if not m:
            continue
        for jm in re.finditer(r'\["?(J\d+)"?\s*,\s*([\d.]+)\]', m.group(1)):
            try:
                result["ranking_history"].append({
                    "jornada": jm.group(1),
                    "ranking": float(jm.group(2)),
                })
            except ValueError:
                pass
        if result["ranking_history"]:
            break

    # Look for stats in spans/divs — also extract ranking from "Rank1376,59" pattern
    for tag in soup.find_all(["span", "div", "p"]):
        texto = tag.get_text(strip=True)
        if any(k in texto.lower() for k in ["ranking", "puntos", "ganados", "perdidos", "sets"]):
            result["raw_data"][f"info_{len(result['raw_data'])}"] = texto
        # ctatenis.com displays ranking as "Rank1376,59" or "Rank 1376,59"
        if result.get("ranking") is None and "rank" in texto.lower():
            rm = re.search(r"[Rr]ank\s*([\d]+[,.][\d]+)", texto)
            if rm:
                result["ranking"] = rm.group(1).replace(",", ".")

    # ── Match history (8-column .history-row layout) ──
    for row in soup.select(".history-row"):
        classes = row.get("class") or []
        if "separator-row" in classes:
            continue

        cols = row.find_all("div", recursive=False)
        # Skip header row (.history-thead has no data, just labels)
        if "history-thead" in classes or "history-head" in classes:
            continue

        entry = {
            "rubber_type":    "singles",
            "is_refuerzo":    1 if "refuerzo" in classes else 0,
            "partner_name":   None,
            "opponent_name":  None,
            "opponent_cta_id": None,
            "score":          None,
            "result":         None,
            "match_date":     None,
            "season":         None,
            "category_match": None,
            "club":           None,
            "vs_club":        None,
            "ranking_after":  None,
            "jornada":        None,
        }

        # Col 0: Jornada (J02) + chip Dobles/Singles
        if len(cols) > 0:
            txt0 = cols[0].get_text(" ", strip=True)
            jm = re.search(r"(J\d+)", txt0)
            if jm:
                entry["jornada"] = jm.group(1)
            if re.search(r"dobles", txt0, re.I):
                entry["rubber_type"] = "doubles"

        # Col 1: Season + Category (e.g. "2026T1" / "5M")
        if len(cols) > 1:
            sub_divs = cols[1].find_all("div")
            if len(sub_divs) >= 2:
                entry["season"] = sub_divs[0].get_text(strip=True)
                entry["category_match"] = sub_divs[1].get_text(strip=True)
            else:
                txt1 = cols[1].get_text(" ", strip=True)
                tm = re.search(r"(\d{4}T[12])\s*[/·\-]?\s*(\S+)?", txt1)
                if tm:
                    entry["season"] = tm.group(1)
                    if tm.group(2):
                        entry["category_match"] = tm.group(2)
            entry["match_date"] = entry["season"]  # legacy compat: existing column "match_date"

        # Col 2: own club for this match (e.g. TACA + team_d link)
        if len(cols) > 2:
            club_link = cols[2].select_one('a[href*="/cts/team_d/"]')
            if club_link:
                entry["club"] = club_link.get_text(strip=True)
            else:
                entry["club"] = cols[2].get_text(strip=True)

        # Col 3: Partner (singles → empty; doubles → 1 profile link)
        if len(cols) > 3:
            plink = cols[3].select_one('a[href*="/cts/profile/"]')
            if plink:
                entry["partner_name"] = plink.get_text(strip=True)

        # Col 4: Opponents (1 in singles, 2 in doubles)
        if len(cols) > 4:
            opp_links = cols[4].select('a[href*="/cts/profile/"]')
            if opp_links:
                names = [a.get_text(strip=True) for a in opp_links]
                entry["opponent_name"] = " · ".join(names)
                m = re.search(r"/cts/profile/(\d+)/", opp_links[0].get("href") or "")
                if m:
                    entry["opponent_cta_id"] = int(m.group(1))

        # Col 5: vs_club (rival club code, e.g. CSCA + team_d link)
        if len(cols) > 5:
            vlink = cols[5].select_one('a[href*="/cts/team_d/"]')
            if vlink:
                entry["vs_club"] = vlink.get_text(strip=True)
            else:
                entry["vs_club"] = cols[5].get_text(strip=True)

        # Col 6: Score pill (W/L + score)
        if len(cols) > 6:
            pill = cols[6].select_one(".match-result-pill") or cols[6]
            ptxt = pill.get_text(" ", strip=True)
            sm = re.match(r"^\s*([WLDwld])\s+(.+)$", ptxt)
            if sm:
                entry["result"] = sm.group(1).upper()
                entry["score"] = sm.group(2).strip()
            elif ptxt:
                entry["score"] = ptxt

        # Col 7: Ranking after match
        if len(cols) > 7:
            rtxt = cols[7].get_text(strip=True)
            rm = re.search(r"([\d]+[.,]?\d*)", rtxt)
            if rm:
                try:
                    entry["ranking_after"] = float(rm.group(1).replace(",", "."))
                except ValueError:
                    pass

        if entry.get("opponent_name") or entry.get("score") or entry.get("jornada"):
            result["match_history"].append(entry)

    # No KPI card for sets in new HTML — compute from match history scores
    if result.get("sets_won") is None and result.get("match_history"):
        sw = sl = 0
        for entry in result["match_history"]:
            for part in re.split(r"[,\s]+", entry.get("score", "") or ""):
                sm_set = re.match(r"(\d+)-(\d+)", part)
                if sm_set:
                    a, b = int(sm_set.group(1)), int(sm_set.group(2))
                    if a > b:
                        sw += 1
                    elif b > a:
                        sl += 1
        if sw or sl:
            result["sets_won"] = sw
            result["sets_lost"] = sl

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

    # Ensure league exists — look up gender/level from CATEGORIES
    cat_info = next((c for c in config.CATEGORIES if c["id"] == cat_id), None)
    league_id = database.upsert_league(
        liga_id, cat_id,
        name=cat_info["name"] if cat_info else f"Liga {liga_id} Cat {cat_id}",
        gender=cat_info["gender"] if cat_info else None,
        level=cat_info["level"] if cat_info else None,
        categoria_name=cat_info["name"] if cat_info else None,
    )

    # Upsert teams and standings
    for team_data in teams:
        cta_id = team_data.get("cta_id")
        name = team_data.get("name", "Unknown")

        if cta_id:
            is_own = cta_id == config.OWN_TEAM_ID
            # Don't overwrite own team's league when it appears as nav widget in foreign categories
            team_league_id = league_id if (not is_own or cat_id == config.CATEGORIA_ID) else None
            db_team_id = database.upsert_team(cta_id, name, team_league_id, is_own)

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

    # Upsert players from roster (with avatar)
    for player in data.get("players", []):
        database.upsert_player(player["cta_id"], player["name"], team_db_id)
        database.set_url(f"/cts/profile/{player['cta_id']}/", "player", player["cta_id"])
        if player.get("photo_url"):
            db_player = database.get_player(player["cta_id"])
            if db_player:
                database.upsert_player_meta(db_player["id"], photo_url=player["photo_url"])

    # Persist team meta (captains, protests, p_ave, set_ave, recent_form)
    if team_db_id:
        meta_fields = {
            "captain_name":    data.get("captain_name"),
            "subcaptain_name": data.get("subcaptain_name"),
            "p_ave":           data.get("p_ave"),
            "set_ave":         data.get("set_ave"),
            "protests_used":   data.get("protests_used"),
            "protests_total":  data.get("protests_total"),
            "recent_form":     data.get("recent_form"),
        }
        # Resolve captain/subcaptain names → player_id (only if name matches a roster member)
        for role_name, fk in (("captain_name", "captain_player_id"), ("subcaptain_name", "subcaptain_player_id")):
            n = meta_fields.get(role_name)
            if n:
                p = database.get_player_by_name_in_team(n, team_db_id)
                if p:
                    meta_fields[fk] = p["id"]
        # Drop None values so we don't overwrite existing data with NULL
        meta_fields = {k: v for k, v in meta_fields.items() if v is not None}
        if meta_fields:
            database.upsert_team_meta(team_db_id, **meta_fields)

    return data


def crawl_player(session, player_cta_id: int, incremental: bool = False) -> dict:
    """Fetch and parse a player profile. Insert stats into DB."""
    url      = f"{config.BASE_URL}/cts/profile/{player_cta_id}/"
    url_path = f"/cts/profile/{player_cta_id}/"
    logger.info(f"Crawling player {player_cta_id}: {url}")

    resp = auth.authenticated_get(session, url)
    if not resp:
        logger.error(f"Failed to fetch player page: {player_cta_id}")
        return {}

    html   = resp.text
    page_h = _page_hash(html)

    database.set_url(url_path, "player", player_cta_id)  # siempre actualiza last_scraped

    if incremental and not database.needs_rescrape(url_path, page_h):
        logger.debug(f"[Skip] Jugador {player_cta_id} sin cambios")
        return {"_skipped": True}

    database.update_url_hash(url_path, page_h)

    data = parse_player_page(html)

    # Update player name only if it's a real name (not a generic page title)
    _GENERIC_NAMES = {"perfil de afiliado", "perfil", "jugador", "player profile"}
    player = database.get_player(player_cta_id)
    scraped_name = data.get("name", "").strip()
    if player and scraped_name and scraped_name.lower() not in _GENERIC_NAMES:
        database.upsert_player(player_cta_id, scraped_name, player.get("team_id"))

    # Insert stats snapshot + persist all new fields
    if player:
        database.insert_player_stats(player["id"], data)

        # PII / photo / club acronym (player-level meta)
        meta = {
            "photo_url":    data.get("photo_url"),
            "club_acronym": data.get("club_acronym"),
            "email":        data.get("email"),
            "phone":        data.get("phone"),
            "cedula":       data.get("cedula"),
            "birth_date":   data.get("birth_date"),
        }
        meta = {k: v for k, v in meta.items() if v is not None}
        if meta:
            database.upsert_player_meta(player["id"], **meta)

        if data.get("ranking_history"):
            season = None
            mh = data.get("match_history") or []
            if mh and mh[0].get("season"):
                season = mh[0]["season"]
            database.replace_player_ranking_history(player["id"], data["ranking_history"], season=season)

        if data.get("match_history"):
            database.upsert_player_match_history(player["id"], data["match_history"])

    return data


def discover_all(session=None, incremental: bool = True, max_pages: int = None) -> dict:
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
    summary = {"teams_found": 0, "players_found": 0, "pages_scraped": 0, "team_errors": 0, "player_errors": 0}
    pages_scraped = 0
    page_limit = max_pages  # None = sin límite; el check `if page_limit` lo maneja

    # Step 1: Crawl standings for ALL categories
    print(f"[Spider] Paso 1: Tablas de posiciones ({len(config.CATEGORIES)} categorías)...")
    all_teams = []
    for cat in config.CATEGORIES:
        if page_limit and pages_scraped >= page_limit:
            break
        print(f"  [{cat['name']}] categoria_id={cat['id']}")
        teams_in_cat = crawl_standings(session, config.LIGA_ID, cat["id"])
        all_teams.extend(teams_in_cat)
        pages_scraped += 1

    teams = all_teams
    summary["teams_found"] = len(teams)

    # Step 2: Crawl each team
    print(f"[Spider] Paso 2: Crawling {len(teams)} equipos...")
    all_players = []
    for team_data in teams:
        cta_id = team_data.get("cta_id")
        if not cta_id:
            continue

        if page_limit and pages_scraped >= page_limit:
            logger.warning(f"Reached max pages limit ({page_limit})")
            break

        try:
            team_result = crawl_team(session, cta_id)
            pages_scraped += 1
            players = team_result.get("players", [])
            all_players.extend(players)
            print(f"  [{pages_scraped}] {team_data.get('name', cta_id)}: {len(players)} jugadores")
        except Exception as e:
            summary["team_errors"] += 1
            logger.exception(f"[Crawl] Error procesando equipo {cta_id} ({team_data.get('name', '')})")
            print(f"  ERROR equipo {cta_id} ({team_data.get('name', '')}): {e}")
            continue

    summary["players_found"] = len(all_players)

    # Step 3: Crawl each player — 3 workers en paralelo
    print(f"[Spider] Paso 3: Crawling {len(all_players)} jugadores (3 en paralelo)...")
    _lock          = threading.Lock()
    _p_counts      = {"scraped": 0, "errors": 0}
    _failed_players = []

    def _crawl_one_player(player):
        pid  = player["cta_id"]
        name = player.get("name", str(pid))
        try:
            result  = crawl_player(session, pid, incremental=incremental)
            skipped = isinstance(result, dict) and result.get("_skipped")
            with _lock:
                _p_counts["scraped"] += 1
                tag = "(sin cambios)" if skipped else "✓"
                print(f"  [{_p_counts['scraped']}/{len(all_players)}] {name} {tag}")
        except Exception as e:
            with _lock:
                _p_counts["scraped"] += 1
                _p_counts["errors"]  += 1
                _failed_players.append(player)
            logger.exception(f"[Crawl] Error jugador {pid} ({name})")
            print(f"  ERROR jugador {pid} ({name}): {e}")

    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(_crawl_one_player, all_players))

    pages_scraped += _p_counts["scraped"]

    # Step 4: Segunda pasada — reintentar jugadores fallidos por SSL/conexión
    if _failed_players:
        print(f"\n[Spider] Paso 4: Segunda pasada — {len(_failed_players)} jugadores fallidos...")
        time.sleep(30)  # pausa para que el servidor se recupere
        auth._reset_connection_pool(session)
        retry_errors = 0
        for i, player in enumerate(_failed_players, 1):
            pid  = player["cta_id"]
            name = player.get("name", str(pid))
            try:
                result  = crawl_player(session, pid, incremental=False)
                skipped = isinstance(result, dict) and result.get("_skipped")
                tag = "(sin cambios)" if skipped else "✓"
                print(f"  [retry {i}/{len(_failed_players)}] {name} {tag}")
            except Exception as e:
                retry_errors += 1
                logger.error(f"[Crawl] Retry fallido jugador {pid} ({name}): {e}")
                print(f"  [retry {i}/{len(_failed_players)}] ERROR {name}: {e}")
        summary["player_errors"] = retry_errors
        print(f"  Segunda pasada completada: {len(_failed_players) - retry_errors}/{len(_failed_players)} recuperados")
    else:
        summary["player_errors"] = _p_counts["errors"]

    summary["pages_scraped"] = pages_scraped
    total_errors = summary["team_errors"] + summary["player_errors"]

    print(f"\n{'━' * 48}")
    print(f"  RESUMEN DEL CRAWL COMPLETO")
    print(f"{'━' * 48}")
    print(f"  Equipos procesados   : {summary['teams_found']}")
    print(f"  Jugadores procesados : {summary['players_found']}")
    print(f"  Páginas scrapeadas   : {summary['pages_scraped']}")
    if total_errors == 0:
        print(f"  Errores encontrados  : 0  ✓")
    else:
        print(f"  Errores encontrados  : {total_errors}  ⚠")
        if summary["team_errors"]:
            print(f"    • Equipos con error : {summary['team_errors']}")
        if summary["player_errors"]:
            print(f"    • Jugadores con error: {summary['player_errors']}")
    print(f"{'━' * 48}")
    print(f"__SUMMARY__teams={summary['teams_found']}|players={summary['players_found']}|pages={summary['pages_scraped']}|errors={total_errors}")
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
                "games_won":  _num(vals[8]) if len(vals) > 8 else None,
                "games_lost": _num(vals[9]) if len(vals) > 9 else None,
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


def crawl_group(group_id: int, session=None, league_id: int = None, grupo_num: str = None) -> dict:
    """Crawl /cts/grupo_d/{group_id}/ y guarda posiciones + fixtures en la DB."""
    if session is None:
        session = auth.get_session()
        if not session:
            return {"error": "Could not authenticate"}

    url = f"{config.BASE_URL}/cts/grupo_d/{group_id}/"
    logger.info(f"[Group] Crawling {url}")
    resp = auth.authenticated_get(session, url)
    if not resp:
        logger.error(f"[Group] Failed to fetch group page: {url}")
        return {"error": "Failed to fetch group page"}

    soup_tmp = BeautifulSoup(resp.text, "html.parser")

    # Extraer nombre del grupo desde <h4> (ej: "Grupo: 6M5" → "6M5")
    group_name = f"Grupo{grupo_num or ''}"
    categoria_name = None
    h4 = soup_tmp.find("h4", class_="m-4")
    if h4:
        h4_text = h4.get_text(strip=True)
        gm = re.search(r"Grupo[:\s]+(\S+)", h4_text, re.IGNORECASE)
        if gm:
            group_name = gm.group(1)          # ej: "6M5"
            cm = re.match(r"([0-9]+[MF])", group_name)
            if cm:
                categoria_name = cm.group(1)  # ej: "6M"

    # Persistir el grupo en la BD
    if league_id:
        database.upsert_group(group_id, league_id, group_name, grupo_num or "1", categoria_name)

    data = parse_group_page(resp.text)

    # Upsert standings
    for s in data["standings"]:
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
            "points":     s["won"],   # sin columna Pts, usamos victorias
        }, group_id=group_id)

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
            group_id=group_id,
            raw_detail={
                "jornada":    f.get("jornada", ""),
                "time":       f.get("time", ""),
                "sede":       f.get("sede", ""),
                "fixture_id": f.get("fixture_id"),
            },
        )
        saved += 1

    logger.info(f"[Group] {group_name}: {len(data['standings'])} standings, {saved} fixtures")
    return {"standings": len(data["standings"]), "fixtures": saved, "group_name": group_name}


def parse_match_result_page(html: str) -> dict:
    """Parse a CTA create_result page and return rubber data.

    Structure on the page:
      - Each rubber is a div.card.bg-light.mb-2 (juego1..juego5)
      - Header h4: "Doble 1" / "Single"
      - Two team columns: .eq1-name / .eq2-name with player <a> links
      - Winner: span.res-check without hidden attr
      - Score: input id_juego{N}-eq{1/2}_set{1/2/3} value attributes

    Returns dict with keys: season, jornada, home_team, away_team, rubbers.
    rubbers is a list of dicts with: position, type, home_players, away_players,
    home_score, away_score, winner ("home"/"away"/None).
    """
    soup = BeautifulSoup(html, "html.parser")

    # ── Meta header (season, jornada, home_team, away_team) ──────────────────
    meta = {}
    for span in soup.select("span.mb-2.mb-sm-4.me-sm-2"):
        label_el = span.find_previous_sibling()
        if not label_el:
            label_el = span.parent.find("b") or span.parent
        label = span.find_previous("b")
        if label:
            key = label.get_text(strip=True).rstrip(":").lower()
            meta[key] = span.get_text(strip=True)

    # Fallback: read from bold labels directly
    for b in soup.find_all("b"):
        txt = b.get_text(strip=True).rstrip(":")
        sibling = b.next_sibling
        while sibling and not getattr(sibling, "get_text", None):
            sibling = sibling.next_sibling
        if sibling:
            val = sibling.get_text(strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
            meta[txt.lower()] = val

    # Equipo names from .eq1-name / .eq2-name (first occurrence, in page header)
    eq1_els = soup.select("h4.eq1-name")
    eq2_els = soup.select("h4.eq2-name")
    home_team = eq1_els[0].get_text(strip=True) if eq1_els else ""
    away_team = eq2_els[0].get_text(strip=True) if eq2_els else ""

    # ── Rubber sections (div.card.text-dark.bg-light) ────────────────────────
    rubber_cards = soup.select("div.card.text-dark.bg-light.mb-2")
    rubbers = []

    for card in rubber_cards:
        # Rubber type + position from header h4 (not .eq1-name / .eq2-name)
        header_h4 = card.select_one("div.card-header h4.card-title:not(.eq1-name):not(.eq2-name)")
        if not header_h4:
            continue
        header_txt = " ".join(header_h4.get_text().split())  # collapse whitespace
        m_type = re.match(r"(Doble|Single|Singles?|Dobles?)\s*(\d*)", header_txt, re.IGNORECASE)
        rubber_type = m_type.group(1).lower() if m_type else header_txt.lower()
        rubber_pos = int(m_type.group(2)) if m_type and m_type.group(2) else len(rubbers) + 1
        # Normalize type
        if "doble" in rubber_type:
            rubber_type = "doubles"
        else:
            rubber_type = "singles"

        # Players from each team column
        def get_players(eq_num):
            players = []
            sel = f"[id*='juego'][id*='-wo_eq{eq_num}']"
            wo_input = card.select_one(sel)
            if not wo_input:
                return players
            # The player links are siblings in the card-body of the same card col
            team_card = wo_input
            for _ in range(6):
                team_card = team_card.parent
                if team_card.name == "div" and "card" in (team_card.get("class") or []) and "p-2" in (team_card.get("class") or []):
                    break
            for a in team_card.select("a[href*='/cts/profile/']"):
                name = a.get_text(strip=True)
                # Remove category suffix like "(6ta M)"
                name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()
                href = a.get("href", "")
                cta_m = re.search(r"/cts/profile/(\d+)/", href)
                cta_id = int(cta_m.group(1)) if cta_m else None
                if name:
                    players.append({"name": name, "profile_id": cta_id})
            return players

        home_players = get_players(1)
        away_players = get_players(2)

        # Winner: span.res-check without hidden attr
        winner = None
        for span in card.select("span.res-check"):
            span_id = span.get("id", "")
            if span.get("hidden") is None and "hidden" not in span.attrs:
                if "eq1_win" in span_id:
                    winner = "home"
                elif "eq2_win" in span_id:
                    winner = "away"

        # Scores: read input values for set1/set2/TB
        def get_set_scores(eq_num):
            sets = []
            for s in (1, 2, 3):
                inp = card.select_one(f"[id$='-eq{eq_num}_set{s}']")
                if inp:
                    v = inp.get("value", "")
                    sets.append(v if v != "" else "0")
            return sets

        home_sets = get_set_scores(1)
        away_sets = get_set_scores(2)

        # Build score string like "4-6 4-6" (set by set, home vs away)
        score_parts = []
        for hs, as_ in zip(home_sets, away_sets):
            if hs != "0" or as_ != "0":
                score_parts.append(f"{hs}-{as_}")
        score_str = " ".join(score_parts) if score_parts else ""

        rubbers.append({
            "position":    rubber_pos,
            "type":        rubber_type,
            "home_players": home_players,
            "away_players": away_players,
            "home_sets":   home_sets,
            "away_sets":   away_sets,
            "score":       score_str,
            "winner":      winner,
        })

    return {
        "meta":      meta,
        "home_team": home_team,
        "away_team": away_team,
        "rubbers":   rubbers,
    }


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


# ─────────────────────────────────────────────
# MATCH RUBBERS — persistence and backfill
# ─────────────────────────────────────────────
def persist_match_rubbers(match_id: int, parsed: dict) -> dict:
    """Persist parsed rubbers from parse_match_result_page into match_rubbers.

    Resolves cta_id (profile_id from parser) → players.id via database.get_player.
    Skips a rubber if any required player cannot be resolved.

    Returns {scraped, skipped, errors}.
    """
    out = {"scraped": 0, "skipped": 0, "errors": 0}

    for rubber in parsed.get("rubbers", []):
        rubber_type = rubber.get("type")
        position = rubber.get("position")

        def resolve(slot_players):
            ids = []
            for ply in slot_players or []:
                cta_id = ply.get("profile_id")
                if not cta_id:
                    return None
                row = database.get_player(cta_id)
                if not row:
                    return None
                ids.append(row["id"])
            return ids

        home_ids = resolve(rubber.get("home_players"))
        away_ids = resolve(rubber.get("away_players"))

        if home_ids is None or away_ids is None:
            out["skipped"] += 1
            continue

        home_player_id  = home_ids[0] if len(home_ids) >= 1 else None
        home_partner_id = home_ids[1] if len(home_ids) >= 2 else None
        away_player_id  = away_ids[0] if len(away_ids) >= 1 else None
        away_partner_id = away_ids[1] if len(away_ids) >= 2 else None

        if rubber_type == "doubles" and (home_partner_id is None or away_partner_id is None):
            out["skipped"] += 1
            continue
        if home_player_id is None or away_player_id is None:
            out["skipped"] += 1
            continue

        try:
            database.insert_rubber(
                match_id=match_id,
                position=position,
                rubber_type=rubber_type,
                home_player_id=home_player_id,
                away_player_id=away_player_id,
                home_partner_id=home_partner_id,
                away_partner_id=away_partner_id,
                score=rubber.get("score") or "",
                winner=rubber.get("winner"),
            )
            out["scraped"] += 1
        except Exception as e:
            logger.warning(f"[Rubbers] insert failed match={match_id} pos={position}: {e}")
            out["errors"] += 1

    return out


def backfill_match_rubbers(
    match_id: int,
    fixture_id: int,
    session=None,
    *,
    force: bool = False,
) -> dict:
    """Scrape and persist rubbers for a single match. Idempotent: skips if rubbers
    already exist unless force=True.
    """
    if not force:
        existing = database.get_rubber_count_for_match(match_id)
        if existing > 0:
            return {"scraped": 0, "skipped": existing, "errors": 0, "status": "already_present"}

    if session is None:
        session = auth.get_session()
        if not session:
            return {"scraped": 0, "skipped": 0, "errors": 1, "status": "auth_failed"}

    url = f"{config.BASE_URL}/cts/create_result/{fixture_id}/"
    resp = auth.authenticated_get(session, url)
    if resp is None or resp.status_code != 200:
        return {"scraped": 0, "skipped": 0, "errors": 1, "status": "fetch_failed"}

    parsed = parse_match_result_page(resp.text)
    result = persist_match_rubbers(match_id, parsed)
    result["status"] = "ok"
    return result


def backfill_all_match_rubbers(
    *,
    only_completed: bool = True,
    team_cta_id: int | None = None,
    force: bool = False,
    progress_cb=None,
) -> dict:
    """Walk through matches and populate match_rubbers for each.

    Args:
        only_completed: skip matches with status != 'completed'.
        team_cta_id: if set, restrict to matches involving this team.
        force: re-scrape and re-insert even if rubbers already exist for that match.
        progress_cb: optional callable(idx, total, match_id, status) for live progress.

    Returns aggregate {processed, scraped, skipped, errors, missing_fixture}.
    """
    session = auth.get_session()
    if not session:
        return {"processed": 0, "scraped": 0, "skipped": 0, "errors": 0,
                "missing_fixture": 0, "status": "auth_failed"}

    sql = """
        SELECT m.id, m.match_date, m.status, m.raw_detail,
               ht.cta_id AS home_cta_id, at.cta_id AS away_cta_id
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.id
        JOIN teams at ON m.away_team_id = at.id
    """
    args: list = []
    where: list[str] = []
    if only_completed:
        where.append("m.status = 'completed'")
    if team_cta_id is not None:
        where.append("(ht.cta_id = ? OR at.cta_id = ?)")
        args.extend([team_cta_id, team_cta_id])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.match_date DESC"

    with database.get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()

    totals = {"processed": 0, "scraped": 0, "skipped": 0, "errors": 0,
              "missing_fixture": 0, "already_present": 0}
    total = len(rows)

    for idx, row in enumerate(rows, start=1):
        match_id = row["id"]
        raw_detail = row["raw_detail"]
        fixture_id = None
        if raw_detail:
            try:
                detail_obj = json.loads(raw_detail)
                fixture_id = detail_obj.get("fixture_id")
            except (json.JSONDecodeError, TypeError):
                pass

        if not fixture_id:
            totals["missing_fixture"] += 1
            if progress_cb:
                progress_cb(idx, total, match_id, "no_fixture")
            continue

        result = backfill_match_rubbers(match_id, fixture_id, session=session, force=force)
        if result.get("status") == "already_present":
            totals["already_present"] += 1
        else:
            totals["processed"] += 1
            totals["scraped"] += result.get("scraped", 0)
            totals["skipped"] += result.get("skipped", 0)
            totals["errors"] += result.get("errors", 0)

        if progress_cb:
            progress_cb(idx, total, match_id, result.get("status", "ok"))

    return totals
