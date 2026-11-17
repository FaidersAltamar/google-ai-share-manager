"""Proveedor AKRShortener para tokens BARE (proxy-render directo del destino).

Usa la sesion web (cookie gshort.sid) del dashboard AKR para crear google links
con el backend ClientLink de AKR. La cookie se renueva via POST /akr-session/upload
cuando expire.
"""
import json
import os
import re
import time

import requests

AKR_BASE = "https://akrshortener.com"
AKR_COOKIE_FILE = os.environ.get("AKR_COOKIE_FILE", "/app/sessions/akr_cookie.txt")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)


def _cookie() -> str:
    if not os.path.exists(AKR_COOKIE_FILE):
        raise RuntimeError("no_akr_session")
    return open(AKR_COOKIE_FILE, encoding="utf-8").read().strip()


def _csrf(session: requests.Session) -> str:
    r = session.get(f"{AKR_BASE}/links", timeout=25)
    m = re.search(r'name="_csrf" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("csrf_no_encontrado")
    return m.group(1)


def crear_bare_link(destination_url: str, timeout_s: int = 90) -> dict:
    """Crea un google link BARE en AKR para la URL destino y devuelve el token."""
    t0 = time.time()
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.headers["Cookie"] = _cookie()

    csrf = _csrf(s)
    r = s.post(
        f"{AKR_BASE}/links",
        data={"_csrf": csrf, "linkType": "google", "destinationUrl": destination_url},
        headers={"Origin": AKR_BASE, "Referer": f"{AKR_BASE}/links"},
        timeout=timeout_s,
        allow_redirects=True,
    )
    state = re.search(r'akr-links-state">(.*?)</script>', r.text, re.S)
    link_id = re.search(r'new-google-link-id="([^"]+)"', r.text)

    if not (state and link_id):
        if "auth/login" in r.url or "Log in" in r.text:
            raise RuntimeError("akr_sesion_expirada")
        raise RuntimeError(f"akr_creacion_fallida (HTTP {r.status_code})")

    data = json.loads(state.group(1))
    info = data.get(link_id.group(1), {})
    url = info.get("url") or ""
    status = info.get("status")

    # si aun no esta ready, hacer polling del endpoint de estado
    waited = 0
    while status != "ready" and waited < 60:
        time.sleep(2)
        waited += 2
        sr = s.get(
            f"{AKR_BASE}/links/google-share/status?ids={link_id.group(1)}&_={int(time.time() * 1000)}",
            headers={"Accept": "application/json"},
            timeout=20,
        )
        items = sr.json().get("links", [])
        if items:
            url = items[0].get("googleShareUrl") or url
            status = items[0].get("googleShareStatus") or status
            if items[0].get("googleShareError"):
                raise RuntimeError(f"akr_error: {items[0]['googleShareError']}")

    if status != "ready" or "share.google" not in url:
        raise RuntimeError(f"akr_no_ready (estado: {status})")

    token = url.split("share.google/", 1)[-1]
    return {
        "ok": True,
        "share_url": f"https://www.google.com/share.google?q={token}",
        "raw_share_url": url,
        "token": token,
        "destination": destination_url,
        "provider": "akr",
        "elapsed_s": round(time.time() - t0, 1),
    }
