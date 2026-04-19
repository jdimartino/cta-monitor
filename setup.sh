#!/bin/bash
# setup.sh — Configuración inicial de cta-monitor
# Corre esto UNA SOLA VEZ para dejar el proyecto listo.
# Uso: bash setup.sh
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; RESET='\033[0m'

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║          🎾 SETUP CTA MONITOR                            ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── 1. Verificar Python 3 ─────────────────────────────────────────────────────
PYTHON=$(which python3 2>/dev/null || echo "")
if [ -z "$PYTHON" ]; then
  echo -e "${RED}❌ Python 3 no encontrado. Instalalo desde https://python.org${RESET}"
  exit 1
fi
echo -e "  ${GREEN}✅ Python:${RESET} $($PYTHON --version)"

# ── 2. Crear o actualizar venv ────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo -e "  📦 Creando entorno virtual..."
  $PYTHON -m venv venv
  echo -e "  ${GREEN}✅ venv creado${RESET}"
else
  echo -e "  ${GREEN}✅ venv ya existe${RESET}"
fi

# ── 3. Instalar dependencias ──────────────────────────────────────────────────
echo -e "  📦 Instalando dependencias..."
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
echo -e "  ${GREEN}✅ Dependencias instaladas${RESET}"

# ── 4. Crear .env si no existe ────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cat > .env << 'ENVEOF'
# CTA Credentials — Completá con tus datos reales
CTA_CEDULA=
CTA_PASSWORD=

# Telegram Bot — Obtenelo desde @BotFather
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Opcionales (podés dejar comentados)
# OWN_TEAM_ID=7361
# LIGA_ID=32
# CATEGORIA_ID=6
# REQUEST_DELAY=2.0
# MAX_PAGES_PER_CRAWL=200
ENVEOF
  echo ""
  echo -e "  ${YELLOW}⚠️  Se creó .env con campos vacíos.${RESET}"
  echo -e "  ${YELLOW}   Editalo y completá: CTA_CEDULA, CTA_PASSWORD, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID${RESET}"
else
  echo -e "  ${GREEN}✅ .env ya existe${RESET}"
fi

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  ✅ Setup completo. Ahora podés usar:${RESET}"
echo ""
echo -e "  ${BOLD}bash run.sh crawl${RESET}          → Scrapea datos del sitio CTA"
echo -e "  ${BOLD}bash run.sh monitor${RESET}        → Corre el monitor una vez"
echo -e "  ${BOLD}bash run.sh report${RESET}         → Genera reporte"
echo -e "  ${BOLD}bash run.sh rival TEAM_ID${RESET}  → Analiza un rival"
echo -e "  ${BOLD}bash run.sh draw RIVAL_ID${RESET}  → Predice el sorteo"
echo -e "  ${BOLD}bash serve.sh${RESET}              → Servidor web local (http://localhost:8000)"
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo ""
