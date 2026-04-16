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
MAX_PAGES_PER_CRAWL = int(os.getenv("MAX_PAGES_PER_CRAWL", "200"))

# ── Known IDs (configurable) ──
OWN_TEAM_ID = int(os.getenv("OWN_TEAM_ID", "7361"))
LIGA_ID = int(os.getenv("LIGA_ID", "32"))
CATEGORIA_ID = int(os.getenv("CATEGORIA_ID", "6"))

# ── Legacy state file (for migration) ──
LEGACY_STATE_FILE = BASE_DIR / "cta_state.json"

# ── User-Agent ──
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
