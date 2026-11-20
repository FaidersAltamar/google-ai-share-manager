"""Diagnostico v19: llevar la URL EXACTA a la Custom Tab de Google + extraer token.

Estrategias probadas para abrir la URL exacta en la Custom Tab:
  S1: escribir la URL completa (con ?=&) en la barra y ENTER
  S2: tocar la sugerencia que coincide con la URL
  S3: SERP -> resultado -> verificar url_bar

Al final: 'Compartir vinculo' -> el share sheet trae el token en
content_preview_text (no hay que copiar/pegar).

    python /tmp/diag_exact.py [url]
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


def dump(tag, limit=40):
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


def estado():
    """Devuelve (pkg_principal, url_bar, titulo)."""
    adb("shell", "uiautomator", "dump", "/sdcard/ui3.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui3.xml", timeout=25)
    ns = nodes(xml)
    urlbar = ""
    for n in ns:
        if n["rid"].endswith("url_bar") and n["text"].strip():
            urlbar = n["text"].strip()
    pkgs = [n["pkg"] for n in ns if n["pkg"]]
    principal = max(set(pkgs), key=pkgs.count) if pkgs else ""
    return principal, urlbar, xml


def abrir_app_google():
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(8)
    cerrar_dialogos()


def escribir(texto):
    """Escribe texto en el campo de la app Google conservando ? & = etc."""
    ns, _ = ui_nodes()
    box = None
    for n in ns:
        if "search_box" in n["rid"]:
            box = n; break
    if not box:
        for n in ns:
            if n["text"].strip() == "Buscar":
                box = n; break
    if not box:
        return False
    adb("shell", "input", "tap", str(box["x"]), str(box["y"]))
    time.sleep(3)
    # input text: solo los espacios necesitan %s; ?&= se pasan tal cual
    adb("shell", "input", "text", texto.replace(" ", "%s"), timeout=45)
    time.sleep(4)
    return True


def compartir():
    ns, xml = ui_nodes()
    btn = None
    for n in ns:
        if "Compartir" in n["text"] or "Compartir" in n["desc"]:
            btn = n; break
    if not btn:
        return None, xml
    print(f"   -> tap Compartir @({btn['x']},{btn['y']})")
    adb("shell", "input", "tap", str(btn["x"]), str(btn["y"]))
    time.sleep(9)
    cerrar_dialogos()
    ns, xml = ui_nodes()
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    return toks, xml


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=4bfeCGHw8ZI"
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices OK\n")
    adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN")

    # ---------- S1: URL completa + ENTER ----------
    print("########## S1: URL completa + ENTER ##########")
    abrir_app_google()
    escribir(url.replace("https://", "").replace("http://", ""))
    ns, _ = ui_nodes()
    print("   texto en el campo:",
          [n["text"] for n in ns if "search_box" in n["rid"] and n["text"].strip()][:2])
    adb("shell", "input", "keyevent", "66")
    time.sleep(16)
    cerrar_dialogos()
    pkg, urlbar, xml = estado()
    print(f"   pkg={pkg} url_bar={urlbar!r}")
    if "chrome" in pkg:
        toks, _ = compartir()
        print("   >>> TOKENS S1:", toks)
        if toks:
            print("\n>>> EXITO:", toks[-1])
            return

    # ---------- S2: sugerencia que coincide ----------
    print("\n########## S2: sugerencia directa ##########")
    abrir_app_google()
    escribir(url.replace("https://", "").replace("http://", ""))
    ns, _ = ui_nodes()
    objs = [n for n in ns if n["rid"].endswith("text1") and n["text"].strip()]
    print("   sugerencias:", [o["text"][:50] for o in objs[:4]])
    if objs:
        print(f"   -> tap sugerencia {objs[0]['text'][:50]!r}")
        adb("shell", "input", "tap", str(objs[0]["x"]), str(objs[0]["y"]))
        time.sleep(16)
        cerrar_dialogos()
        pkg, urlbar, xml = estado()
        print(f"   pkg={pkg} url_bar={urlbar!r}")
        if "chrome" in pkg:
            toks, _ = compartir()
            print("   >>> TOKENS S2:", toks)
            if toks:
                print("\n>>> EXITO:", toks[-1])
                return

    # ---------- S3: SERP + resultado ----------
    print("\n########## S3: SERP + resultado ##########")
    dominio = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    abrir_app_google()
    escribir(dominio)
    adb("shell", "input", "keyevent", "66")
    time.sleep(14)
    cerrar_dialogos()
    ns, _ = ui_nodes()
    cands = [n for n in ns if n["pkg"] == GAPP and n["text"].strip()
             and dominio.lower() in n["text"].lower()
             and "search_box" not in n["rid"] and "srp_search_box" not in n["rid"]]
    print("   candidatos:", [c["text"][:50] for c in cands[:5]])
    for c in cands[:4]:
        print(f"   -> tap {c['text'][:55]!r}")
        adb("shell", "input", "tap", str(c["x"]), str(c["y"]))
        time.sleep(14)
        cerrar_dialogos()
        pkg, urlbar, xml = estado()
        print(f"      pkg={pkg} url_bar={urlbar!r}")
        if "chrome" in pkg and dominio.split(".")[0] in urlbar.lower():
            toks, _ = compartir()
            print("   >>> TOKENS S3:", toks)
            if toks:
                print("\n>>> EXITO:", toks[-1])
                return
        adb("shell", "input", "keyevent", "4"); time.sleep(6)

    print("\n>>> sin exito")


if __name__ == "__main__":
    main()
