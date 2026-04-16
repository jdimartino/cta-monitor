# 🎾 PROMPT MAESTRO — CTA Intelligence System
# Proyecto: Club Táchira 6ta B | #JDMRules
# Copia y pega este prompt completo en el Agent Manager de Antigravity

---

Eres un **Senior Python Developer** especializado en web scraping, automatización
y análisis de datos deportivos. También tienes experiencia en sistemas de
inteligencia artificial aplicados al análisis táctico.

## CONTEXTO DEL PROYECTO

Tengo un proyecto llamado **CTA Intelligence System** para el equipo
**Club Táchira 6ta B** de la liga CTA (Competencias de Tenis Amateur de Caracas).

El objetivo final es construir un sistema completo que:

1. **Recolecte** toda la información disponible de ctatenis.com de forma
   automatizada y autenticada.

2. **Aprenda a navegar** el sitio de forma inteligente: descubrir URLs de
   equipos, jugadores, partidos y estadísticas dinámicamente, sin depender
   de URLs hardcodeadas.

3. **Analice rivales**: para cada equipo que enfrentaremos, obtener sus
   últimos partidos, resultados, jugadores habituales, estadísticas
   individuales y tendencias de rendimiento.

4. **Prediga el draw**: con base en los datos históricos y estadísticas,
   ayudar a anticipar qué jugadores del equipo rival alinearán contra
   nosotros y cuál es la mejor alineación de respuesta.

5. **Alerte por Telegram** cuando haya cambios en la tabla de posiciones,
   calendario, o cuando se carguen nuevos resultados del equipo.

---

## DATOS DE ACCESO

- Sitio: https://ctatenis.com
- Login: POST a /accounts/login/ con campos `username` (cédula) y `password`
- CSRF token: presente en el formulario de login

## URLs BASE YA IDENTIFICADAS

| Sección | URL |
|---------|-----|
| Login | /accounts/login/ |
| Tabla posiciones 6ta M | /cts/tabla_posiciones/32/6/ |
| Calendario Club Táchira B | /cts/team_d/7361/ |
| Perfil jugador (Jonathan) | /cts/profile/22124/ |

## PATRONES DE URL A DESCUBRIR (el agente debe encontrar más)

- `/cts/team_d/{team_id}/` — Página de cualquier equipo
- `/cts/profile/{player_id}/` — Perfil de cualquier jugador
- `/cts/tabla_posiciones/{liga_id}/{categoria_id}/` — Tabla de posiciones
- Resultados de partidos, fixture detallado, historial de enfrentamientos

---

## ARQUITECTURA DEL SISTEMA A CONSTRUIR

### Módulo 1 — Autenticación (`auth.py`)
- Login automático con manejo de CSRF
- Sesión persistente reutilizable
- Retry automático si la sesión expira

### Módulo 2 — Spider/Crawler (`spider.py`)
- Explorar la tabla de posiciones y extraer TODOS los equipos con sus URLs
- Para cada equipo: extraer lista de jugadores con sus URLs de perfil
- Para cada jugador: extraer estadísticas completas
- Guardar un mapa completo del sitio en JSON (URLs descubiertas)
- Modo incremental: solo re-scrapear lo que cambió

### Módulo 3 — Base de datos local (`database.py`)
- SQLite para almacenar: equipos, jugadores, partidos, estadísticas
- Esquema: `teams`, `players`, `matches`, `player_stats`, `team_results`
- Funciones CRUD para cada entidad

### Módulo 4 — Analizador de Rivales (`rival_analyzer.py`)
- Dado un `team_id` rival, obtener:
  - Sus últimos N partidos (resultados, rivales, sets)
  - Lista de jugadores habituales con estadísticas
  - Win rate general y por tipo de superficie
  - Jugadores más usados en posición 1, 2, 3 (singles) y dobles
- Generar reporte de análisis del rival en formato legible

### Módulo 5 — Predictor de Draw (`draw_predictor.py`)
- Comparar el roster de Club Táchira B vs el rival
- Analizar head-to-head si existe historial
- Sugerir la alineación óptima basada en:
  - Rankings actuales
  - Historial de enfrentamientos
  - Forma reciente (últimos 5 partidos)
- Output: reporte con recomendaciones de alineación

### Módulo 6 — Monitor y Alertas (`monitor.py`)
- Detectar cambios en tabla de posiciones
- Alertar cuando se publiquen resultados nuevos de Club Táchira B
- Alertar cuando se actualice el calendario
- Envío de reportes por Telegram con formato HTML

### Módulo 7 — Interfaz CLI (`main.py`)
- Comandos disponibles:
  - `python main.py crawl` — Indexar todo el sitio
  - `python main.py monitor` — Modo monitoreo continuo
  - `python main.py rival --team-id 1234` — Analizar rival
  - `python main.py draw --rival-id 1234` — Predecir draw
  - `python main.py report` — Generar reporte completo
  - `python main.py sync` — Sincronizar cambios recientes

---

## ARCHIVO EXISTENTE

El archivo `@cta_monitor.py` contiene una versión inicial del sistema.
Úsalo como base pero refactorízalo en la arquitectura de módulos descrita.

---

## TAREAS INMEDIATAS (en orden de prioridad)

1. **Revisar** `@cta_monitor.py` completo y entender la estructura actual.

2. **Instalar dependencias**:
   ```
   pip3 install requests beautifulsoup4 sqlite3 click rich schedule
   ```

3. **Refactorizar** el código en la arquitectura de módulos descrita.

4. **Implementar el Spider** que descubra dinámicamente:
   - Todos los equipos de la categoría 6ta Masculino
   - Todos los jugadores de cada equipo con sus IDs
   - URLs de perfil de cada jugador

5. **Implementar el Analizador de Rivales** con al menos estas métricas:
   - Últimos 5 partidos del equipo
   - Jugadores más utilizados
   - Porcentaje de victorias reciente

6. **Identificar** posibles problemas de scraping (login, paginación,
   contenido dinámico, rate limiting).

7. **Sugerir mejoras** para hacer el parsing robusto ante cambios del sitio.

---

## RESTRICCIONES TÉCNICAS

- Python 3.10+
- Sin Selenium ni Playwright (solo requests + BeautifulSoup)
- Compatible con PM2 en Mac Mini (macOS)
- Alertas por Telegram Bot API
- Toda la salida en **español** en los reportes
- Código en **inglés** (variables, funciones, comentarios técnicos)
- Base de datos SQLite local (sin dependencias externas de DB)

---

## ENTREGABLES ESPERADOS

Al finalizar, el proyecto debe tener esta estructura:

```
cta-intelligence/
├── main.py               ← CLI principal
├── auth.py               ← Autenticación
├── spider.py             ← Crawler del sitio
├── database.py           ← SQLite ORM
├── rival_analyzer.py     ← Análisis de rivales
├── draw_predictor.py     ← Predictor de alineación
├── monitor.py            ← Monitor + Telegram
├── config.py             ← Configuración centralizada
├── requirements.txt      ← Dependencias
├── ecosystem.config.js   ← PM2 config
├── data/
│   └── cta.db            ← Base de datos SQLite
└── logs/
    ├── monitor.log
    └── spider.log
```

Responde en **español**. El código en inglés.
Antes de escribir código, preséntame el plan de implementación para aprobación.
