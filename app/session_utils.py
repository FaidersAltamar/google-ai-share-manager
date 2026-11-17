"""Utilidades para convertir cookies de distintas fuentes a storage_state de Playwright."""
import json

DEFAULT_DOMAIN = ".google.com"


def _norm(c: dict) -> dict:
    out = {
        "name": c["name"],
        "value": c["value"],
        "domain": c.get("domain", DEFAULT_DOMAIN),
        "path": c.get("path", "/"),
        "secure": bool(c.get("secure", True)),
        "httpOnly": bool(c.get("httpOnly", False)),
    }
    if c.get("expires") not in (None, -1, 0):
        out["expires"] = c["expires"]
    if c.get("sameSite") in ("Strict", "Lax", "None"):
        out["sameSite"] = c["sameSite"]
    return out


def parse_cookies(raw):
    """Acepta dos formatos:
    1) JSON array de cookies (DevTools 'Copy all', extensión EditThisCookie, Playwright)
    2) String estilo header HTTP: 'SID=abc; HSID=def; ...'
    Devuelve lista de cookies normalizadas para Playwright.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("[") or raw.startswith("{"):
            raw = json.loads(raw)
        else:
            cookies = []
            for part in raw.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                name, _, value = part.partition("=")
                cookies.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": DEFAULT_DOMAIN,
                        "path": "/",
                        "secure": True,
                        "httpOnly": False,
                    }
                )
            return cookies

    if isinstance(raw, dict):  # un solo objeto cookie
        raw = [raw]
    return [_norm(c) for c in raw]


def build_storage_state(cookies: list) -> dict:
    return {"cookies": cookies, "origins": []}
