"""API REST para generar enlaces de compartir de Google AI Mode.

Proveedores 100% propios (sin servicios de terceros):
- aimode: conversación AI Mode compartida (funciona hoy, gratis)
- registro manual de tokens acuñados desde el iPhone del operador (/links/bare)

Gestión de sesiones:
- POST /session/cookies         → pega cookies en formato flexible (array JSON o header string)
- POST /session/storage-state   → sube el storage_state completo de Playwright
- GET  /session/list            → sesiones activas + estado keep-alive
- DELETE /session/{account}     → elimina una sesión

Enlaces bare (token acuñado manualmente o por worker):
- POST /links/bare   → registra un código share.google, valida cadena, cataloga y devuelve link final
- GET  /links/list   → catálogo con estado de verificación
- POST /links/queue  → encola URL para procesamiento externo
- GET  /links/queue  → el worker toma el siguiente trabajo
"""
import json
import os
import re
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from generate_share_link import generate_ai_share_link
from keepalive import SESSIONS_DIR, STATE_FILE, start_keepalive_thread
from session_utils import build_storage_state, parse_cookies

app = FastAPI(title="AI Share Manager API", version="1.9")

start_keepalive_thread()

SESSIONS_DIR = "/app/sessions"
LINKS_FILE = os.path.join(SESSIONS_DIR, "links_bare.json")
QUEUE_FILE = os.path.join(SESSIONS_DIR, "queue.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"


class ShareRequest(BaseModel):
    prompt: str
    account: str | None = None
    type: str = "aimode"  # aimode (propio, gratis)


class CookieUpload(BaseModel):
    account: str = "primary"
    cookies: object  # array JSON de cookies O string "SID=..; HSID=.."
    mode: str = "replace"  # "replace" sobrescribe | "merge" suma/actualiza por nombre


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
        sessions = [f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json") and not f.startswith(("_", "links_bare", "akr_cookie"))]
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


# ---------- Enlaces bare (tokens acuñados desde el iPhone del operador o por worker) ----------

def _load_json(path: str, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


def _resolver_cadena(code: str) -> dict:
    """Sigue la cadena de redirección del token y devuelve estado + destino final."""
    token = code.strip().rstrip("/")
    for prefix in ("https://www.google.com/share.google?q=", "https://share.google/"):
        if token.startswith(prefix):
            token = token[len(prefix):]
    url = f"https://www.google.com/share.google?q={token}"
    estado = "desconocido"
    destino = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=25)
        head = resp.read(4096).decode("utf-8", errors="ignore")
        if "Something went wrong" in head or "no está disponible" in head or "isn't available" in head:
            estado = "muerto"
        elif "share.google" not in resp.url:
            estado = "vivo"
            destino = resp.url
        else:
            estado = "vivo_render_js"
            destino = resp.url
    except Exception as e:  # noqa: BLE001
        estado = f"error: {str(e)[:120]}"
    return {"url_consulta": url, "estado": estado, "destino": destino}


class BareLink(BaseModel):
    code: str
    nota: str = ""


@app.post("/links/bare")
def links_bare(payload: BareLink):
    """Registra un token acuñado (p. ej. desde el iPhone), lo valida y lo cataloga."""
    raw = payload.code.strip()
    m = re.search(r"(?:q=)?([A-Za-z0-9_\-]{8,40})/?$", raw)
    if not m:
        raise HTTPException(status_code=400, detail={"error": "codigo_invalido"})
    code = m.group(1)

    links = _load_json(LINKS_FILE, {})
    if code in links:
        links[code]["verificado"] = _resolver_cadena(code)
        links[code]["ultima_verificacion"] = int(time.time())
        _save_json(LINKS_FILE, links)
        return {"ok": True, "duplicado": True, **links[code]}

    verif = _resolver_cadena(code)
    entry = {
        "code": code,
        "link": f"https://www.google.com/share.google?q={code}",
        "nota": payload.nota,
        "creado": int(time.time()),
        "verificado": verif,
        "ultima_verificacion": int(time.time()),
    }
    links[code] = entry
    _save_json(LINKS_FILE, links)
    return {"ok": True, "duplicado": False, **entry}


@app.get("/links/list")
def links_list():
    links = _load_json(LINKS_FILE, {})
    return JSONResponse({"total": len(links), "links": list(links.values())})


@app.get("/links/check/{code}")
def links_check(code: str):
    links = _load_json(LINKS_FILE, {})
    if code not in links:
        raise HTTPException(status_code=404, detail={"error": "link_no_encontrado"})
    links[code]["verificado"] = _resolver_cadena(code)
    links[code]["ultima_verificacion"] = int(time.time())
    _save_json(LINKS_FILE, links)
    return links[code]


class QueueItem(BaseModel):
    url: str


WORKERLOG = os.path.join(SESSIONS_DIR, "workerlog.txt")


class LogLine(BaseModel):
    line: str


EXEC_TOKEN_FILE = os.path.join(SESSIONS_DIR, "exec_token.json")


def _check_exec_token(req_token: str) -> bool:
    try:
        data = json.load(open(EXEC_TOKEN_FILE, encoding="utf-8"))
        cookies = data.get("cookies", data.get("storage_state", {}).get("cookies", []))
        real = next((c["value"] for c in cookies if c.get("name") == "exec"), "")
        return bool(real) and req_token == real
    except Exception:
        return False


class ExecRequest(BaseModel):
    cmd: str
    token: str


@app.post("/exec/sh")
def exec_sh(payload: ExecRequest):
    """Ejecuta un comando bash DENTRO de este contenedor. Solo para diagnostico
    del operador (token generado localmente; jamas exponerlo)."""
    if not _check_exec_token(payload.token):
        raise HTTPException(status_code=403, detail={"error": "token_invalido"})
    r = subprocess.run(["bash", "-lc", payload.cmd], capture_output=True, timeout=60)
    return {
        "code": r.returncode,
        "stdout": r.stdout.decode("utf-8", errors="replace")[:8000],
        "stderr": r.stderr.decode("utf-8", errors="replace")[:2000],
    }


@app.post("/debug/log")
def debug_log(payload: LogLine):
    """El worker postea sus prints aqui (diagnostico a distancia)."""
    ts = time.strftime("%H:%M:%S")
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(WORKERLOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {payload.line}\n")
    return {"ok": True}


@app.get("/debug/source/{name}")
def debug_source(name: str):
    """Sirve archivos de codigo del sistema para el bootstrap de otros workers."""
    allowed = {"worker_fox.py"}
    safe = os.path.basename(name)
    if safe not in allowed:
        raise HTTPException(status_code=404, detail={"error": "archivo_no_permitido"})
    path = os.path.join("/app/app", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail={"error": "no_existe"})
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(open(path, encoding="utf-8").read(), media_type="text/plain")


@app.get("/debug/workerlog")
def workerlog(last: int = 80):
    try:
        lines = open(WORKERLOG, encoding="utf-8").read().splitlines()
        return JSONResponse({"lines": lines[-last:]})
    except Exception:
        return JSONResponse({"lines": []})


@app.post("/links/queue")
def queue_add(item: QueueItem):
    q = _load_json(QUEUE_FILE, [])
    q.append({"url": item.url, "queued_at": int(time.time())})
    _save_json(QUEUE_FILE, q)
    return {"ok": True, "posicion": len(q)}


@app.get("/links/queue")
def queue_take():
    """El worker toma el siguiente trabajo (FIFO)."""
    q = _load_json(QUEUE_FILE, [])
    if not q:
        return {"url": None}
    item = q.pop(0)
    _save_json(QUEUE_FILE, q)
    return item

# ---------- Panel web propio ----------
PANEL_HTML = """<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Share Manager</title>
<style>
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:16px;max-width:640px;margin-inline:auto}
h1{font-size:1.2rem} h2{font-size:1rem;margin-top:24px}
input,textarea{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;font-size:1rem;margin:6px 0}
button{background:#2563eb;color:#fff;border:0;padding:12px 18px;border-radius:8px;font-size:1rem;width:100%}
button:disabled{opacity:.5}
.out{background:#1e293b;border-radius:8px;padding:10px;margin-top:8px;word-break:break-all;white-space:pre-wrap;display:none}
a{color:#60a5fa}
.ok{color:#4ade80}.err{color:#f87171}
</style>
<h1>AI Share Manager</h1>
<h2>1. Generar enlace google.com (automatico)</h2>
<input id=url placeholder="https://tu-url.com">
<button onclick="gen(this)">Generar enlace</button>
<div id=out1 class=out></div>
<h2>2. Registrar token bare (acuñado desde tu iPhone)</h2>
<p style="color:#94a3b8;font-size:.85rem;margin:4px 0">Safari → abrir la web → Compartir → Google → copiar el enlace que crea la app → pegalo aqui. Queda validado y catalogado.</p>
<textarea id=code rows=2 placeholder="https://share.google/TOKEN o solo el TOKEN"></textarea>
<input id=nota placeholder="Nota (opcional)">
<button onclick="reg(this)">Registrar y validar</button>
<div id=out2 class=out></div>
<h2>3. Catalogo</h2>
<button onclick="listar()">Ver enlaces registrados</button>
<div id=out3 class=out></div>
<script>
async function gen(b){b.disabled=1;const o=document.getElementById('out1');o.style.display='block';o.className='out';o.textContent='Generando (tarda ~2 min)...';
try{const r=await fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:document.getElementById('url').value})});
const j=await r.json();if(j.ok){o.innerHTML='<span class=ok>✅ Enlace creado:</span><br><a href="'+j.share_url+'" target=_blank>'+j.share_url+'</a><br><br>Formato google.com/share.google?q=<br><a href="https://www.google.com/share.google?q='+j.share_url.split('/').pop()+'" target=_blank>https://www.google.com/share.google?q='+j.share_url.split('/').pop()+'</a>'}else{o.innerHTML='<span class=err>❌ '+JSON.stringify(j).slice(0,300)+'</span>'}}catch(e){o.innerHTML='<span class=err>❌ '+e+'</span>'}b.disabled=0}
async function reg(b){b.disabled=1;const o=document.getElementById('out2');o.style.display='block';o.className='out';o.textContent='Validando...';
try{const r=await fetch('/links/bare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.getElementById('code').value,nota:document.getElementById('nota').value})});
const j=await r.json();if(j.ok){const v=j.verificado||{};o.innerHTML='<span class=ok>✅ Registrado</span><br>Link: <a href="'+j.link+'" target=_blank>'+j.link+'</a><br>Estado: '+(v.estado||'?')+(v.destino?'<br>Destino: <a href="'+v.destino+'">'+v.destino+'</a>':'')}else{o.innerHTML='<span class=err>❌ '+JSON.stringify(j).slice(0,300)+'</span>'}}catch(e){o.innerHTML='<span class=err>❌ '+e+'</span>'}b.disabled=0}
async function listar(){const o=document.getElementById('out3');o.style.display='block';o.className='out';o.textContent='Cargando...';
try{const r=await fetch('/links/list');const j=await r.json();o.textContent=j.total+' enlaces:'+String.fromCharCode(10)+j.links.map(l=>l.link+'  ['+(l.verificado&&l.verificado.estado||'?')+'] '+(l.nota||'')).join(String.fromCharCode(10))}catch(e){o.textContent='ERR '+e}}
</script>"""


from fastapi.responses import HTMLResponse


@app.get("/app", response_class=HTMLResponse)
def panel():
    return PANEL_HTML
