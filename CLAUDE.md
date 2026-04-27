# CTA Monitor — Instrucciones del Proyecto

## Arquitectura de trabajo

**Todo corre directamente en la Mac Mini.**

| Elemento | Ubicación |
|----------|-----------|
| Código fuente | `~/Desktop/antigravity/cta-monitor/` |
| Base de datos | `~/antigravity/cta-monitor/data/cta.db` |
| Logs del servidor | `~/antigravity/cta-monitor/logs/` |
| Servidor API local | `http://localhost:8000` |
| Servidor API en red | `http://192.168.100.132:8000` |
| Túnel público | `https://cta.tenistac.site` |

El frontend (`static/app.js`) llama a `http://192.168.100.132:8000/api/...`.

## Cómo abrir el proyecto

Doble clic en:
```
~/Desktop/antigravity/cta-monitor.code-workspace
```

Para ver el dashboard: extensión **Live Server** en VS Code → click derecho en `static/index.html` → "Open with Live Server".

## Servidor FastAPI

El servidor se levanta **manualmente** con el script:

```bash
bash open-server.sh
```

Esto mata cualquier instancia anterior en el puerto 8000 y abre una nueva ventana Terminal ejecutando `serve.sh` (que activa el venv y lanza uvicorn).

Ver logs en tiempo real:
```bash
tail -f ~/antigravity/cta-monitor/logs/fastapi-error.log
```

## Túnel Cloudflare

El túnel expone el servidor local en `https://cta.tenistac.site`.

Configuración en `~/.cloudflared/config.yml`:
- Tunnel: `cta-monitor`
- Credenciales: `~/.cloudflared/748e7331-cb87-4f1d-9ccd-29bfa6323854.json`
- Binario: `~/bin/cloudflared`

**Arrancar el túnel:**
```bash
bash open-tunnel.sh
```
Abre una nueva ventana Terminal con cloudflared corriendo en primer plano.

**Detener el túnel:**
```bash
bash stop-tunnel.sh
```

**Verificar que el túnel está activo:**
```bash
pgrep -a cloudflared
curl https://cta.tenistac.site/api/standings | head -5
```

## Comandos CLI

```bash
python3 main.py group          # Actualizar posiciones + calendario del grupo (~5 seg)
python3 main.py sync           # Sync completo: standings + grupo + equipo propio (~30 seg)
python3 main.py crawl --full   # Crawl completo: todos los equipos y jugadores (~5 min)
```

## Stack técnico

- **Backend**: FastAPI + Python 3.9 + SQLite (`data/cta.db`)
- **Frontend**: SPA vanilla JS/CSS en `static/`
- **Scraping**: BeautifulSoup4 + requests con sesión autenticada
- **Auth**: ctatenis.com (credenciales en `.env`)
- **Túnel**: Cloudflare Tunnel (`cloudflared 2026.3.0`)
- **Mac Mini**: macOS 12.7.6, Intel Core i5, IP fija 192.168.100.132

## Estructura clave

```
cta-monitor/
├── api.py             # FastAPI — endpoints REST
├── spider.py          # Scraper — parse_team_page(), crawl_group()
├── database.py        # SQLite ORM
├── auth.py            # Sesión autenticada ctatenis.com
├── config.py          # Variables de entorno y constantes
├── main.py            # CLI: sync, group, crawl, rival, draw
├── open-server.sh     # Levanta el servidor FastAPI en nueva ventana Terminal
├── serve.sh           # Script interno que activa venv y lanza uvicorn
├── open-tunnel.sh     # Arranca el túnel Cloudflare en nueva ventana Terminal
├── stop-tunnel.sh     # Detiene el túnel Cloudflare
├── static/            # Frontend SPA
│   ├── index.html
│   ├── app.js
│   └── style.css
└── data/
    └── cta.db         # Base de datos SQLite
```

## Notas importantes

- La página de datos del grupo es `/cts/team_d/{team_id}/` — contiene standings, fixtures y jugadores en 3 tablas exactas
- Los standings del grupo tienen `sets_won IS NOT NULL` (los de la liga general no)
- La sesión de scraping se cachea en `data/session.pkl` (válida 4 horas)
- Zona horaria del dashboard: America/Caracas (UTC-4)

## GitHub Workflow (día a día)

```bash
# Guardar cambios y subir a GitHub
git add -p                        # revisar cambios
git commit -m "descripción"
git push
```

**Archivos excluidos de git** (nunca se suben): `.env`, `data/`, `logs/`
