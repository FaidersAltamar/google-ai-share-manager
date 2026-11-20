"""AI Share Manager — sistema AKR bare puro.

Unica cadena: Galaxy S21 FoxPhone (acuñador) -> worker ADB -> tokens bare
google.com/share.google?q=CODE -> validacion -> catalogo.

Endpoints:
- GET  /health                 estado
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
"""
import json
import os
import re
import subprocess
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SESSIONS_DIR = "/app/sessions"
LINKS_FILE = os.path.join(SESSIONS_DIR, "links_bare.json")
QUEUE_FILE = os.path.join(SESSIONS_DIR, "queue.json")
WORKERLOG = os.path.join(SESSIONS_DIR, "workerlog.txt")
SSH_CREDS_FILE = os.path.join("/app", "ssh_creds.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"

app = FastAPI(title="AKR Bare System API", version="2.2")


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


# ---------- health ----------

@app.get("/health")
def health():
    return {"status": "ok", "message": "AKR bare system operativo"}


# ---------- enlaces bare ----------

class BareLink(BaseModel):
    code: str
    nota: str = ""


@app.post("/links/bare")
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


# ---------- cola del worker ----------

class QueueItem(BaseModel):
    url: str


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


# ---------- credenciales SSH ADB ----------

class AdbCreds(BaseModel):
    user: str
    host: str
    port: int
    lport: int
    rhost: str
    rport: int
    pass_: str


@app.post("/adb-creds")
def adb_creds_upload(creds: AdbCreds):
    """Sube las credenciales SSH ADB extraidas localmente (sin captcha)."""
    data = {"user": creds.user, "host": creds.host, "port": creds.port,
            "lport": creds.lport, "rhost": creds.rhost, "rport": creds.rport,
            "pass": creds.pass_}
    os.makedirs("/app", exist_ok=True)
    with open(SSH_CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return {"ok": True, "file": SSH_CREDS_FILE, "cred": {k: (v[:12] + "..." if k == "pass" else v) for k, v in data.items()}}


@app.get("/adb-creds")
def adb_creds_get():
    """El worker consulta aqui sus credenciales SSH."""
    try:
        data = json.load(open(SSH_CREDS_FILE, encoding="utf-8"))
        return data
    except Exception:
        raise HTTPException(status_code=404, detail={"error": "no_creds"})


# ---------- diagnostico ----------

class LogLine(BaseModel):
    line: str


@app.post("/debug/log")
def debug_log(payload: LogLine):
    """El worker postea sus prints aqui (diagnostico a distancia)."""
    ts = time.strftime("%H:%M:%S")
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(WORKERLOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {payload.line}\n")
    return {"ok": True}


@app.get("/debug/workerlog")
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
