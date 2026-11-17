"""API REST para generar enlaces de compartir de Google AI Mode.

Gestión de sesiones:
- POST /session/cookies         → pega cookies en formato flexible (array JSON o header string)
- POST /session/storage-state   → sube el storage_state completo de Playwright
- GET  /session/list            → sesiones activas + estado keep-alive
- DELETE /session/{account}     → elimina una sesión
"""
import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from generate_share_link import generate_ai_share_link
from keepalive import SESSIONS_DIR, STATE_FILE, start_keepalive_thread
from session_utils import build_storage_state, parse_cookies

app = FastAPI(title="AI Share Manager API", version="1.2")

start_keepalive_thread()


class ShareRequest(BaseModel):
    prompt: str
    account: str | None = None


class CookieUpload(BaseModel):
    account: str = "primary"
    cookies: object  # array JSON de cookies O string "SID=..; HSID=.."


class StorageStateUpload(BaseModel):
    account: str = "primary"
    storage_state: dict


def _session_path(account: str) -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    safe = "".join(c for c in account if c.isalnum() or c in "-_") or "account"
    return os.path.join(SESSIONS_DIR, f"{safe}.json")


def _keepalive_state() -> dict:
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


@app.get("/health")
def health():
    sessions = []
    if os.path.isdir(SESSIONS_DIR):
        sessions = [f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")]
    return {
        "status": "ok",
        "message": "AI Share Manager operativo",
        "sessions": sessions,
        "keepalive": _keepalive_state(),
    }


@app.post("/generate")
def create_share_link(request: ShareRequest):
    result = generate_ai_share_link(request.prompt, request.account)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/session/cookies")
def upload_cookies(payload: CookieUpload):
    """Pega cookies capturadas desde tu navegador (DevTools o extensión).

    Acepta:
      - Array JSON: [{"name":"SID","value":"..",...}, ...]
      - String header: "SID=abc; HSID=def; SAPISID=xyz"
    """
    try:
        cookies = parse_cookies(payload.cookies)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "formato_invalido", "detail": str(e)})

    if not cookies:
        raise HTTPException(status_code=400, detail={"error": "sin_cookies_utiles"})
    if not any(c["name"] in ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SSID", "HSID") for c in cookies):
        raise HTTPException(
            status_code=400,
            detail={"error": "parece_no_ser_sesion_google", "hint": "Debe incluir cookies de sesión de Google (SAPISID/HSID/SSID...)"},
        )

    path = _session_path(payload.account)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_storage_state(cookies), f)

    return {"ok": True, "account": payload.account, "cookies": len(cookies), "file": path}


@app.post("/session/storage-state")
def upload_storage_state(payload: StorageStateUpload):
    """Sube el storage_state completo generado por Playwright (crear_sesion.py)."""
    if not payload.storage_state.get("cookies"):
        raise HTTPException(status_code=400, detail={"error": "storage_state_sin_cookies"})
    path = _session_path(payload.account)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload.storage_state, f)
    return {
        "ok": True,
        "account": payload.account,
        "cookies": len(payload.storage_state.get("cookies", [])),
        "file": path,
    }


@app.get("/session/list")
def session_list():
    sessions = []
    ka = _keepalive_state()
    if os.path.isdir(SESSIONS_DIR):
        for f in os.listdir(SESSIONS_DIR):
            if f.endswith(".json") and not f.startswith("_"):
                account = f[:-5]
                sessions.append({"account": account, "keepalive": ka.get(account)})
    return JSONResponse({"sessions": sessions})


@app.delete("/session/{account}")
def delete_session(account: str):
    path = _session_path(account)
    if os.path.exists(path):
        os.remove(path)
        return {"ok": True, "deleted": account}
    raise HTTPException(status_code=404, detail={"error": "sesion_no_encontrada"})
