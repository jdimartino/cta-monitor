# 📊 CTA-Monitor: Resumen Técnico Ejecutivo

## 🏗️ Stack Tecnológico
- **Framework Principal**: FastAPI (Python 3.x) para el Backend / Vanilla JS para el Frontend.
- **Versión Node**: 18.x / 20.x (Utilizado principalmente para gestión con PM2).
- **Package Manager**: npm
- **Build Tool**: Ninguna (Frontend estático / Python Scripts).
- **Deployment**: PM2 (Process Manager) en entorno local (Mac Mini).
- **Base de Datos**: SQLite (almacenada en `data/cta.db`).
- **Integraciones**: Telegram Bot API para notificaciones de cambios.

## 📂 Estructura de Carpetas
```
cta-monitor/
├── data/              # Bases de datos SQLite (.db) y persistencia de sesión (.pkl).
├── logs/              # Registros de salida y errores de la API y el monitor.
├── scripts/           # Scripts auxiliares de mantenimiento (ej: semillas de clubes).
├── static/            # Frontend: index.html, app.js (lógica), style.css (estilos).
├── venv/              # Entorno virtual de Python con dependencias instaladas.
├── api.py             # Punto de entrada de la API FastAPI (endpoints REST/SSE).
├── database.py        # Capa de abstracción de datos y consultas SQL.
├── spider.py          # Lógica de web scraping y parsing de ctatenis.com.
├── main.py            # Orquestador CLI para tareas de sync, crawl y monitor.
├── config.py          # Configuración global, credenciales y mapeo de categorías.
├── ecosystem.config.js # Configuración para despliegue y autorestart con PM2.
├── package.json       # Definición de scripts de inicio y metadatos.
└── requirements.txt   # Dependencias de Python (requests, fastapi, bs4, etc.).
```

## ⚙️ Componentes Clave
- **Monitor**: Script que corre cada 3 horas verificando cambios en el ranking y resultados.
- **Crawler**: Sistema de recolección masiva de datos de jugadores, equipos y jornadas.
- **Draw Predictor**: Motor de predicción de alineaciones rivales basado en datos históricos.
- **API**: Servidor que expone datos al frontend y permite disparar sincronizaciones manuales.
