#!/usr/bin/env python3
"""
CTA Tenis Monitor — Club Táchira 6ta B
Autor: JDM | #JDMRules
Descripción: Monitorea tabla de posiciones, calendario y perfil en ctatenis.com
             y envía alertas via Telegram cuando hay cambios.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import hashlib
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURACIÓN — edita estos valores
# ─────────────────────────────────────────────
CTA_CEDULA   = "TU_CEDULA_AQUI"        # Tu cédula de identidad
CTA_PASSWORD = "TU_PASSWORD_AQUI"      # Tu contraseña CTA

TELEGRAM_TOKEN  = "TU_BOT_TOKEN_AQUI"  # Token del bot de Telegram
TELEGRAM_CHAT_ID = "TU_CHAT_ID_AQUI"   # Tu Chat ID de Telegram

# URLs objetivo
URLS = {
    "tabla_posiciones": "https://ctatenis.com/cts/tabla_posiciones/32/6/",
    "calendario_equipo": "https://ctatenis.com/cts/team_d/7361/",
    "perfil_jugador":   "https://ctatenis.com/cts/profile/22124/",
}

# Archivo donde se guarda el estado anterior (para detectar cambios)
STATE_FILE = os.path.join(os.path.dirname(__file__), "cta_state.json")

BASE_URL   = "https://ctatenis.com"
LOGIN_URL  = "https://ctatenis.com/accounts/login/"


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
def send_telegram(message: str):
    """Envía un mensaje de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[Telegram] Mensaje enviado OK")
    except Exception as e:
        print(f"[Telegram] Error: {e}")


