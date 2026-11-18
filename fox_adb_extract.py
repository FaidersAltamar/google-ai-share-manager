"""Login console FoxPhone + extraer credenciales ADB del telefono.
Uso: python fox_adb_extract.py
Guarda: debug_fox/ssh_info.txt con el comando SSH + key si esta disponible."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
DBG = os.path.join(BASE, "debug_fox")
EMAIL = "faiders@scale.com.co"
PASS = "@jMbk8BJ#xh.SWn"
STATE = os.path.join(DBG, "fox_session.json")

def shot(page, name):
    page.screenshot(path=os.path.join(DBG, name), full_page=False)

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

    # login solo si el formulario es REALMENTE visible
    email_f = page.locator("input[placeholder='Please enter your email']").first
    need_login = False
    try:
        email_f.wait_for(state="visible", timeout=5000)
        need_login = True
    except Exception:
        need_login = False

    if need_login:
        print("[1] login...")
        email_f.fill(EMAIL)
        page.locator("input[placeholder='Please enter your Password']").first.fill(PASS)
        for sel in ("button:has-text('Log In')", "button:has-text('Login')"):
            b = page.locator(sel)
            if b.count() > 0:
                b.first.click(); break
        page.wait_for_timeout(9000)
        shot(page, "s1_login.png")
    else:
        print("[1] sesion viva - sin login")

    # esperar fila del telefono (hasta 60s, con refresh si hace falta)
    print("[2] esperando fila Galaxy...")
    ok = False
    for attempt in range(3):
        try:
            page.wait_for_selector("text=Galaxy S21", timeout=20000)
            ok = True
            break
        except Exception:
            print(f"  intento {attempt+1}: no aparecio, refresh...")
            page.reload(timeout=60000)
            page.wait_for_timeout(8000)
            ef = page.locator("input[placeholder='Please enter your email']").first
            try:
                ef.wait_for(state="visible", timeout=4000)
                ef.fill(EMAIL)
                page.locator("input[placeholder='Please enter your Password']").first.fill(PASS)
                for sel in ("button:has-text('Log In')", "button:has-text('Login')"):
                    b = page.locator(sel)
                    if b.count() > 0:
                        b.first.click(); break
                page.wait_for_timeout(9000)
            except Exception:
                pass
    if not ok:
        print("FALLO: telefono no visible"); shot(page, "fail_table.png"); sys.exit(1)
    print("[3] fila visible - abriendo menu '...'")

    row = page.locator("tr", has_text="Galaxy S21").first
    more_btn = row.locator("button").last
    more_btn.wait_for(timeout=30000)
    more_btn.click()
    page.wait_for_timeout(2500)

    # click ADB Info (solo el match VISIBLE, el DOM guarda copias ocultas)
    print("[4] click ADB Info...")
    matches = page.get_by_text("ADB Info")
    clicked = False
    for i in range(matches.count()):
        el = matches.nth(i)
        try:
            if el.is_visible():
                el.click()
                clicked = True
                print(f"  clicked match visible #{i}")
                break
        except Exception:
            continue
    if not clicked:
        # fallback: click por coordenadas del menu abierto
        print("  fallback: buscando en popups visibles")
        pops = page.locator(".t-popup__content:visible")
        for i in range(pops.count()):
            el = pops.nth(i).get_by_text("ADB Info").first
            try:
                if el.is_visible():
                    el.click(); clicked = True; break
            except Exception:
                continue
    page.wait_for_timeout(5000)
    shot(page, "s2_adb_modal.png")

    # capturar TODO el texto de modales visibles
    out = []
    dialogs = page.locator(".t-dialog, [role=dialog], .t-popup__content")
    for i in range(min(dialogs.count(), 5)):
        try:
            t = dialogs.nth(i).inner_text()
            if t.strip():
                out.append(t)
        except Exception:
            pass
    body = page.inner_text("body")
    # extraer seccion relevante (ssh/ip/puerto/key)
    full = "\n\n=== DIALOG ===\n".join(out)
    print("=== CONTENIDO MODALES ===")
    print(full[:2500])
    with open(os.path.join(DBG, "ssh_info.txt"), "w", encoding="utf-8") as f:
        f.write(full)
    ctx.storage_state(path=STATE)
    print("[5] guardado debug_fox/ssh_info.txt y sesion actualizada")
    browser.close()
