#!/bin/bash
# pull-global.sh — baja los últimos cambios de GitHub al MacBook Air
# La Mac Mini se actualiza vía push-global.sh (rsync directo, sin internet)
# Uso: ./pull-global.sh

set -e
cd "$(dirname "$0")"

echo "━━━ Pull → GitHub ━━━━━━━━━━━━━━━━━━━━━━━━━━━"
git pull origin main

echo ""
echo "✓ Listo — MacBook Air actualizado."
