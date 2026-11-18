"""Worker FoxPhone: acuña tokens bare en el Galaxy S21 cloud y los registra en el API.

Loop: GET /links/queue -> extrae SSH del console (Playwright, cada ciclo o si expira)
      -> tunnel paramiko -> adb flujo (buscar URL -> abrir -> compartir -> copiar -> pegar -> extraer)
      -> POST /links/bare
"""
import sys, os, time, re, json, socket, threading, select, subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API = os.environ.get("VPS_API", "http://ai-share-manager:8000")

def detect_api():
    """Prueba candidatos: gateway de la red, docker0 del host (172.17.0.1).
    El API esta publicado en 0.0.0.0:8000 del host -> reachable desde cualquier red."""
    candidates = []
    env = os.environ.get("VPS_API", "")
    if env:
        candidates.append(env)
    try:
        gw = subprocess.check_output(
            "ip route | awk '/default/ {print $3}'", shell=True).decode().strip()
        if gw:
            candidates.append(f"http://{gw}:8000")
    except Exception:
        pass
    candidates.append("http://172.17.0.1:8000")
    for c in candidates:
        try:
            raw = subprocess.check_output(
                ["curl", "-s", "--max-time", "5", c + "/health"], timeout=15)
            if b"status" in raw:
                return c
        except Exception:
            continue
    return candidates[0] if candidates else "http://172.17.0.1:8000"

API = detect_api()
FP_EMAIL = os.environ.get("FP_EMAIL", "")
FP_PASS = os.environ.get("FP_PASS", "")


