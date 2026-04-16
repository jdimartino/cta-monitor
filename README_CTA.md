# CTA Tenis Monitor 🎾
## Club Táchira 6ta B — #JDMRules

Script de monitoreo automático para ctatenis.com con alertas por Telegram.

---

## Instalación

### 1. Dependencias Python
```bash
pip3 install requests beautifulsoup4
```

### 2. Configura tus credenciales
Edita `cta_monitor.py` y rellena estas 4 variables al inicio:

```python
CTA_CEDULA      = "TU_CEDULA"
CTA_PASSWORD    = "TU_PASSWORD"
TELEGRAM_TOKEN  = "TU_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TU_CHAT_ID"
```

> Para obtener tu Telegram Chat ID: escríbele a @userinfobot en Telegram.

### 3. Prueba manual
```bash
# Ejecutar UNA vez (solo notifica si hay cambios)
python3 cta_monitor.py

# Forzar notificación aunque no haya cambios (para probar)
python3 cta_monitor.py --force
```

---

## Configuración con PM2 (Mac Mini 24/7)

### 1. Edita ecosystem.config.js
Cambia la ruta del script:
```js
args: "/Users/tu_usuario/scripts/cta_monitor.py",
```

### 2. Inicia con PM2
```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup  # Para que inicie con el sistema
```

### 3. Comandos útiles PM2
```bash
pm2 list                    # Ver estado
pm2 logs cta-monitor        # Ver logs en tiempo real
pm2 restart cta-monitor     # Reiniciar
pm2 stop cta-monitor        # Detener
```

---

## Horario de ejecución
Por defecto: **cada 3 horas** (`0 */3 * * *`)

Para cambiarlo, edita `cron_restart` en `ecosystem.config.js`:
- Cada hora:    `"0 * * * *"`
- Cada 6 horas: `"0 */6 * * *"`
- Solo mañanas: `"0 8 * * *"`

---

## Qué monitorea

| Sección | URL |
|---------|-----|
| Tabla de posiciones 6ta M | `/cts/tabla_posiciones/32/6/` |
| Calendario Club Táchira B | `/cts/team_d/7361/` |
| Perfil jugador (Jonathan) | `/cts/profile/22124/` |

Solo envía notificación Telegram cuando **detecta cambios** (compara hash MD5 del HTML).

---

## Estructura de archivos
```
cta_monitor.py       ← Script principal
ecosystem.config.js  ← Configuración PM2
cta_state.json       ← Estado anterior (auto-generado)
logs/
  cta_monitor_out.log
  cta_monitor_err.log
```
