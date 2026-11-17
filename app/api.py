"""API REST para generar enlaces de compartir de Google AI Mode.

Gestión de sesiones:
- POST /session/cookies         → pega cookies en formato flexible (array JSON o header string)
- POST /session/storage-state   → sube el storage_state completo de Playwright
- GET  /session/list            → sesiones activas + estado keep-alive
- DELETE /session/{account}     → elimina una sesión
"""
import json
import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from generate_share_link import generate_ai_share_link
from keepalive import SESSIONS_DIR, STATE_FILE, start_keepalive_thread
from provider_akr import crear_bare_link
from session_utils import build_storage_state, parse_cookies

app = FastAPI(title="AI Share Manager API", version="1.7")

start_keepalive_thread()


class ShareRequest(BaseModel):
    prompt: str
    account: str | None = None
    type: str = "aimode"  # "aimode" (gratis, propio) | "bare" (AKR, proxy-render directo)


class CookieUpload(BaseModel):
    account: str = "primary"
    cookies: object  # array JSON de cookies O string "SID=..; HSID=.."
    mode: str = "replace"  # "replace" sobrescribe | "merge" suma/actualiza por nombre


class AkrSessionUpload(BaseModel):
    cookie: str  # el valor completo de la cookie gshort.sid=... del navegador


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
        sessions = [f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json") and not f.startswith("_")]
    return {
        "status": "ok",
        "message": "AI Share Manager operativo",
        "sessions": sessions,
        "keepalive": _keepalive_state(),
    }


@app.post("/generate")
def create_share_link(request: ShareRequest):
    if request.type == "bare":
        try:
            return crear_bare_link(request.prompt)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail={"ok": False, "provider": "akr", "error": str(e)})
    result = generate_ai_share_link(request.prompt, request.account)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/akr-session/upload")
def upload_akr_session(payload: AkrSessionUpload):
    """Sube la cookie de sesion de AKR (gshort.sid) para el proveedor bare."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    cookie = payload.cookie.strip()
    if not cookie.startswith("gshort.sid="):
        cookie = "gshort.sid=" + cookie
    with open(os.path.join(SESSIONS_DIR, "akr_cookie.txt"), "w", encoding="utf-8") as f:
        f.write(cookie)
    return {"ok": True, "message": "Sesion AKR guardada"}


@app.get("/akr-session/status")
def akr_session_status():
    path = os.path.join(SESSIONS_DIR, "akr_cookie.txt")
    exists = os.path.exists(path)
    remaining = None
    if exists:
        try:
            from provider_akr import _csrf
            import requests as _r

            s = _r.Session()
            s.headers["Cookie"] = open(path, encoding="utf-8").read().strip()
            s.headers["User-Agent"] = "Mozilla/5.0 Chrome/131"
            r = s.get("https://akrshortener.com/subscription", timeout=20)
            txt = re.sub(r"<[^>]+>", "\n", r.text)
            m = re.findall(r"(\d+)\s+links?\s+available", txt)
            remaining = int(m[0]) if m else None
        except Exception as e:  # noqa: BLE001
            return {"session": exists, "valid": False, "error": str(e)[:120]}
    return {"session": exists, "links_available": remaining}


@app.post("/session/cookies")
def upload_cookies(payload: CookieUpload):
    """Pega cookies capturadas desde tu navegador (DevTools o extensión).

    Acepta:
      - Array JSON: [{"name":"SID","value":"..",...}, ...]
      - String header: "SID=abc; HSID=def; SAPISID=xyz"
    """
    try:
        new_cookies = parse_cookies(payload.cookies)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": "formato_invalido", "detail": str(e)})

    if not new_cookies:
        raise HTTPException(status_code=400, detail={"error": "sin_cookies_utiles"})
    if not any(c["name"] in ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SSID", "HSID") for c in new_cookies):
        raise HTTPException(
            status_code=400,
            detail={"error": "parece_no_ser_sesion_google", "hint": "Debe incluir cookies de sesión de Google (SAPISID/HSID/SSID...)"},
        )

    path = _session_path(payload.account)
    existing: dict = {}
    if payload.mode == "merge" and os.path.exists(path):
        try:
            for c in json.load(open(path, encoding="utf-8")).get("cookies", []):
                existing[c["name"]] = c
        except Exception:
            existing = {}
    for c in new_cookies:
        existing[c["name"]] = c
    merged = list(existing.values())

    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_storage_state(merged), f)

    return {
        "ok": True,
        "account": payload.account,
        "cookies": len(merged),
        "added_this_request": len(new_cookies),
        "mode": payload.mode,
        "file": path,
    }


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


@app.get("/debug/list")
def debug_list():
    d = os.path.join(SESSIONS_DIR, "debug")
    if not os.path.isdir(d):
        return {"files": []}
    files = sorted(
        (f, os.path.getsize(os.path.join(d, f))) for f in os.listdir(d) if f.endswith(".png")
    )
    return {"files": [{"name": n, "bytes": s} for n, s in files]}


@app.get("/debug/{name}")
def debug_get(name: str):
    safe = os.path.basename(name)
    path = os.path.join(SESSIONS_DIR, "debug", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail={"error": "archivo_no_encontrado"})
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type="image/png")


@app.delete("/session/{account}")
def delete_session(account: str):
    path = _session_path(account)
    if os.path.exists(path):
        os.remove(path)
        return {"ok": True, "deleted": account}
    raise HTTPException(status_code=404, detail={"error": "sesion_no_encontrada"})
