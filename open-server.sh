#!/bin/bash
# open-server.sh — Reinicia el servidor en una ventana Terminal aparte.
# Mata cualquier uvicorn corriendo en el puerto 8000, abre ventana nueva y el browser.
# Uso: bash open-server.sh

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Matar servidor anterior si está corriendo
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Abrir nueva ventana Terminal con el servidor
osascript \
  -e 'tell application "Terminal"' \
  -e "  do script \"cd '$DIR' && bash serve.sh\"" \
  -e '  activate' \
  -e 'end tell'

# Esperar que inicie y abrir browser
sleep 2
open http://localhost:8000
