"""Diagnostico interactivo del telefono FoxPhone via ADB (desde el VPS).

Abre el tunel SSH, lanza la URL en varios intents y vuelca el UI XML de cada
paso para descubrir la pantalla real (textos y coordenadas) sin adivinar.

Uso dentro del contenedor worker:
    python /tmp/diag_fox.py <url>
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = "http://ai-share-manager:8000"
ADB_BIN = "/opt/platform-tools/platform-tools/adb"
OUT = "/tmp/diag"
LOCAL_PORT = int(os.environ.get("DIAG_PORT", "19536"))


def api_get(path):
    return json.loads(urllib.request.urlopen(API + path, timeout=15).read().decode())


def ssh_creds():
    return api_get("/adb-creds")


def tunnel(ssh):
    import paramiko
    transport = paramiko.Transport((ssh["host"], ssh["port"]))
    transport.connect(username=ssh["user"], password=ssh["pass"])
    server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LOCAL_PORT)); server.listen(10)
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
    return transport, server


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=4bfeCGHw8ZI"
    os.makedirs(OUT, exist_ok=True)
    ssh = ssh_creds()
    transport, server = tunnel(ssh)
    serial = f"127.0.0.1:{LOCAL_PORT}"

    def adb(*args, timeout=60):
        r = subprocess.run([ADB_BIN, "-s", serial, *args], capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode("utf-8", errors="ignore")

    def dump(tag):
        adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=50)
        xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
        p = os.path.join(OUT, f"{tag}.xml")
        open(p, "w", encoding="utf-8").write(xml)
        # resumen: textos con sus bounds
        items = []
        for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
            t = m.group(1)
            if t.strip():
                x1, y1, x2, y2 = map(int, m.groups()[1:])
                items.append(f"{t!r} @({(x1+x2)//2},{(y1+y2)//2})")
        print(f"\n=== {tag} ({len(xml)} bytes) ===")
        for it in items[:60]:
            print("  ", it)
        return xml

    try:
        subprocess.run([ADB_BIN, "kill-server"], capture_output=True); time.sleep(2)
        print("connect:", adb("connect", f"127.0.0.1:{LOCAL_PORT}"))
        time.sleep(3)
        print("devices:", adb("devices"))

        # A: estado inicial
        adb("shell", "input", "keyevent", "3")  # home
        time.sleep(2)
        dump("00_home")

        # B: abrir la URL en la app Google (quicksearchbox)
        print("\n>>> B: VIEW intent sobre com.google.android.googlequicksearchbox")
        print(adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url,
                   "com.google.android.googlequicksearchbox", timeout=40)[:300])
        time.sleep(10)
        dump("01_gapp_view")

        # C: compartir desde la barra (coord fija historica)
        print("\n>>> C: tap compartir (862,103)")
        adb("shell", "input", "tap", "862", "103")
        time.sleep(4)
        dump("02_share_sheet")

        # D: copiar (coord fija historica)
        print("\n>>> D: tap copiar (407,1219)")
        adb("shell", "input", "tap", "407", "1219")
        time.sleep(3)
        dump("03_after_copy")

        # E: leer el portapapeles directo (varias vias)
        print("\n>>> E: clipboard directo")
        for cmd in [
            ["shell", "service", "call", "clipboard", "1"],
            ["shell", "cmd", "clipboard", "get", "text"],
            ["shell", "am", "broadcast", "-a", "clipboard.get"],
        ]:
            out = adb(*cmd, timeout=30)
            print(f"  $ {' '.join(cmd)} -> {out[:200]!r}")

        # F: pegar en el buscador de la app Google
        print("\n>>> F: abrir app google y pegar")
        adb("shell", "input", "keyevent", "4"); time.sleep(2)
        adb("shell", "input", "keyevent", "4"); time.sleep(2)
        adb("shell", "monkey", "-p", "com.google.android.googlequicksearchbox",
            "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
        time.sleep(4)
        dump("04_google_home")
        adb("shell", "input", "keyevent", "279")
        time.sleep(3)
        dump("05_pasted")
    finally:
        try:
            transport.close(); server.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
