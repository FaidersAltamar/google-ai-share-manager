"""API REST para generar enlaces de compartir de Google AI Mode."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from generate_share_link import generate_ai_share_link

app = FastAPI(title="AI Share Manager API", version="1.0")


class ShareRequest(BaseModel):
    prompt: str
    account: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "message": "AI Share Manager operativo"}


@app.post("/generate")
def create_share_link(request: ShareRequest):
    result = generate_ai_share_link(request.prompt, request.account)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result
