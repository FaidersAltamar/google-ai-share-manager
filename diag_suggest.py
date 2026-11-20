"""Diagnostico v18: como llevar una URL EXACTA a la Custom Tab de Google.

Escribe la URL completa en la barra de la app Google y examina el desplegable
de sugerencias: la primera fila suele ser la URL directa (se abre en la Custom
Tab, no como busqueda).

    python /tmp/diag_suggest.py [url]
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
ADB = "/opt/platform-tools/platform-tools/adb"
LP = int(os.environ.get("DIAG_PORT", "19536"))
GAPP = "com.google.android.googlequicksearchbox"

ssh = json.loads(urllib.request.urlopen(API + "/adb-creds", timeout=15).read().decode())
import paramiko
tr = paramiko.Transport((ssh["host"], ssh["port"]))
tr.connect(username=ssh["user"], password=ssh["pass"])
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LP)); srv.listen(10)


def handle(cs):
    try:
        ch = tr.open_channel("direct-tcpip", (ssh["rhost"], ssh["rport"]), cs.getpeername())
    except Exception:
        cs.close(); return
    try:
        while True:
            r, _, _ = select.select([cs, ch], [], [], 60)
            if cs in r:
                d = cs.recv(4096)
                if not d: break
                ch.sendall(d)
            if ch in r:
                d = ch.recv(4096)
                if not d: break
                cs.sendall(d)
    except Exception:
        pass
    cs.close()


threading.Thread(target=lambda: [handle(c) for c, _ in iter(srv.accept, None)], daemon=True).start()
time.sleep(1)


def adb(*a, timeout=20):
    try:
        r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "<TIMEOUT>"


def ensure_dev(tries=10):
    for _ in range(tries):
        out = adb("devices")
        if "127.0.0.1" in out and "\tdevice" in out:
            return True
        adb("disconnect", f"127.0.0.1:{LP}")
        adb("connect", f"127.0.0.1:{LP}")
        time.sleep(3)
    raise RuntimeError("sin dispositivo")


NODE_RE = re.compile(r'<node[^>]*?>', re.I)


def nodes(xml):
    out = []
    for m in NODE_RE.finditer(xml):
        node = m.group(0)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bm:
            continue
        g = lambda p: (re.search(p, node).group(1) if re.search(p, node) else "")
        x1, y1, x2, y2 = map(int, bm.groups())
        out.append({"text": g(r'text="([^"]*)"'), "desc": g(r'content-desc="([^"]*)"'),
                    "rid": g(r'resource-id="([^"]*)"'), "pkg": g(r'package="([^"]*)"'),
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def dump(tag, limit=50):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=60)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    print(f"\n=== {tag} ({len(xml)}B) ===")
    seen = set()
    for n in nodes(xml):
        label = (n["text"] or n["desc"]).strip()
        if not label:
            continue
        key = (label, n["x"], n["y"], n["rid"])
        if key in seen:
            continue
        seen.add(key)
        rid = n["rid"].split("/")[-1] if n["rid"] else ""
        pk = n["pkg"].split(".")[-1] if n["pkg"] else ""
        print(f"   {label!r} @({n['x']},{n['y']})" + (f" [{rid}]" if rid else "") + (f" <{pk}>" if pk else ""))
        if len(seen) >= limit:
            break
    return xml


def cerrar_dialogos():
    adb("shell", "uiautomator", "dump", "/sdcard/ui2.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui2.xml", timeout=25)
    for n in nodes(xml):
        if n["pkg"] == "permissioncontroller" and n["text"].strip():
            print(f"   (cerrando: {n['text']!r})")
            adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
            time.sleep(3)
            return True
    return False


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=4bfeCGHw8ZI"
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices OK\n")
    adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN")

    print("=== 1. app Google + escribir URL COMPLETA ===")
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(8)
    cerrar_dialogos()
    xml = dump("home", limit=20)
    box = None
    for n in nodes(xml):
        if "srp_search_box_text" in n["rid"] or "search_box" in n["rid"]:
            box = n; break
    if not box:
        for n in nodes(xml):
            if n["text"].strip() == "Buscar":
                box = n; break
    print("   campo:", box["rid"] if box else None)
    adb("shell", "input", "tap", str(box["x"]), str(box["y"]))
    time.sleep(3)
    # input text: el protocolo con : y / no es comodo -> escribimos sin https://
    limpio = url.replace("https://", "").replace("http://", "")
    limpio = re.sub(r"[^A-Za-z0-9._\-/]", "%s", limpio)
    print("   escribiendo:", limpio)
    adb("shell", "input", "text", limpio, timeout=45)
    time.sleep(4)
    xml = dump("sugerencias", limit=40)

    print("\n=== 2. sugerencias que parecen URL directa ===")
    for n in nodes(xml):
        t = n["text"].strip()
        if t and ("watch" in t or "youtube" in t or "Buscar con Google" in t):
            print(f"   {t!r} rid={n['rid'].split('/')[-1]!r} @({n['x']},{n['y']})")

    print("\n=== 3. tocar la sugerencia que NO es 'Buscar con Google' ===")
    objetivo = None
    for n in nodes(xml):
        t = n["text"].strip()
        if t and "Buscar con Google" not in t and ("watch" in t or "youtube" in t or "http" in t):
            objetivo = n; break
    if objetivo:
        print(f"   -> tap {objetivo['text'][:60]!r} @({objetivo['x']},{objetivo['y']})")
        adb("shell", "input", "tap", str(objetivo["x"]), str(objetivo["y"]))
    else:
        print("   -> fallback: ENTER")
        adb("shell", "input", "keyevent", "66")
    time.sleep(16)
    cerrar_dialogos()
    xml = dump("customtab", limit=30)

    print("\n=== 4. url_bar + Compartir ===")
    urlbar = ""
    for n in nodes(xml):
        if n["rid"].endswith("url_bar") and n["text"].strip():
            urlbar = n["text"].strip()
    print("   url_bar:", repr(urlbar))
    share = None
    for n in nodes(xml):
        if "Compartir" in n["text"] or "Compartir" in n["desc"]:
            share = n; break
    if share:
        print(f"   -> tap Compartir @({share['x']},{share['y']})")
        adb("shell", "input", "tap", str(share["x"]), str(share["y"]))
        time.sleep(9)
        xml = dump("hoja", limit=40)
        toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
        print("\n   >>> TOKENS:", toks)
        for n in nodes(xml):
            if n["rid"] and "content_preview" in n["rid"]:
                print("   preview:", repr(n["text"]))


if __name__ == "__main__":
    main()
