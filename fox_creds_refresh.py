"""Extrae credenciales ADB/SSH del telefono FoxPhone y las sube al API.

Corre desde el PC del operador (red residencial, sin captcha) -> el worker en el
VPS nunca toca el console de FoxPhone (su IP de datacenter dispara el captcha).

Uso:
    python fox_creds_refresh.py            # extrae + sube al API
    python fox_creds_refresh.py --local    # solo extrae a debug_fox/ssh_creds.json

Salida: debug_fox/ssh_creds.json  {user, host, port, lport, rhost, rport, pass}
"""
import sys, os, re, json, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
DBG = os.path.join(BASE, "debug_fox")
STATE = os.path.join(DBG, "fox_session.json")
OUT_JSON = os.path.join(DBG, "ssh_creds.json")
EMAIL = "faiders@scale.com.co"
PASSWORD = "@jMbk8BJ#xh.SWn"
API = os.environ.get("VPS_API", "http://179.66.140.79:8000")


def login(page):
    """Devuelve True si la tabla de telefonos es visible."""
    email_f = page.locator("input[placeholder='Please enter your email']").first
    try:
        email_f.wait_for(state="visible", timeout=6000)
    except Exception:
        pass  # sesion viva, sin formulario
    else:
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
            print(f"  intento {attempt+1}: no aparecio la fila, refresh...")
            page.reload(timeout=60000)
            page.wait_for_timeout(8000)
            login(page)
            return True
    return False


def parse_ssh(text):
    """El modal trae: ssh -oXXX user@host -p PORT -L LPORT:RHOST:RPORT ... Password: ... """
    text = text.replace("\r", "")
    # comando ssh completo
    m = re.search(
        r"ssh\s+-o\S+\s+(\S+)@(\S+)\s+-p\s+(\d+)\s+-L\s+(\d+):([^:\s]+):(\d+)",
        text)
    if not m:
        # variantes: -p antes de -L, o conStrictHostKeyChecking y mas flags
        m = re.search(
            r"ssh[^\n]*?\s(\S+)@([^\s]+)\s+[^\n]*?-p\s+(\d+)[^\n]*?-L\s+(\d+):([^:\s]+):(\d+)",
            text)
    if not m:
        return None
    user, host, port, lport, rhost, rport = m.groups()
    # password: en el modal suele venir como "Password:\n<valor>" o "Password: <valor>"
    pw = re.search(r"Password:\s*\n?\s*([^\s\n]+)", text)
    if not pw:
        return None
    return {
        "user": user, "host": host, "port": int(port),
        "lport": int(lport), "rhost": rhost, "rport": int(rport),
        "pass": pw.group(1).strip(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="no subir al API")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}, locale="en-US",
            storage_state=STATE if os.path.exists(STATE) else None,
        )
        page = ctx.new_page()
        page.goto("https://console.foxphone.com/", timeout=60000)
        page.wait_for_timeout(7000)

        if not login(page):
            print("FALLO: telefono no visible en la tabla")
            page.screenshot(path=os.path.join(DBG, "fail_table.png"))
            browser.close()
            sys.exit(1)

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
            print("FALLO: no se pudo abrir 'ADB Info'")
            page.screenshot(path=os.path.join(DBG, "fail_adb.png"))
            browser.close()
            sys.exit(1)

        page.wait_for_timeout(5000)
        page.screenshot(path=os.path.join(DBG, "s2_adb_modal.png"))

        chunks = []
        dialogs = page.locator(".t-dialog, [role=dialog], .t-popup__content")
        for i in range(min(dialogs.count(), 5)):
            try:
                t = dialogs.nth(i).inner_text()
                if t.strip():
                    chunks.append(t)
            except Exception:
                pass
        if not chunks:
            chunks.append(page.inner_text("body"))
        full = "\n".join(chunks)

        ctx.storage_state(path=STATE)
        browser.close()

    with open(os.path.join(DBG, "ssh_info.txt"), "w", encoding="utf-8") as f:
        f.write(full)

    creds = parse_ssh(full)
    if not creds:
        print("FALLO: no se pudo parsear el comando ssh del modal")
        print(full[:1500])
        sys.exit(2)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=1)
    print("CREDENCIALES OK:", {k: (v[:10] + "..." if k == "pass" else v) for k, v in creds.items()})

    if args.local:
        print("(solo local, no subido)")
        return

    import urllib.request
    payload = dict(creds)
    payload["pass_"] = payload.pop("pass")
    req = urllib.request.Request(
        API + "/adb-creds", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("SUBIDO AL API:", r.read().decode()[:200])


if __name__ == "__main__":
    main()
