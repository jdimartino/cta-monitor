#!/bin/bash
# push-global.sh — commit + push a GitHub + sync a Mac Mini
# Uso: ./push-global.sh "mensaje del commit"
#      ./push-global.sh            (usa fecha/hora automática)

set -e
cd "$(dirname "$0")"

MSG="${1:-update: $(date '+%Y-%m-%d %H:%M')}"

echo "━━━ 1/3  Commit ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
git add -A
if git diff --cached --quiet; then
    echo "  Sin cambios que commitear."
else
    git commit -m "$MSG"
fi

echo "━━━ 2/3  Push → GitHub ━━━━━━━━━━━━━━━━━━━━━━"
git push origin main

echo "━━━ 3/3  Sync → Mac Mini ━━━━━━━━━━━━━━━━━━━━"
rsync -az --delete \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='data/' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='*.pkl' \
    --exclude='.DS_Store' \
    --exclude='.venv/' \
    --exclude='cta_state.json' \
    . mac-mini:~/antigravity/cta-monitor/

echo ""
echo "✓ Listo — GitHub y Mac Mini actualizados."
