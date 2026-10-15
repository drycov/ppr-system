"""Централизованные настройки приложения ППР, хранящиеся в БД."""
from copy import deepcopy
from datetime import datetime
import os
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session
from models import SystemSetting, SettingsAudit

SETTINGS_CATALOG = [
 {"key":"organization.name","category":"Организация","label":"Название организации","description":"Название в заголовках и документах.","type":"str","default":"ТОО «Satory Company ltd»"},
 {"key":"organization.branch","category":"Организация","label":"Филиал","description":"Название филиала/площадки.","type":"str","default":"Филиал в г. Усть-Каменогорск"},
 {"key":"organization.department","category":"Организация","label":"Подразделение","description":"Подразделение, ответственное за ППР.","type":"str","default":"Отдел сетей связи и группа IT (ОСС)"},
 {"key":"organization.city","category":"Организация","label":"Город","description":"Город обслуживания.","type":"str","default":"Усть-Каменогорск"},
 {"key":"organization.address","category":"Организация","label":"Адрес","description":"Адрес организации для документов.","type":"str","default":"Республика Казахстан, г. Усть-Каменогорск"},
 {"key":"organization.phone","category":"Организация","label":"Телефон","description":"Контактный телефон для документов.","type":"str","default":""},
 {"key":"organization.email","category":"Организация","label":"E-mail","description":"Контактный адрес электронной почты.","type":"str","default":""},
 {"key":"planning.auto_generate","category":"Планирование ППР","label":"Автогенерация планов","description":"Автоматически создавать план в первый день месяца.","type":"bool","default":True},
 {"key":"planning.prefer_duty","category":"Планирование ППР","label":"Назначать дежурного в приоритете","description":"Предпочитать дежурного исполнителя при автоматическом назначении.","type":"bool","default":True},
 {"key":"planning.include_daily_templates","category":"Планирование ППР","label":"Включать ежедневные шаблоны","description":"Учитывать шаблоны с ежедневной периодичностью при генерации планов.","type":"bool","default":False},
 {"key":"planning.only_without_plan","category":"Планирование ППР","label":"Не создавать дубликаты","description":"Пропускать задачи, если план на этот период уже существует.","type":"bool","default":True},
 {"key":"planning.default_horizon_months","category":"Планирование ППР","label":"Горизонт планирования (месяцы)","description":"Рекомендуемый горизонт для планирования и отчётов.","type":"int","default":1,"min":1,"max":24},
 {"key":"planning.overdue_after_days","category":"Планирование ППР","label":"Считать просроченной через (дней)","description":"Число дней после плановой даты для контроля просрочки.","type":"int","default":0,"min":0,"max":365},
 {"key":"duty.enabled","category":"Дежурства","label":"Использовать график дежурств","description":"Разрешить назначение исполнителей по графику дежурств.","type":"bool","default":True},
 {"key":"duty.default_shift","category":"Дежурства","label":"Смена по умолчанию","description":"Тип смены при создании дежурства.","type":"str","default":"day","choices":["day","night","full"]},
 {"key":"daily.require_comment_on_issue","category":"Ежедневный контроль","label":"Требовать комментарий при проблеме","description":"Правило фиксации замечаний в чек-листе.","type":"bool","default":True},
 {"key":"daily.require_incidents_logged","category":"Ежедневный контроль","label":"Обязательная фиксация инцидентов","description":"Включает обязательность пункта регистрации инцидентов.","type":"bool","default":True},
 {"key":"notifications.overdue_enabled","category":"Уведомления","label":"Уведомления о просрочках","description":"Уведомлять о просроченных задачах.","type":"bool","default":True},
 {"key":"notifications.duty_enabled","category":"Уведомления","label":"Напоминания о дежурствах","description":"Отправлять ежедневные напоминания о дежурствах.","type":"bool","default":True},
 {"key":"notifications.auto_plan_enabled","category":"Уведомления","label":"Уведомления о генерации планов","description":"Уведомлять о результате автоматической генерации.","type":"bool","default":True},
 {"key":"scheduler.interval_seconds","category":"Планировщик","label":"Интервал фоновой проверки (сек.)","description":"Интервал между проверками; применяется при следующем запуске процесса.","type":"int","default":3600,"min":60,"max":86400,"restart_required":True},
 {"key":"reports.include_company_header","category":"Отчёты","label":"Реквизиты организации в отчётах","description":"Показывать сведения организации в отчётных документах.","type":"bool","default":True},
 {"key":"reports.date_format","category":"Отчёты","label":"Формат даты","description":"Формат отображения даты в интерфейсе и документах.","type":"str","default":"DD.MM.YYYY","choices":["DD.MM.YYYY","YYYY-MM-DD","DD/MM/YYYY"]},
 {"key":"ui.primary_color","category":"Интерфейс","label":"Основной цвет интерфейса","description":"Акцентный цвет интерфейса в HEX.","type":"str","default":"#0f766e"},
 {"key":"ui.page_size","category":"Интерфейс","label":"Размер страницы таблиц","description":"Количество записей по умолчанию в списках.","type":"int","default":100,"min":10,"max":500},
 {"key":"integrations.zabbix.enabled","category":"Интеграции","label":"Включить интеграцию Zabbix","description":"Разрешение на использование интеграции Zabbix.","type":"bool","default":False},
 {"key":"integrations.zabbix.url","category":"Интеграции","label":"URL Zabbix","description":"Базовый URL Zabbix API.","type":"str","default":""},
 {"key":"integrations.zabbix.token","category":"Интеграции","label":"Токен Zabbix","description":"Секретный токен хранится в БД; API возвращает только признак наличия.","type":"secret","default":""},
 {"key":"integrations.telegram.enabled","category":"Интеграции","label":"Включить Telegram","description":"Разрешить отправку уведомлений ППР в Telegram. Для отправки укажите токен бота и chat ID.","type":"bool","default":true},
 {"key":"integrations.telegram.bot_token","category":"Интеграции","label":"Токен Telegram-бота","description":"Токен от @BotFather. Хранится в БД в зашифрованном виде; API его не раскрывает.","type":"secret","default":""},
 {"key":"integrations.telegram.chat_id","category":"Интеграции","label":"Telegram Chat ID","description":"ID личного чата, группы или канала, куда отправлять уведомления.","type":"str","default":""}
]
CATALOG_BY_KEY = {item["key"]: item for item in SETTINGS_CATALOG}

