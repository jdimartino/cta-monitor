"""
CTA Intelligence System — Configuration
Autor: JDM | #JDMRules
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# Load .env from project root
load_dotenv(BASE_DIR / ".env")

# ── CTA Credentials ──
CTA_CEDULA = os.getenv("CTA_CEDULA", "")
CTA_PASSWORD = os.getenv("CTA_PASSWORD", "")

# ── Telegram ──
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── CTA Site ──
BASE_URL = "https://ctatenis.com"
LOGIN_URL = f"{BASE_URL}/accounts/login/"

# ── Database ──
DB_PATH = DATA_DIR / "cta.db"

# ── Session persistence ──
SESSION_FILE = DATA_DIR / "session.pkl"
SESSION_MAX_AGE_HOURS = 4

# ── Rate limiting ──
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.0"))
MAX_PAGES_PER_CRAWL = int(os.getenv("MAX_PAGES_PER_CRAWL", "500"))

# ── Known IDs (configurable) ──
OWN_TEAM_ID  = int(os.getenv("OWN_TEAM_ID",  "7361"))
LIGA_ID      = int(os.getenv("LIGA_ID",      "32"))
CATEGORIA_ID = int(os.getenv("CATEGORIA_ID", "6"))
GROUP_ID     = int(os.getenv("GROUP_ID",     "1282"))  # Alias de compatibilidad — Grupo 5M del equipo propio

# Todos los grupos de la liga. Clave = categoria_id de ctatenis.
# Valor = lista de (grupo_num, group_id) en orden.
GROUPS: dict[int, list[tuple[str, int]]] = {
    9:  [("1", 1248)],                                                        # 3F
    1:  [("1", 1249)],                                                        # 3M
    2:  [("1", 1250), ("2", 1251)],                                           # 4F
    7:  [("1", 1252), ("2", 1253)],                                           # 4M
    4:  [("1", 1269), ("2", 1270), ("3", 1271)],                              # 5F
    5:  [("1", 1272), ("2", 1273), ("3", 1274)],                              # 5M
    3:  [("1", 1275), ("2", 1276), ("3", 1277)],                              # 6F
    6:  [("1", 1278), ("2", 1279), ("3", 1280), ("4", 1281), ("5", 1282)],   # 6M
    35: [("1", 1254), ("2", 1255)],                                           # 7F
    36: [("1", 1256), ("2", 1257)],                                           # 7M
}

# ── Todas las categorías de la liga (liga_id=32) ──
CATEGORIES = [
    {"id": 9,  "name": "3F", "gender": "F", "level": 3},
    {"id": 1,  "name": "3M", "gender": "M", "level": 3},
    {"id": 2,  "name": "4F", "gender": "F", "level": 4},
    {"id": 7,  "name": "4M", "gender": "M", "level": 4},
    {"id": 4,  "name": "5F", "gender": "F", "level": 5},
    {"id": 5,  "name": "5M", "gender": "M", "level": 5},
    {"id": 3,  "name": "6F", "gender": "F", "level": 6},
    {"id": 6,  "name": "6M", "gender": "M", "level": 6},
    {"id": 35, "name": "7F", "gender": "F", "level": 7},
    {"id": 36, "name": "7M", "gender": "M", "level": 7},
]

# ── Legacy state file (for migration) ──
LEGACY_STATE_FILE = BASE_DIR / "cta_state.json"

# ── User-Agent ──
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
