#!/bin/bash
# stop-tunnel.sh — Detiene el túnel Cloudflare.
# Uso: bash stop-tunnel.sh

pkill -f "cloudflared tunnel run" 2>/dev/null && echo "✓ Túnel detenido" || echo "⚠️  El túnel no estaba corriendo"
