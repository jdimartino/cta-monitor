#!/bin/bash
# open-tunnel.sh — Arranca el túnel Cloudflare en una ventana Terminal aparte.
# Uso: bash open-tunnel.sh

CLOUDFLARED="/Users/macmini2014/bin/cloudflared"
CONFIG="/Users/macmini2014/.cloudflared/config.yml"

# Matar túnel anterior si está corriendo
pkill -f "cloudflared tunnel run" 2>/dev/null || true
sleep 1

# Abrir nueva ventana Terminal con el túnel
osascript \
  -e 'tell application "Terminal"' \
  -e "  do script \"echo '🌐 Túnel Cloudflare → cta.tenistac.site' && $CLOUDFLARED --config $CONFIG tunnel run cta-monitor\"" \
  -e '  activate' \
  -e 'end tell'
