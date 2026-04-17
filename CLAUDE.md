# CTA Monitor — Instrucciones del Proyecto

## Arquitectura de trabajo

**TODOS los archivos viven en la Mac Mini, no en el MacBook Air.**

| Elemento | Ubicación |
|----------|-----------|
| Código fuente | `mac-mini:/Users/jdimartino/antigravity/cta-monitor/` |
| Base de datos | `mac-mini:/Users/jdimartino/antigravity/cta-monitor/data/cta.db` |
| Servidor web | `http://192.168.1.5:8000` |
| SSH alias | `ssh mac-mini` |

## Cómo abrir el proyecto

Doble clic en el archivo:
```
~/Desktop/Antigravity/cta-monitor.code-workspace
```
VS Code se conecta automáticamente a la Mac Mini y abre la carpeta correcta.
**No abrir carpetas locales — todo el trabajo es remoto.**

## Servidor

El servidor FastAPI arranca automáticamente cuando prende la Mac Mini (`crontab @reboot`).

Si necesitas reiniciarlo manualmente:
```bash
ssh mac-mini
cd ~/antigravity/cta-monitor
pkill -f "uvicorn api:app"
nohup python3 -m uvicorn api:app --host 0.0.0.0 --port 8000 >> logs/server.log 2>&1 &
```

Ver logs del servidor:
```bash
ssh mac-mini "tail -50 ~/antigravity/cta-monitor/logs/server.log"
```

## Comandos CLI (correr en el terminal del IDE — que está en la Mac Mini)

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
- **Mac Mini**: macOS 12.7.6, Intel Core i5, IP fija 192.168.1.5

## Estructura clave

```
cta-monitor/
├── api.py           # FastAPI — endpoints REST
├── spider.py        # Scraper — parse_team_page(), crawl_group()
├── database.py      # SQLite ORM
├── auth.py          # Sesión autenticada ctatenis.com
├── config.py        # Variables de entorno y constantes
├── main.py          # CLI: sync, group, crawl, rival, draw
├── static/          # Frontend SPA
│   ├── index.html
│   ├── app.js
│   └── style.css
└── data/
    └── cta.db       # Base de datos SQLite
```

## Notas importantes

- La página de datos del grupo es `/cts/team_d/{team_id}/` — contiene standings, fixtures y jugadores en 3 tablas exactas
- Los standings del grupo tienen `sets_won IS NOT NULL` (los de la liga general no)
- La sesión de scraping se cachea en `data/session.pkl` (válida 4 horas)
- Zona horaria del dashboard: America/Caracas (UTC-4)
