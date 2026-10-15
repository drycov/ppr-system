"""Интеграция с Zabbix API (опционально)."""
import os
import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("ppr.zabbix")

ZABBIX_URL = os.environ.get("ZABBIX_URL", "").rstrip("/")  # https://zabbix.example/api_jsonrpc.php
ZABBIX_USER = os.environ.get("ZABBIX_USER", "")
ZABBIX_PASSWORD = os.environ.get("ZABBIX_PASSWORD", "")
ZABBIX_TOKEN = os.environ.get("ZABBIX_TOKEN", "")  # API token (Zabbix 5.4+)


def _rpc(method: str, params: dict, auth=None) -> dict:
    if not ZABBIX_URL:
        raise RuntimeError("ZABBIX_URL не задан")
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    if auth:
        payload["auth"] = auth
    body = json.dumps(payload).encode()
    req = Request(ZABBIX_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def login() -> str:
    if ZABBIX_TOKEN:
        return ZABBIX_TOKEN
    return _rpc("user.login", {"username": ZABBIX_USER, "password": ZABBIX_PASSWORD})


def get_host_status(host_name: str) -> dict:
    """Статус хоста по имени (доступность)."""
    auth = login()
    hosts = _rpc("host.get", {
        "filter": {"host": [host_name]},
        "output": ["hostid", "host", "name", "status"],
        "selectInterfaces": ["ip", "available"],
    }, auth=auth)
    if not hosts:
        return {"found": False, "host": host_name}
    h = hosts[0]
    return {
        "found": True,
        "hostid": h.get("hostid"),
        "host": h.get("host"),
        "name": h.get("name"),
        "status": h.get("status"),  # 0=enabled
        "interfaces": h.get("interfaces", []),
    }


def ping() -> dict:
    if not ZABBIX_URL:
        return {"configured": False, "message": "Задайте ZABBIX_URL, ZABBIX_TOKEN или USER/PASSWORD"}
    try:
        auth = login()
        ver = _rpc("apiinfo.version", {}, auth=None)
        return {"configured": True, "ok": True, "version": ver, "auth": bool(auth)}
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}
