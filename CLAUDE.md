# CTA Monitor — Instrucciones del Proyecto

## Arquitectura de trabajo

**Código fuente en MacBook Air. Base de datos y servidor en Mac Mini.**

| Elemento | Ubicación |
|----------|-----------|
| Código fuente | `macbook:~/Desktop/Antigravity/cta-monitor/` |
| Base de datos | `mac-mini:~/antigravity/cta-monitor/data/cta.db` |
| Servidor API | `http://192.168.1.5:8000` (corre en Mac Mini) |
| SSH alias | `ssh mac-mini` |

El frontend (`static/app.js`) llama directamente a `http://192.168.1.5:8000/api/...` — la Mac Mini atiende todas las consultas de datos.

## Cómo abrir el proyecto

Doble clic en el archivo:
```
~/Desktop/Antigravity/cta-monitor.code-workspace
```
VS Code abre la carpeta **local** en el MacBook Air. No requiere conexión SSH.

Para ver el dashboard: instala la extensión **Live Server** en VS Code y abre `static/index.html` con "Open with Live Server".

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

## Comandos CLI (correr via SSH en la Mac Mini)

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


## Setup inicial en MacBook Air M1 (primera vez)

```bash
# 1. Clonar el repositorio
cd ~/Desktop/Antigravity
git clone https://github.com/jdimartino/cta-monitor.git
```

Eso es todo. No se necesita Python local ni `.env` — el backend corre en la Mac Mini.

**VS Code:**
1. Abrir `cta-monitor.code-workspace` (doble clic)
2. Instalar extensión **Live Server** (`ritwickdey.liveserver`)
3. Click derecho en `static/index.html` → "Open with Live Server"
4. El dashboard abre en `http://127.0.0.1:5500` y consulta datos desde `192.168.1.5:8000`

## GitHub Workflow (día a día)

```bash
# Guardar cambios y subir a GitHub
git add -p                        # revisar cambios
git commit -m "descripción"
git push

# En la Mac Mini — actualizar el servidor con los cambios
ssh mac-mini "cd ~/antigravity/cta-monitor && git pull"
```

**Archivos excluidos de git** (nunca se suben): `.env`, `data/`, `logs/`