def log(msg):
    """Print + reporta al API para diagnostico a distancia."""
    print(msg, flush=True)
    try:
        import urllib.request
        req = urllib.request.Request(
            API + "/debug/log",
            data=json.dumps({"line": str(msg)[:500]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
# fallback: creds.json en /app (evita problemas de # en env-files)
if not FP_EMAIL or not FP_PASS:
    try:
        creds = json.load(open("/app/creds.json", encoding="utf-8"))
        FP_EMAIL = creds.get("email", FP_EMAIL)
        FP_PASS = creds.get("password", FP_PASS)
    except Exception:
        pass
ADB_BIN = os.environ.get("ADB_BIN", "/opt/platform-tools/platform-tools/adb")


def ensure_adb():
    """Descarga platform-tools si el binario no existe (Linux)."""
    if os.path.exists(ADB_BIN):
        return
    import urllib.request, zipfile
    os.makedirs("/opt/platform-tools", exist_ok=True)
    zip_path = "/opt/platform-tools/pt.zip"
    log("descargando platform-tools...")
    urllib.request.urlretrieve(
        "https://dl.google.com/android/repository/platform-tools-latest-linux.zip", zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall("/opt/platform-tools")
    os.chmod(ADB_BIN, 0o755)
    print("platform-tools listos:", os.path.exists(ADB_BIN))

STATE = {"ssh": None, "ssh_at": 0}


def api(method, path, body=None, timeout=30):
    import urllib.request
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body else None
    with urllib.request.urlopen(req, data, timeout=timeout) as r:
        return json.loads(r.read().decode())


def extraer_ssh():
    """Login al console FoxPhone y extrae el comando SSH del modal ADB Info."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}, locale="en-US")
        page = ctx.new_page()
        page.goto("https://console.foxphone.com/", timeout=60000)
        page.wait_for_timeout(7000)
        email_f = page.locator("input[placeholder='Please enter your email']").first
        try:
            email_f.wait_for(state="visible", timeout=5000)
            email_f.fill(FP_EMAIL)
            page.locator("input[placeholder='Please enter your Password']").first.fill(FP_PASS)
            for sel in ("button:has-text('Log In')", "button:has-text('Login')"):
                b = page.locator(sel)
                if b.count() > 0:
                    b.first.click(); break
            page.wait_for_timeout(9000)
        except Exception:
            pass
        try:
            page.wait_for_selector("text=Galaxy S21", timeout=40000)
        except Exception:
            pass
        row = page.locator("tr", has_text="Galaxy S21").first
        row.locator("button").last.click()
        page.wait_for_timeout(2500)
        matches = page.get_by_text("ADB Info")
        clicked = False
        for i in range(matches.count()):
            el = matches.nth(i)
            try:
                if el.is_visible():
                    el.click(); clicked = True; break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError("no_adb_info_visible")
        page.wait_for_timeout(5000)
        dialogs = page.locator(".t-dialog, [role=dialog], .t-popup__content")
        full = ""
        for i in range(min(dialogs.count(), 5)):
            try:
                t = dialogs.nth(i).inner_text()
                if t.strip():
                    full += t + "\n"
            except Exception:
                pass
        browser.close()
    m = re.search(r"ssh -o\S+\s+(\S+)@(\S+)\s+-p\s+(\d+)\s+-L\s+(\d+):([^:\s]+):(\d+)", full)
    pw = re.search(r"Password:\s*\n\s*(\S+)", full)
    if not m or not pw:
        raise RuntimeError(f"no_ssh_en_modal: {full[:200]}")
    return {
        "user": m.group(1), "host": m.group(2), "port": int(m.group(3)),
        "lport": int(m.group(4)), "rhost": m.group(5), "rport": int(m.group(6)),
        "pass": pw.group(1),
    }


def tunnel(ssh):
    import paramiko
    transport = paramiko.Transport((ssh["host"], ssh["port"]))
    transport.connect(username=ssh["user"], password=ssh["pass"])
    server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", ssh["lport"])); server.listen(10)
    def handle(cs):
        try:
            chan = transport.open_channel("direct-tcpip", (ssh["rhost"], ssh["rport"]), cs.getpeername())
        except Exception:
            cs.close(); return
        try:
            while True:
                r, _, _ = select.select([cs, chan], [], [], 60)
                if cs in r:
                    d = cs.recv(4096)
                    if not d: break
                    chan.sendall(d)
                if chan in r:
                    d = chan.recv(4096)
                    if not d: break
                    cs.sendall(d)
        except Exception:
            pass
        cs.close()
    threading.Thread(target=lambda: [handle(cs) for cs, _ in iter(server.accept, None)], daemon=True).start()
    time.sleep(1)
    return transport


def adb(*args, timeout=60):
    serial = f"127.0.0.1:{STATE['ssh']['lport']}"
    r = subprocess.run([ADB_BIN, "-s", serial, *args], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", errors="ignore")


def dump_xml(tag=""):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=50)
    return adb("shell", "cat", "/sdcard/ui.xml", timeout=30)


def tap_coords(x, y):
    adb("shell", "input", "tap", str(x), str(y))


def tap_text(xml, patterns):
    for pat in patterns:
        for mm in re.finditer(
            rf'(?:text|content-desc)="([^"]*{pat}[^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml, re.I):
            x1, y1, x2, y2 = map(int, mm.groups()[1:])
            adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
            return mm.group(1)[:50]
    return None


def acunar(url: str) -> dict:
    """Flujo completo por ADB para una URL arbitraria."""
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    ssh = STATE["ssh"]
    transport = tunnel(ssh)
    try:
        subprocess.run([ADB_BIN, "kill-server"], capture_output=True); time.sleep(2)
        adb("connect", f"127.0.0.1:{ssh['lport']}"); time.sleep(2)

        # 1. buscar el dominio en la app google
        adb("shell", "am", "start", "-a", "android.search.ACTION_WEB_SEARCH",
            "--es", "query", domain, timeout=30)
        time.sleep(7)
        xml = dump_xml(domain[:12])
        # 2. abrir el resultado cuyo texto contenga el dominio
        hit = tap_text(xml, [re.escape(domain)])
        if not hit:
            # fallback: tap el primer resultado de web
            hit = tap_text(xml, [r"www\.", r"https?:"])
        if not hit:
            return {"ok": False, "error": "resultado_no_encontrado", "stage": "search"}
        time.sleep(7)  # carga in-app

        # 3. Compartir (coordenada fija barra in-app)
        tap_coords(862, 103)
        time.sleep(3)

        # 4. Copiar (coordenada fija del sheet)
        tap_coords(407, 1219)
        time.sleep(2)

        # 5. volver a la app google home y pegar para extraer
        adb("shell", "input", "keyevent", "4"); time.sleep(2)
        adb("shell", "input", "keyevent", "4"); time.sleep(2)
        adb("shell", "monkey", "-p", "com.google.android.googlequicksearchbox",
            "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
        time.sleep(3)
        xml = dump_xml("home")
        if not tap_text(xml, [r"B[u\u00fa]squeda por voz", r"Buscar"]):
            return {"ok": False, "error": "campo_busqueda_no_encontrado", "stage": "paste"}
        time.sleep(3)
        adb("shell", "input", "keyevent", "279")  # KEYCODE_PASTE
        time.sleep(2)
        xml = dump_xml("pasted")
        tokens = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
        if not tokens:
            return {"ok": False, "error": "paste_sin_token", "stage": "extract"}
        token = tokens[-1]

        # 6. registrar
        res = api("POST", "/links/bare", {"code": token.split("/")[-1], "nota": f"worker fox: {url}"})
        return {"ok": True, "token": token, "registro": res}
    finally:
        try:
            transport.stop()
        except Exception:
            pass


def ensure_deps():
    try:
        import paramiko  # noqa
        return
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "paramiko"],
                       timeout=180)


def main():
    # validar credenciales foxphone
    if not FP_EMAIL or not FP_PASS:
        print("FALTA FP_EMAIL/FP_PASS"); sys.exit(1)
    ensure_adb()
    ensure_deps()
    log("worker foxphone iniciado")
    while True:
        try:
            item = api("GET", "/links/queue")
            url = (item or {}).get("url")
            if not url:
                time.sleep(20)
                continue
            log(f"acuñando: {url}")
            # refrescar ssh cada 30 min o si falla
            if not STATE["ssh"] or time.time() - STATE["ssh_at"] > 1800:
                STATE["ssh"] = extraer_ssh()
                STATE["ssh_at"] = time.time()
                log("ssh fresco")
            res = acunar(url)
            log("resultado: " + json.dumps(res, ensure_ascii=False)[:300])
        except Exception as e:
            log("ciclo error: " + str(e)[:300] + " | stage-detail arriba")
            STATE["ssh"] = None
            time.sleep(45)


if __name__ == "__main__":
    main()
