# Развёртывание ППР ОСС

## Docker

```bash
docker compose up -d --build
# http://localhost:8000  admin / admin
```

Положите Excel в `backend/data/` для импорта объектов.

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Уведомления |
| `ZABBIX_URL` / `ZABBIX_TOKEN` | Мониторинг |
| `AUTHENTIK_ISSUER` / `AUTHENTIK_CLIENT_ID` / `AUTHENTIK_CLIENT_SECRET` | SSO |
| `PPR_DB_PATH` | Путь к SQLite |

## PWA

Откройте сайт по HTTPS (или localhost) — «Установить приложение».

## React

См. `frontend-react/README.md`. Рабочий UI — встроенный SPA на `/`.