def _validate(spec, value):
 kind = spec["type"]
 if kind == "secret":
  if not isinstance(value, str) or len(value) > 4096: raise ValueError("Секрет должен быть строкой длиной не более 4096 символов")
  return value
 if kind == "bool":
  if not isinstance(value, bool): raise ValueError("Ожидается логическое значение")
  return value
 if kind == "int":
  if isinstance(value, bool) or not isinstance(value, int): raise ValueError("Ожидается целое число")
  if value < spec.get("min", -2147483648) or value > spec.get("max", 2147483647): raise ValueError("Значение вне допустимого диапазона")
  return value
 if kind == "float":
  if isinstance(value, bool) or not isinstance(value, (int, float)): raise ValueError("Ожидается число")
  return float(value)
 if kind == "str":
  if not isinstance(value, str) or len(value) > 4000: raise ValueError("Ожидается строка длиной не более 4000 символов")
  if "choices" in spec and value not in spec["choices"]: raise ValueError("Недопустимое значение")
  if spec["key"] == "ui.primary_color" and (len(value) != 7 or not value.startswith("#") or any(c not in "0123456789abcdefABCDEF" for c in value[1:])): raise ValueError("Цвет должен быть в формате #RRGGBB")
  return value
 if kind == "json":
  if not isinstance(value, (dict, list, str, int, float, bool, type(None))): raise ValueError("Недопустимый JSON")
  return value
 raise ValueError("Неизвестный тип настройки")

def _fernet():
 key = os.environ.get("PPR_SETTINGS_SECRET_KEY", "").strip()
 if not key:
  raise ValueError("Для хранения секретов задайте PPR_SETTINGS_SECRET_KEY (ключ Fernet)")
 try:
  return Fernet(key.encode("ascii"))
 except Exception as exc:
  raise ValueError("PPR_SETTINGS_SECRET_KEY должен быть корректным ключом Fernet") from exc

def _encrypt_secret(value: str) -> str:
 if not value:
  return ""
 return "enc:v1:" + _fernet().encrypt(value.encode("utf-8")).decode("ascii")

def _decrypt_secret(value: str) -> str:
 if not value:
  return ""
 if not isinstance(value, str) or not value.startswith("enc:v1:"):
  raise RuntimeError("Обнаружен незашифрованный секрет в БД; задайте PPR_SETTINGS_SECRET_KEY и заново сохраните секрет через Web UI")
 try:
  return _fernet().decrypt(value[7:].encode("ascii")).decode("utf-8")
 except (InvalidToken, UnicodeError) as exc:
  raise RuntimeError("Не удалось расшифровать секрет настроек; проверьте PPR_SETTINGS_SECRET_KEY") from exc

def get_setting(db: Session, key: str):
 spec = CATALOG_BY_KEY.get(key)
 if not spec: return None
 row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
 if row is None:
  return deepcopy(spec["default"])
 if spec["type"] == "secret":
  return _decrypt_secret(row.value)
 return row.value

def get_settings_snapshot(db: Session, include_secrets: bool = False):
 rows = {r.key:r for r in db.query(SystemSetting).all()}
 result = []
 for spec in SETTINGS_CATALOG:
  row = rows.get(spec["key"])
  value = row.value if row else deepcopy(spec["default"])
  item = dict(spec, value=value, is_overridden=row is not None, updated_at=row.updated_at.isoformat() if row and row.updated_at else None)
  if spec["type"] == "secret":
   item["configured"] = bool(value)
   item["value"] = ""
  result.append(item)
 return result

def save_settings(db: Session, values: dict, actor: str):
 if not isinstance(values, dict): raise ValueError("Поле settings должно быть объектом")
 unknown = sorted(set(values) - set(CATALOG_BY_KEY))
 if unknown: raise ValueError("Неизвестные настройки: " + ", ".join(unknown))
 rows = {r.key:r for r in db.query(SystemSetting).filter(SystemSetting.key.in_(list(values))).all()} if values else {}
 changed = {}
 for key, raw in values.items():
  spec = CATALOG_BY_KEY[key]
  value = _validate(spec, raw)
  if spec["type"] == "secret" and value == "": continue
  row = rows.get(key)
  stored_value = _encrypt_secret(value) if spec["type"] == "secret" else value
  old_value = row.value if row else deepcopy(spec["default"])
  if old_value == stored_value: continue
  if row is None:
   row = SystemSetting(key=key, value=stored_value)
   db.add(row)
  else: row.value = stored_value
  row.updated_at = datetime.utcnow()
  changed[key] = {"old":"***" if spec["type"] == "secret" else old_value, "new":"***" if spec["type"] == "secret" else value}
 if changed:
  db.add(SettingsAudit(actor=actor, action="update", changes=changed, created_at=datetime.utcnow()))
  db.commit()
 return changed
