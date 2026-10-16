# Развёртывание ППР ОСС

## Docker

```bash
docker compose up -d --build
# http://localhost:8000  admin / admin
```

Положите Excel в `backend/data/` для импорта объектов.

## Telegram

Токен бота и Chat ID настраиваются администратором в Web UI: **Настройки системы → Интеграции**. Секретный токен хранится в БД в зашифрованном виде. Для сохранения секретов задайте постоянный `PPR_SETTINGS_SECRET_KEY` в `.env` (сгенерируйте один раз командой `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) и не меняйте его после сохранения настроек. После сохранения токена бот запускает polling через aiogram. Напишите боту `/start` — он покажет Chat ID; скопируйте его в настройки и сохраните. Команда `/id` повторно показывает Chat ID, а `/help` выводит список команд. Затем откройте **Уведомления → Тест уведомления**. Переменные `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` продолжают поддерживаться как запасной вариант, если соответствующие значения не заданы в Web UI.

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
