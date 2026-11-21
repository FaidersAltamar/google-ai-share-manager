"""AI Share Manager — Google Share Generator (standalone).

Unica cadena: Galaxy S21 FoxPhone (acuñador) -> worker ADB -> tokens bare
google.com/share.google?q=CODE -> validacion -> catalogo.
Sin dependencias externas.

Endpoints:
- GET  /health                 estado (público)
- POST /links/bare             registrar token acuñado (valida cadena + cataloga)
- GET  /links/list             catalogo
- GET  /links/check/{code}     reverificar un token
- POST /links/queue            encolar URL para el worker
- GET  /links/queue            worker toma la siguiente
- GET  /adb-creds              worker consulta sus credenciales SSH
- POST /adb-creds              operador sube credenciales SSH extraidas localmente
- POST /debug/log              worker reporta logs
- GET  /debug/workerlog        log del worker
- GET  /debug/source/{name}    sirve worker_fox.py para bootstrap
- POST /exec/sh                diagnostico remoto (token)

Auth: X-API-Key header required on all endpoints except /health.
"""
import json
import os
import re
import subprocess
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

SESSIONS_DIR = "/app/sessions"
LINKS_FILE = os.path.join(SESSIONS_DIR, "links_bare.json")
QUEUE_FILE = os.path.join(SESSIONS_DIR, "queue.json")
WORKERLOG = os.path.join(SESSIONS_DIR, "workerlog.txt")
# las creds SSH viven en el volumen persistente (/app/sessions) para no perderlas
# en cada recreate del contenedor
SSH_CREDS_FILE = os.path.join(SESSIONS_DIR, "ssh_creds.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"

# API Key configuration
API_KEY = os.environ.get("API_KEY", "").strip()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)):
    """Dependency to verify X-API-Key header. Skip if API_KEY not configured."""
    if not API_KEY:
        return  # Auth disabled if no API_KEY set (dev mode only)
    if not api_key or api_key != API_KEY:
        raise HTTPException(status_code=401, detail={"error": "invalid_api_key"})


app = FastAPI(title="Google Share Generator API", version="2.2")


def _load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def _resolver_cadena(code: str) -> dict:
    """Sigue la cadena del token y devuelve estado + destino final."""
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
    except Exception as e:
        estado = f"error: {str(e)[:120]}"
    return {"url_consulta": url, "estado": estado, "destino": destino}


# ---------- health (público, SIN auth) ----------

@app.get("/health", dependencies=[])
def health():
    return {"status": "ok", "message": "Google Share Generator operativo"}


# ---------- enlaces bare (requieren auth) ----------

class BareLink(BaseModel):
    code: str
    nota: str = ""


@app.post("/links/bare", dependencies=[Depends(verify_api_key)])
def links_bare(payload: BareLink):
    """Registra un token acuñado, lo valida y lo cataloga."""
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


@app.get("/links/list", dependencies=[Depends(verify_api_key)])
def links_list():
    links = _load_json(LINKS_FILE, {})
    return JSONResponse({"total": len(links), "links": list(links.values())})


@app.get("/links/check/{code}", dependencies=[Depends(verify_api_key)])
def links_check(code: str):
    links = _load_json(LINKS_FILE, {})
    if code not in links:
        raise HTTPException(status_code=404, detail={"error": "link_no_encontrado"})
    links[code]["verificado"] = _resolver_cadena(code)
    links[code]["ultima_verificacion"] = int(time.time())
    _save_json(LINKS_FILE, links)
    return links[code]


# ---------- cola del worker (requieren auth) ----------

class QueueItem(BaseModel):
    url: str


@app.post("/links/queue", dependencies=[Depends(verify_api_key)])
def queue_add(item: QueueItem):
    q = _load_json(QUEUE_FILE, [])
    q.append({"url": item.url, "queued_at": int(time.time())})
    _save_json(QUEUE_FILE, q)
    return {"ok": True, "posicion": len(q)}


@app.get("/links/queue", dependencies=[Depends(verify_api_key)])
def queue_take(peek: bool = False):
    """El worker toma la siguiente trabajo (FIFO). Con peek=true NO la saca:
    sirve para inspeccionar la cola sin robarle el job al worker."""
    q = _load_json(QUEUE_FILE, [])
    if not q:
        return {"url": None}
    if peek:
        return {"url": q[0]["url"], "posicion": 1, "total": len(q), "peek": True}
    item = q.pop(0)
    _save_json(QUEUE_FILE, q)
    return item


# ---------- credenciales SSH ADB (requieren auth) ----------

class AdbCreds(BaseModel):
    user: str
    host: str
    port: int
    lport: int
    rhost: str
    rport: int
    pass_: str


