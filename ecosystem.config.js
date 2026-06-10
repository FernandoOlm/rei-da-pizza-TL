// Arquivo de configuração PM2 para o Ferdinando Monitor Bot
module.exports = {
  apps: [
    {
      name: "monit-bot",
      script: "main.py",
      interpreter: "/home/folmdelima/bot_create/venv/bin/python",
      cwd: "/home/folmdelima/bot_create",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "./logs/pm2_out.log",
      error_file: "./logs/pm2_err.log",
    },
  ],
};
