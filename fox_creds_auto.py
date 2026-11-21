"""Refresco autonomo de credenciales ADB/SSH del FoxPhone.

Corre DENTRO del contenedor (imagen Playwright) en bucle. Re-login en
console.foxphone.com, extrae el comando ssh del modal ADB Info y lo sube
al API con X-API-Key.

Uso:
    python fox_creds_auto.py --once      # una pasada
    python fox_creds_auto.py --loop      # bucle (FOX_INTERVAL seg, def 6h)

Env:
    FOX_API       base del API (def http://ai-share-manager:8000)
    API_KEY       X-API-Key del API (obligatorio para subir)
    FOX_EMAIL / FOX_PASSWORD
    FOX_INTERVAL  segundos entre refrescos (def 21600)
    FOX_SESSIONS  carpeta persistente (def /app/sessions)
"""
import sys, os, re, json, time, argparse, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

SESSIONS = os.environ.get("FOX_SESSIONS", "/app/sessions")
STATE = os.path.join(SESSIONS, "fox_session.json")
OUT_JSON = os.path.join(SESSIONS, "ssh_creds.json")
API = os.environ.get("FOX_API", "http://ai-share-manager:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "").strip()
EMAIL = os.environ.get("FOX_EMAIL", "faiders@scale.com.co")
PASSWORD = os.environ.get("FOX_PASSWORD", "@jMbk8BJ#xh.SWn")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def login(page):
    email_f = page.locator("input[placeholder='Please enter your email']").first
    try:
        email_f.wait_for(state="visible", timeout=6000)
    except Exception:
        pass
    else:
        log("formulario de login presente -> autenticando")
        email_f.fill(EMAIL)
        page.locator("input[placeholder='Please enter your Password']").first.fill(PASSWORD)
        for sel in ("button:has-text('Log In')", "button:has-text('Login')"):
            b = page.locator(sel)
            if b.count() > 0:
                b.first.click()
                break
        page.wait_for_timeout(9000)

    for attempt in range(3):
        try:
            page.wait_for_selector("text=Galaxy S21", timeout=20000)
            return True
        except Exception:
            log(f"  intento {attempt+1}: fila no visible, reload")
            page.reload(timeout=60000)
            page.wait_for_timeout(8000)
            login(page)
            return True
    return False


def parse_ssh(text):
    text = text.replace("\r", "")
    m = re.search(r"ssh\s+-o\S+\s+(\S+)@(\S+)\s+-p\s+(\d+)\s+-L\s+(\d+):([^:\s]+):(\d+)", text)
    if not m:
        m = re.search(r"ssh[^\n]*?\s(\S+)@([^\s]+)\s+[^\n]*?-p\s+(\d+)[^\n]*?-L\s+(\d+):([^:\s]+):(\d+)", text)
    if not m:
        return None
    user, host, port, lport, rhost, rport = m.groups()
    pw = re.search(r"Password:\s*\n?\s*([^\s\n]+)", text)
    if not pw:
        return None
    return {
        "user": user, "host": host, "port": int(port),
        "lport": int(lport), "rhost": rhost, "rport": int(rport),
        "pass": pw.group(1).strip(),
    }


def upload(creds):
    if not API_KEY:
        log("sin API_KEY: no se sube")
        return False
    payload = dict(creds)
    payload["pass_"] = payload.pop("pass")
    req = urllib.request.Request(
        API + "/adb-creds", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        log("subido al API: " + r.read().decode()[:120])
    return True


def refresh():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900}, locale="en-US",
                storage_state=STATE if os.path.exists(STATE) else None,
            )
            page = ctx.new_page()
            page.goto("https://console.foxphone.com/", timeout=60000)
            page.wait_for_timeout(7000)

            if not login(page):
                log("FALLO: telefono no visible (posible captcha)")
                return None

            row = page.locator("tr", has_text="Galaxy S21").first
            row.locator("button").last.click(timeout=30000)
            page.wait_for_timeout(2500)

            clicked = False
            for i in range(page.get_by_text("ADB Info").count()):
                el = page.get_by_text("ADB Info").nth(i)
                try:
                    if el.is_visible():
                        el.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                log("FALLO: no se abrio 'ADB Info'")
                return None

            page.wait_for_timeout(5000)
            chunks = []
            for i in range(min(page.locator(".t-dialog, [role=dialog], .t-popup__content").count(), 5)):
                try:
                    t = page.locator(".t-dialog, [role=dialog], .t-popup__content").nth(i).inner_text()
                    if t.strip():
                        chunks.append(t)
                except Exception:
                    pass
            full = "\n".join(chunks) or page.inner_text("body")
            try:
                ctx.storage_state(path=STATE)
            except Exception:
                pass
        finally:
            browser.close()

    creds = parse_ssh(full)
    if not creds:
        log("FALLO: no se pudo parsear el comando ssh")
        return None
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=1)
    log("CREDENCIALES OK: " + json.dumps({k: (v[:8] + "..." if k == "pass" else v) for k, v in creds.items()}))
    upload(creds)
    return creds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    interval = int(os.environ.get("FOX_INTERVAL", "21600"))

    if args.once or not args.loop:
        refresh()
        return

    log(f"bucle de refresco activo (cada {interval}s)")
    while True:
        try:
            refresh()
        except Exception as e:
            log(f"error en refresco: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
