"""
CTA Intelligence System — Monitor & Telegram Alerts
Autor: JDM | #JDMRules
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime

import requests

import config
import auth
import database

logger = logging.getLogger("monitor")


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
def send_telegram(message: str, chat_id: str = None) -> bool:
    """Send HTML-formatted message to Telegram. Returns True on success."""
    token = config.TELEGRAM_TOKEN
    chat = chat_id or config.TELEGRAM_CHAT_ID

    if not token or not chat:
        logger.warning("Telegram credentials not configured")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Telegram message sent OK")
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


# ─────────────────────────────────────────────
# HASH-BASED CHANGE DETECTION
# ─────────────────────────────────────────────
def compute_hash(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()


def check_page_changed(key: str, html: str) -> bool:
    """Compare page hash with stored value. Returns True if changed (and updates DB)."""
    new_hash = compute_hash(html)
    old_hash = database.get_hash(key)

    if old_hash != new_hash:
        database.set_hash(key, new_hash)
        return True
    return False


# ─────────────────────────────────────────────
# MESSAGE FORMATTERS
# ─────────────────────────────────────────────
def format_standings_msg(rows: list[list[str]]) -> str:
    """Format standings table rows for Telegram."""
    lines = ["\U0001f3be <b>TABLA DE POSICIONES \u2014 6ta Masculino CTA</b>\n"]
    for row in rows[:15]:
        lines.append(" | ".join(row))
    lines.append(f"\n\U0001f550 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def format_calendar_msg(rows: list[list[str]]) -> str:
    """Format calendar rows for Telegram."""
    lines = ["\U0001f4c5 <b>CALENDARIO \u2014 Club T\u00e1chira 6ta B</b>\n"]
    for row in rows[:20]:
        lines.append(" | ".join(row))
    lines.append(f"\n\U0001f550 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def format_profile_msg(stats: dict) -> str:
    """Format player profile stats for Telegram."""
    lines = ["\U0001f464 <b>MI PERFIL \u2014 CTA Tenis</b>\n"]
    for k, v in list(stats.items())[:15]:
        lines.append(f"\u2022 <b>{k}</b>: {v}")
    lines.append(f"\n\U0001f550 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# PAGE SCRAPERS (for monitoring only)
# ─────────────────────────────────────────────
def _scrape_page(session: requests.Session, url: str) -> str | None:
    """Fetch a page and return raw HTML, or None on error."""
    resp = auth.authenticated_get(session, url)
    if resp is None:
        return None
    return resp.text


def _parse_table_rows(html: str) -> list[list[str]]:
    """Extract table rows from HTML (generic)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    tabla = soup.find("table")
    filas = tabla.find_all("tr") if tabla else soup.find_all("tr")
    for fila in filas:
        celdas = fila.find_all(["td", "th"])
        if celdas:
            row = [c.get_text(strip=True) for c in celdas]
            if row:
                rows.append(row)
    return rows


def _parse_profile_stats(html: str) -> dict:
    """Extract profile stats from HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    stats = {}

    nombre = soup.find("h1") or soup.find("h2") or soup.find("h3")
    if nombre:
        stats["nombre"] = nombre.get_text(strip=True)

    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) == 2:
            key = celdas[0].get_text(strip=True)
            val = celdas[1].get_text(strip=True)
            if key:
                stats[key] = val

    for tag in soup.find_all(["span", "div", "p"]):
        texto = tag.get_text(strip=True)
        if any(k in texto.lower() for k in ["ranking", "puntos", "ganados", "perdidos", "sets"]):
            stats[f"info_{len(stats)}"] = texto

    return stats


# ─────────────────────────────────────────────
# MONITOR CYCLE
# ─────────────────────────────────────────────
def monitor_cycle(force_notify: bool = False):
    """Single monitoring cycle: check pages for changes and alert."""
    print(f"\n{'='*50}")
    print(f"[CTA Monitor] Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    session = auth.get_session()
    if not session:
        send_telegram("\u26a0\ufe0f <b>CTA Monitor</b>: Error de login. Verificar credenciales.")
        return

    # Ensure DB is initialized
    database.init_db()
    database.migrate_legacy_state()

    url_tabla = f"{config.BASE_URL}/cts/tabla_posiciones/{config.LIGA_ID}/{config.CATEGORIA_ID}/"
    url_calendario = f"{config.BASE_URL}/cts/team_d/{config.OWN_TEAM_ID}/"
    url_perfil = f"{config.BASE_URL}/cts/profile/22124/"

    # ── Tabla de posiciones ──
    print("[Scraper] Tabla de posiciones...")
    html = _scrape_page(session, url_tabla)
    if html:
        if force_notify or check_page_changed("tabla_posiciones", html):
            print("[Cambio detectado] Tabla de posiciones")
            rows = _parse_table_rows(html)
            send_telegram(format_standings_msg(rows))
        else:
            print("[Sin cambios] Tabla de posiciones")

    # ── Calendario ──
    print("[Scraper] Calendario del equipo...")
    html = _scrape_page(session, url_calendario)
    if html:
        if force_notify or check_page_changed("calendario_equipo", html):
            print("[Cambio detectado] Calendario")
            rows = _parse_table_rows(html)
            send_telegram(format_calendar_msg(rows))
        else:
            print("[Sin cambios] Calendario")

    # ── Perfil ──
    print("[Scraper] Perfil del jugador...")
    html = _scrape_page(session, url_perfil)
    if html:
        if force_notify or check_page_changed("perfil_jugador", html):
            print("[Cambio detectado] Perfil")
            stats = _parse_profile_stats(html)
            send_telegram(format_profile_msg(stats))
        else:
            print("[Sin cambios] Perfil")

    print(f"[CTA Monitor] Ciclo completado OK\n")


def run_monitor(interval_seconds: int = None):
    """Run monitor in a loop or once (for PM2 mode)."""
    if interval_seconds:
        print(f"[Monitor] Running in loop mode, interval={interval_seconds}s")
        while True:
            try:
                monitor_cycle()
            except Exception as e:
                logger.error(f"Monitor cycle error: {e}")
            time.sleep(interval_seconds)
    else:
        monitor_cycle()
