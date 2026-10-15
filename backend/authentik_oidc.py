"""Опциональный вход через Authentik (OIDC).

Переменные окружения:
  AUTHENTIK_ISSUER=https://auth.example.com/application/o/ppr/
  AUTHENTIK_CLIENT_ID=...
  AUTHENTIK_CLIENT_SECRET=...
  AUTHENTIK_REDIRECT_URI=http://localhost:8000/api/auth/oidc/callback

Полный OIDC flow можно включить при наличии httpx/authlib.
Сейчас — конфиг и health-check discovery.
"""
import os
import json
from urllib.request import urlopen

ISSUER = os.environ.get("AUTHENTIK_ISSUER", "").rstrip("/")
CLIENT_ID = os.environ.get("AUTHENTIK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AUTHENTIK_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("AUTHENTIK_REDIRECT_URI", "http://localhost:8000/api/auth/oidc/callback")


def is_configured() -> bool:
    return bool(ISSUER and CLIENT_ID)


def discovery() -> dict:
    if not ISSUER:
        return {"configured": False}
    url = f"{ISSUER}/.well-known/openid-configuration"
    try:
        with urlopen(url, timeout=10) as resp:
            conf = json.loads(resp.read().decode())
        return {
            "configured": True,
            "ok": True,
            "issuer": conf.get("issuer"),
            "authorization_endpoint": conf.get("authorization_endpoint"),
            "token_endpoint": conf.get("token_endpoint"),
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
        }
    except Exception as e:
        return {"configured": True, "ok": False, "error": str(e)}


def login_url(state: str = "ppr") -> str | None:
    d = discovery()
    if not d.get("ok"):
        return None
    from urllib.parse import urlencode
    q = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    })
    return f"{d['authorization_endpoint']}?{q}"
