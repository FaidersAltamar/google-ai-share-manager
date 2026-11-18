import sys, socket, threading, select, subprocess, time, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import paramiko

ADB = "C:/Users/faiders/AppData/Local/Temp/platform-tools/adb.exe"
DBG = "D:/Proyectos/Hacking etico/google-share-generator/debug_fox"
info = open(f"{DBG}/ssh_info.txt", encoding="utf-8").read()
m = re.search(r"ssh -o\S+\s+(\S+)@(\S+)\s+-p\s+(\d+)\s+-L\s+(\d+):([^:\s]+):(\d+)", info)
USER, HOST, SPORT, LPORT, RH, RP = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5), int(m.group(6))
SSHPASS = re.search(r"Password:\s*\n\s*(\S+)", info).group(1)
transport = paramiko.Transport((HOST, SPORT)); transport.connect(username=USER, password=SSHPASS)
server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", LPORT)); server.listen(10)
def handle(cs):
    try: chan = transport.open_channel("direct-tcpip", (RH, RP), cs.getpeername())
    except Exception: cs.close(); return
    try:
        while True:
            r,_,_ = select.select([cs, chan], [], [], 60)
            if cs in r:
                d = cs.recv(4096)
                if not d: break
                chan.sendall(d)
            if chan in r:
                d = chan.recv(4096)
                if not d: break
                cs.sendall(d)
    except Exception: pass
    cs.close()
threading.Thread(target=lambda: [handle(cs) for cs,_ in iter(server.accept, None)], daemon=True).start()
time.sleep(1)
def adb(*args, timeout=90):
    r = subprocess.run([ADB, "-s", f"127.0.0.1:{LPORT}", *args], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", errors="ignore")
def dump(tag):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=50)
    xml = adb("shell", "cat", "/sdcard/ui.xml", timeout=30)
    open(f"{DBG}/phone_{tag}.xml", "w", encoding="utf-8").write(xml)
    raw = subprocess.run([ADB, "-s", f"127.0.0.1:{LPORT}", "exec-out", "screencap", "-p"], capture_output=True, timeout=45)
    open(f"{DBG}/phone_{tag}.png", "wb").write(raw.stdout)
    return xml
def tap_text(xml, patterns):
    for pat in patterns:
        for mm in re.finditer(rf'(?:text|content-desc)="([^"]*{pat}[^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml, re.I):
            x1,y1,x2,y2 = map(int, mm.groups()[1:])
            adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
            print(f"tap '{mm.group(1)[:60]}'")
            return True
    return False

subprocess.run([ADB, "kill-server"], capture_output=True); time.sleep(2)
adb("connect", f"127.0.0.1:{LPORT}"); time.sleep(2)

# salir de settings hacia la home de la app google
adb("shell", "input", "keyevent", "4"); time.sleep(2)
adb("shell", "input", "keyevent", "4"); time.sleep(3)
xml = dump("30_home")
nodes = re.findall(r'(?:text|content-desc)="([^"]{2,60})"', xml)
print("pantalla:", nodes[:25])

# tocar el campo de busqueda para abrir el teclado
if not tap_text(xml, [r"Buscar", r"Search"]):
    print("no encontre el campo de busqueda")
    sys.exit(1)
time.sleep(3)
xml = dump("31_keyboard")
nodos = re.findall(r'(?:text|content-desc)="([^"]{2,50})"', xml)
print("teclado:", nodos[:50])

# buscar el chip de portapapeles en gboard
if tap_text(xml, [r"portapapeles|clipboard|Portapapeles"]):
    time.sleep(2)
    xml = dump("32_gboard_clipboard")
    links = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
    print("\n=== TOKEN COMPLETO DESDE GBOARD ===")
    for l in links: print("  ", l)
    if not links:
        nodos = re.findall(r'text="([^"]{2,90})"', xml)
        print("pantalla clipboard:", nodos[:40])
else:
    print("no hay chip de portapapeles - probando los 3 puntos del teclado")
    if tap_text(xml, [r"M[a\u00e1]s opciones|More options"]):
        time.sleep(2)
        xml = dump("33_more")
        if tap_text(xml, [r"portapapeles|clipboard"]):
            time.sleep(2)
            xml = dump("34_clipboard")
            links = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml)
            print("\n=== TOKEN COMPLETO ===")
            for l in links: print("  ", l)
time.sleep(6)
transport.close()
