"""Abre Chrome visible para que inicies sesión en Google UNA sola vez.
Cuando detecta que la sesión quedó activa, guarda app/sessions/primary.json."""
import json
import os
import time

from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "sessions", "primary.json")


def tiene_sesion(cookies) -> bool:
    nombres = {c["name"] for c in cookies}
    return "SAPISID" in nombres or "__Secure-1PAPISID" in nombres


def main():
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto("https://accounts.google.com/ServiceLogin?continue=https://www.google.com")

        print("=" * 60)
        print("VENTANA DE CHROME ABIERTA")
        print("1. Inicia sesión con tu cuenta de Google (con tu 2FA)")
        print("2. Cuando termines, NO cierres la ventana")
        print("3. Este script detectará la sesión sola y guardará el archivo")
        print("   (esperando hasta 10 minutos...)")
        print("=" * 60)

        guardado = False
        for _ in range(600):  # 10 min máx
            time.sleep(1)
            cookies = context.cookies()
            if tiene_sesion(cookies):
                context.storage_state(path=SESSION_FILE)
                guardado = True
                print(f"\n✅ Sesión detectada y guardada en: {SESSION_FILE}")
                print("   Ya puedes cerrar la ventana de Chrome.")
                break

        if not guardado:
            print("\n❌ No se detectó sesión después de 10 minutos. Saliendo sin guardar.")

        time.sleep(2)
        browser.close()

    if guardado:
        state = json.load(open(SESSION_FILE, encoding="utf-8"))
        print(f"   Cookies guardadas: {len(state.get('cookies', []))}")


if __name__ == "__main__":
    main()
