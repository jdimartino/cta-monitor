// ecosystem.config.js — PM2 para CTA Monitor
// Uso: pm2 start ecosystem.config.js

module.exports = {
  apps: [
    {
      name: "cta-monitor",
      script: "/usr/bin/python3",
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
