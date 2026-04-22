// ecosystem.config.js — PM2 para CTA Monitor
// Uso: pm2 start ecosystem.config.js

module.exports = {
  apps: [
    {
      name: "cta-api",
      script: __dirname + "/venv/bin/uvicorn",
      args: "api:app --host 0.0.0.0 --port 8000",
      interpreter: "none",
      cwd: __dirname,
      autorestart: true,
      watch: false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "./logs/cta_api_out.log",
      error_file: "./logs/cta_api_err.log",
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: "cta-monitor",
      script: __dirname + "/venv/bin/python",
      args: __dirname + "/main.py monitor",
      cron_restart: "0 */3 * * *",               // Cada 3 horas
      autorestart: false,                         // No reiniciar si termina OK
      watch: false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "./logs/cta_monitor_out.log",
      error_file: "./logs/cta_monitor_err.log",
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