# ─────────────────────────────────────────────
# AUTENTICACIÓN
# ─────────────────────────────────────────────
def login() -> requests.Session | None:
    """Crea una sesión autenticada en ctatenis.com."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    })

    # 1. GET para obtener el CSRF token
    try:
        resp = session.get(LOGIN_URL, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Login] Error al cargar la página de login: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_input:
        print("[Login] No se encontró el token CSRF")
        return None

    csrf_token = csrf_input["value"]

    # 2. POST con credenciales
    payload = {
        "csrfmiddlewaretoken": csrf_token,
        "username": CTA_CEDULA,
        "password": CTA_PASSWORD,
    }
    headers = {"Referer": LOGIN_URL}

    try:
        resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Login] Error en POST: {e}")
        return None

    # Verificar login exitoso (si redirigió a login de nuevo, falló)
    if "/accounts/login/" in resp.url:
        print("[Login] Credenciales incorrectas o login fallido")
        return None

    print(f"[Login] Sesión iniciada correctamente → {resp.url}")
    return session


# ─────────────────────────────────────────────
# SCRAPERS
# ─────────────────────────────────────────────
def scrape_tabla_posiciones(session: requests.Session) -> dict:
    """Extrae la tabla de posiciones de 6ta Masculino."""
    try:
        resp = session.get(URLS["tabla_posiciones"], timeout=10)
        resp.raise_for_status()
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    equipos = []

    # Buscar tabla de posiciones
    tabla = soup.find("table")
    if not tabla:
        # Intentar buscar por divs si no hay <table>
        filas = soup.find_all("tr")
    else:
        filas = tabla.find_all("tr")

    for fila in filas:
        celdas = fila.find_all(["td", "th"])
        if celdas:
            equipo = [c.get_text(strip=True) for c in celdas]
            if equipo:
                equipos.append(equipo)

    return {
        "timestamp": datetime.now().isoformat(),
        "equipos": equipos,
        "raw_hash": hashlib.md5(resp.text.encode()).hexdigest(),
    }


def scrape_calendario(session: requests.Session) -> dict:
    """Extrae el calendario/fixtures del equipo Club Táchira 6ta B."""
    try:
        resp = session.get(URLS["calendario_equipo"], timeout=10)
        resp.raise_for_status()
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    partidos = []

    # Buscar filas de partidos
    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) >= 2:
            partido = [c.get_text(strip=True) for c in celdas]
            partidos.append(partido)

    # Buscar también divs con info de partidos
    for item in soup.find_all(class_=lambda c: c and any(
        x in c for x in ["match", "partido", "fixture", "game", "result"]
    )):
        texto = item.get_text(strip=True)
        if texto:
            partidos.append([texto])

    return {
        "timestamp": datetime.now().isoformat(),
        "partidos": partidos,
        "raw_hash": hashlib.md5(resp.text.encode()).hexdigest(),
    }


def scrape_perfil(session: requests.Session) -> dict:
    """Extrae estadísticas del perfil del jugador."""
    try:
        resp = session.get(URLS["perfil_jugador"], timeout=10)
        resp.raise_for_status()
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    stats = {}

    # Nombre del jugador
    nombre = soup.find("h1") or soup.find("h2") or soup.find("h3")
    if nombre:
        stats["nombre"] = nombre.get_text(strip=True)

    # Buscar stats en tabla
    for fila in soup.find_all("tr"):
        celdas = fila.find_all(["td", "th"])
        if len(celdas) == 2:
            key = celdas[0].get_text(strip=True)
            val = celdas[1].get_text(strip=True)
            if key:
                stats[key] = val

    # Buscar ranking / puntos en spans/divs
    for tag in soup.find_all(["span", "div", "p"]):
        texto = tag.get_text(strip=True)
        if any(k in texto.lower() for k in ["ranking", "puntos", "ganados", "perdidos", "sets"]):
            stats[f"info_{len(stats)}"] = texto

    return {
        "timestamp": datetime.now().isoformat(),
        "stats": stats,
        "raw_hash": hashlib.md5(resp.text.encode()).hexdigest(),
    }


# ─────────────────────────────────────────────
# DETECCIÓN DE CAMBIOS
# ─────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def check_changes(key: str, new_hash: str, state: dict) -> bool:
    """Retorna True si hubo cambio."""
    return state.get(key) != new_hash


# ─────────────────────────────────────────────
# FORMATO DE MENSAJES TELEGRAM
# ─────────────────────────────────────────────
def format_tabla_msg(data: dict) -> str:
    lines = ["🎾 <b>TABLA DE POSICIONES — 6ta Masculino CTA</b>\n"]
    equipos = data.get("equipos", [])
    for i, equipo in enumerate(equipos[:15]):  # máx 15 filas
        lines.append(" | ".join(equipo))
    lines.append(f"\n🕐 {data.get('timestamp', '')[:16].replace('T', ' ')}")
    return "\n".join(lines)


def format_calendario_msg(data: dict) -> str:
    lines = ["📅 <b>CALENDARIO — Club Táchira 6ta B</b>\n"]
    partidos = data.get("partidos", [])
    for p in partidos[:20]:
        lines.append(" | ".join(p))
    lines.append(f"\n🕐 {data.get('timestamp', '')[:16].replace('T', ' ')}")
    return "\n".join(lines)


def format_perfil_msg(data: dict) -> str:
    stats = data.get("stats", {})
    lines = ["👤 <b>MI PERFIL — CTA Tenis</b>\n"]
    for k, v in list(stats.items())[:15]:
        lines.append(f"• <b>{k}</b>: {v}")
    lines.append(f"\n🕐 {data.get('timestamp', '')[:16].replace('T', ' ')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ─────────────────────────────────────────────
def run(force_notify: bool = False):
    """Ejecuta el ciclo completo de scraping y notificación."""
    print(f"\n{'='*50}")
    print(f"[CTA Monitor] Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # Login
    session = login()
    if not session:
        send_telegram("⚠️ <b>CTA Monitor</b>: Error de login. Verificar credenciales.")
        return

    state = load_state()
    new_state = dict(state)

    # ── Tabla de posiciones ──
    print("[Scraper] Tabla de posiciones...")
    tabla = scrape_tabla_posiciones(session)
    if "error" not in tabla:
        if force_notify or check_changes("tabla_hash", tabla["raw_hash"], state):
            print("[Cambio detectado] Tabla de posiciones")
            send_telegram(format_tabla_msg(tabla))
            new_state["tabla_hash"] = tabla["raw_hash"]
        else:
            print("[Sin cambios] Tabla de posiciones")

    time.sleep(2)

    # ── Calendario ──
    print("[Scraper] Calendario del equipo...")
    calendario = scrape_calendario(session)
    if "error" not in calendario:
        if force_notify or check_changes("calendario_hash", calendario["raw_hash"], state):
            print("[Cambio detectado] Calendario")
            send_telegram(format_calendario_msg(calendario))
            new_state["calendario_hash"] = calendario["raw_hash"]
        else:
            print("[Sin cambios] Calendario")

    time.sleep(2)

    # ── Perfil ──
    print("[Scraper] Perfil del jugador...")
    perfil = scrape_perfil(session)
    if "error" not in perfil:
        if force_notify or check_changes("perfil_hash", perfil["raw_hash"], state):
            print("[Cambio detectado] Perfil")
            send_telegram(format_perfil_msg(perfil))
            new_state["perfil_hash"] = perfil["raw_hash"]
        else:
            print("[Sin cambios] Perfil")

    save_state(new_state)
    print(f"[CTA Monitor] Ciclo completado OK\n")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv  # python cta_monitor.py --force → notifica siempre
    run(force_notify=force)