@app.post("/adb-creds", dependencies=[Depends(verify_api_key)])
def adb_creds_upload(creds: AdbCreds):
    """Sube las credenciales SSH ADB extraidas localmente (sin captcha)."""
    data = {"user": creds.user, "host": creds.host, "port": creds.port,
            "lport": creds.lport, "rhost": creds.rhost, "rport": creds.rport,
            "pass": creds.pass_}
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(SSH_CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return {"ok": True, "file": SSH_CREDS_FILE, "cred": {k: (v[:12] + "..." if k == "pass" else v) for k, v in data.items()}}


@app.get("/adb-creds", dependencies=[Depends(verify_api_key)])
def adb_creds_get():
    """El worker consulta aqui sus credenciales SSH."""
    try:
        data = json.load(open(SSH_CREDS_FILE, encoding="utf-8"))
        return data
    except Exception:
        raise HTTPException(status_code=404, detail={"error": "no_creds"})


# ---------- diagnostico (requieren auth) ----------

class LogLine(BaseModel):
    line: str


@app.post("/debug/log", dependencies=[Depends(verify_api_key)])
def debug_log(payload: LogLine):
    """El worker postea sus prints aqui (diagnostico a distancia)."""
    ts = time.strftime("%H:%M:%S")
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(WORKERLOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {payload.line}\n")
    return {"ok": True}


@app.get("/debug/workerlog", dependencies=[Depends(verify_api_key)])
def workerlog(last: int = 80):
    try:
        lines = open(WORKERLOG, encoding="utf-8").read().splitlines()
        return JSONResponse({"lines": lines[-last:]})
    except Exception:
        return JSONResponse({"lines": []})


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


@app.post("/exec/sh", dependencies=[Depends(verify_api_key)])
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


PANEL_HTML = """<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Google Share Generator</title>
<style>
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:16px;max-width:640px;margin-inline:auto}
h1{font-size:1.2rem} h2{font-size:1rem;margin-top:24px}
textarea,input{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;font-size:1rem;margin:6px 0}
button{background:#2563eb;color:#fff;border:0;padding:12px 18px;border-radius:8px;font-size:1rem;width:100%;margin:6px 0}
.out{background:#1e293b;border-radius:8px;padding:10px;margin-top:8px;word-break:break-all;white-space:pre-wrap;display:none}
.ok{color:#4ade80}.err{color:#f87171}
small{color:#94a3b8}
</style>
<h1>Google Share Generator</h1>
<h2>1. Registrar token bare acu&ntilde;ado</h2>
<small>Pega el enlace share.google/... o el codigo que acuno el telefono.</small>
<textarea id=code rows=2 placeholder="https://share.google/TOKEN"></textarea>
<input id=nota placeholder="Nota (opcional)">
<button onclick="reg(this)">Registrar y validar</button>
<div id=out1 class=out></div>
<h2>2. Estado</h2>
<button onclick="estado()">Ver sistema</button>
<div id=out2 class=out></div>
<h2>3. Credenciales SSH del tel&eacute;fono (JSON)</h2>
<small>Pega el contenido de ssh_creds.json (extraido localmente por fox_adb_extract.py). El worker lo consulta para el t&uacute;nel ADB.</small>
<textarea id=creds rows=4 placeholder={"user":"...","host":"adb.foxphone.com","port":1824,"lport":9536,"rhost":"foxphone","rport":100,"pass":"..."}></textarea>
<button onclick="subircreds(this)">Subir credenciales al worker</button>
<div id=outc class=out></div>
<h2>4. Catalogo</h2>
<button onclick="listar()">Ver enlaces</button>
<div id=out3 class=out></div>
<script>
async function reg(b){b.disabled=1;const o=document.getElementById('out1');o.style.display='block';o.className='out';o.textContent='Validando cadena...';
try{const r=await fetch('/links/bare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.getElementById('code').value,nota:document.getElementById('nota').value})});
const j=await r.json();if(j.ok){const st=j.verificado||{};o.innerHTML='<span class=ok>&#9989; Registrado:</span><br><a href="https://www.google.com/share.google?q='+j.code+'" target=_blank>https://www.google.com/share.google?q='+j.code+'</a><br><br>Estado: '+JSON.stringify(st).slice(0,200)}else{o.innerHTML='<span class=err>&#10060; '+JSON.stringify(j).slice(0,300)+'</span>'}}catch(e){o.innerHTML='<span class=err>&#10060; '+e+'</span>'}b.disabled=0}
async function estado(){const o=document.getElementById('out2');o.style.display='block';try{const r=await fetch('/adb-creds');const j=await r.json();o.textContent='SSH creds: '+JSON.stringify(j).slice(0,250)}catch(e){o.textContent=e}}
async function subircreds(b){b.disabled=1;const o=document.getElementById('outc');o.style.display='block';o.className='out';o.textContent='Subiendo credenciales...';
try{const creds=JSON.parse(document.getElementById('creds').value);const r=await fetch('/adb-creds',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(creds)});const j=await r.json();if(j.ok){o.innerHTML='<span class=ok>✅ Credenciales subidas al worker. El proximo ciclo de acuñacion las usara.</span>'}else{o.innerHTML='<span class=err>❌ '+JSON.stringify(j).slice(0,300)+'</span>'}}catch(e){o.innerHTML='<span class=err>❌ '+e+'</span>'}b.disabled=0}
async function listar(){const o=document.getElementById('out3');o.style.display='block';try{const r=await fetch('/links/list');const j=await r.json();o.textContent=JSON.stringify(j,null,1).slice(0,1500)}catch(e){o.textContent=e}}
listar();
</script>"""


@app.get("/debug/source/{name}", dependencies=[Depends(verify_api_key)])
def debug_source(name: str):
    """Sirve archivos de codigo del sistema para el bootstrap de otros workers."""
    allowed = {"worker_fox.py"}
    safe = os.path.basename(name)
    if safe not in allowed:
        raise HTTPException(status_code=404, detail={"error": "archivo_no_permitido"})
    path = os.path.join("/app", safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail={"error": "no_existe"})
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(open(path, encoding="utf-8").read(), media_type="text/plain")