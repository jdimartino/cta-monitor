#!/bin/bash
# serve.sh — Levanta el servidor web local de cta-monitor (FastAPI).
# Uso: bash serve.sh
# Abre: http://localhost:8000
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; BOLD='\033[1m'; RESET='\033[0m'

if [ ! -d "venv" ]; then
  echo -e "${RED}❌ Primero corré: bash setup.sh${RESET}"
  exit 1
fi

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo -e "  🌐 Servidor CTA Monitor — ${GREEN}http://localhost:8000${RESET}"
echo -e "  Ctrl+C para detener."
echo -e "${BOLD}══════════════════════════════════════════════════════════${RESET}"
echo ""

venv/bin/uvicorn api:app --reload --port 8000
