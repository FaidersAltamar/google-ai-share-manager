"""Diagnostico v17: flujo real de acuñacion (Custom Tab de Google + hoja Google).

Reproduce el flujo que funciono el 19-nov:
  app Google -> buscar URL -> abrir resultado (Custom Tab) -> 'Compartir vinculo'
  -> hoja -> opcion que genera share.google -> leer portapapeles pegando.

    python /tmp/diag_customtab.py [url]
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


def dump(tag, limit=50, only_pkg=None):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=60)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    print(f"\n=== {tag} ({len(xml)}B) ===")
    seen = set()
    for n in nodes(xml):
        if only_pkg and n["pkg"] != only_pkg:
            continue
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


def clear_overlays():
    adb("shell", "uiautomator", "dump", "/sdcard/ui2.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui2.xml", timeout=25)
    for n in nodes(xml):
        if n["pkg"] == "permissioncontroller" and n["text"].strip():
            print(f"   (cerrando dialogo: {n['text']!r})")
            adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
            time.sleep(3)
            return True
    return False


def tap(xml, *, text=None, desc=None, rid=None, contains=None, pkg=None, index=0):
    hits = []
    for n in nodes(xml):
        if pkg and n["pkg"] != pkg:
            continue
        if text is not None and n["text"].strip().lower() == text.lower():
            hits.append(n)
        elif desc is not None and n["desc"].strip().lower() == desc.lower():
            hits.append(n)
        elif rid is not None and n["rid"] == rid:
            hits.append(n)
        elif contains is not None and (contains.lower() in n["text"].lower() or contains.lower() in n["desc"].lower()):
            hits.append(n)
    if not hits:
        print(f"   !! no match text={text} desc={desc} rid={rid} contains={contains} pkg={pkg}")
        return False
    n = hits[index]
    print(f"   -> tap {(n['text'] or n['desc'] or n['rid'])!r} @({n['x']},{n['y']})")
    adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
    return True


def leer_clipboard(tag):
    adb("shell", "input", "keyevent", "3"); time.sleep(2)
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(7)
    clear_overlays()
    adb("shell", "uiautomator", "dump", "/sdcard/ui3.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui3.xml", timeout=25)
    tapped = False
    for n in nodes(xml):
        if "search_box" in n["rid"] or "srp_search_box" in n["rid"]:
            print(f"   -> tap rid={n['rid']} @({n['x']},{n['y']})")
            adb("shell", "input", "tap", str(n["x"]), str(n["y"]))
            tapped = True
            break
    if not tapped:
        tap(xml, contains="Buscar")
    time.sleep(3)
    adb("shell", "input", "keyevent", "279")
    time.sleep(3)
    adb("shell", "input", "keyevent", "111")
    time.sleep(2)
    adb("shell", "uiautomator", "dump", "/sdcard/ui4.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui4.xml", timeout=25)
    toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    campo = [n["text"] for n in nodes(xml) if n["text"].strip() and "search" in n["rid"]]
    print(f"   [{tag}] TOKENS: {toks}")
    print(f"   [{tag}] campo: {campo}")
    return toks


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://scale.com.co/"
    print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
    ensure_dev(); print("devices OK\n")
    adb("shell", "iptables", "-t", "nat", "-F", "VOLC_PROXY_NAT_CHAIN")
    clear_overlays()

    print("########## 1. app Google: buscar la URL ##########")
    adb("shell", "am", "force-stop", GAPP); time.sleep(1)
    adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=40)
    time.sleep(8)
    clear_overlays()
    xml = dump("1_home", limit=22)
    if not tap(xml, rid=GAPP + ":id/googleapp_srp_search_box_text"):
        tap(xml, contains="Buscar")
    time.sleep(3)
    adb("shell", "input", "text", url.replace(":", "%s").replace("/", "%s").replace(".", "%s"))
    time.sleep(2)
    adb("shell", "input", "keyevent", "66")
    time.sleep(12)
    clear_overlays()
    xml = dump("2_resultados", limit=30)

    print("\n########## 2. abrir el primer resultado (Custom Tab) ##########")
    dominio = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    if not tap(xml, contains=dominio):
        print("   !! no se encuentra el dominio en el XML")
    time.sleep(14)
    clear_overlays()
    xml = dump("3_customtab", limit=30)

    print("\n########## 3. 'Compartir vinculo' en la Custom Tab ##########")
    if not tap(xml, contains="Compartir"):
        print("   -> fallback tap (862,103)")
        adb("shell", "input", "tap", "862", "103")
    time.sleep(7)
    clear_overlays()
    xml = dump("4_hoja_google", limit=60)

    print("\n########## 4. leer portapapeles ##########")
    toks = leer_clipboard("hoja")
    if not toks:
        print("\n########## 5. probar 'COPIAR' de la hoja del sistema ##########")
        adb("shell", "input", "keyevent", "4"); time.sleep(2)
        xml = dump("5_vuelta", limit=15)
        if tap(xml, contains="Compartir"):
            time.sleep(6)
            xml = dump("5_hoja", limit=30)
            if tap(xml, text="Más"):
                time.sleep(7)
                xml = dump("5_sistema", limit=40)
                if tap(xml, rid="android:id/chooser_copy_button"):
                    time.sleep(3)
                    toks = leer_clipboard("sistema")

    print("\n>>> RESULTADO FINAL:", toks)


if __name__ == "__main__":
    main()
