"""API REST para generar enlaces de compartir de Google AI Mode."""
import json
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from generate_share_link import generate_ai_share_link

app = FastAPI(title="AI Share Manager API", version="1.0")

SESSIONS_DIR = "/app/sessions"


class ShareRequest(BaseModel):
    prompt: str
    account: str | None = None


class SessionUpload(BaseModel):
    account: str = "primary"
    storage_state: dict


@app.get("/health")
def health():
    sessions = []
    if os.path.isdir(SESSIONS_DIR):
        sessions = [f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")]
    return {"status": "ok", "message": "AI Share Manager operativo", "sessions": sessions}


@app.post("/generate")
def create_share_link(request: ShareRequest):
    result = generate_ai_share_link(request.prompt, request.account)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.post("/session/upload")
def upload_session(payload: SessionUpload):
    """Recibe el storage_state de Playwright y lo guarda como sesión de la cuenta.

    Genera el JSON en local con HEADLESS=false (login manual una sola vez),
    y súbelo aquí para activar la cuenta en el servidor.
    """
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    safe_name = "".join(c for c in payload.account if c.isalnum() or c in "-_") or "account"
    path = os.path.join(SESSIONS_DIR, f"{safe_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload.storage_state, f)
    return {
        "ok": True,
        "account": safe_name,
        "file": path,
        "cookies": len(payload.storage_state.get("cookies", [])),
    }
