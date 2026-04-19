#!/bin/bash
# run.sh — Corre un comando de cta-monitor usando el venv local.
# Uso: bash run.sh <comando> [argumentos]
# Ejemplos:
#   bash run.sh crawl
#   bash run.sh monitor
#   bash run.sh rival 7361
#   bash run.sh draw 7361
#   bash run.sh report
#   bash run.sh sync
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

if [ ! -d "venv" ]; then
  echo -e "${RED}❌ Primero corré: bash setup.sh${RESET}"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo -e "${RED}❌ Falta el archivo .env. Corré: bash setup.sh${RESET}"
  exit 1
fi

if [ $# -eq 0 ]; then
  echo ""
  echo -e "${BOLD}Uso: bash run.sh <comando>${RESET}"
  echo ""
  echo -e "  ${CYAN}crawl${RESET}              → Scrapea datos nuevos del sitio CTA"
  echo -e "  ${CYAN}monitor${RESET}            → Ejecuta el monitor una vez"
  echo -e "  ${CYAN}rival TEAM_ID${RESET}      → Analiza un rival"
  echo -e "  ${CYAN}draw RIVAL_ID${RESET}      → Predice el sorteo"
  echo -e "  ${CYAN}report${RESET}             → Genera reporte"
  echo -e "  ${CYAN}sync${RESET}               → Sincroniza datos"
  echo ""
  exit 0
fi

echo ""
echo -e "  🎾 Corriendo: ${BOLD}python main.py $*${RESET}"
echo ""

venv/bin/python main.py "$@"
