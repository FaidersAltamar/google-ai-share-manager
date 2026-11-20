"""Diagnostico v6: por que falla HTTPS en el telefono (TCP vs TLS vs MTU).

    python /tmp/diag6.py
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = "http://ai-share-manager:8000"
ADB = "/opt/platform-tools/platform-tools/adb"
LP = 19536

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


def adb(*a, timeout=60):
    r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", errors="replace")


def ensure_dev(tries=8):
    for _ in range(tries):
        out = adb("devices")
        if "127.0.0.1" in out and "device" in out:
            return True
        adb("connect", f"127.0.0.1:{LP}")
        time.sleep(2)
    raise RuntimeError("sin dispositivo")


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(2)
ensure_dev(); print("devices ok\n")

print("=== 1. ¿existe curl/wget/nc en el telefono? ===")
for b in ("curl", "wget", "nc", "toybox", "ping", "openssl"):
    p = adb("shell", "which", b, timeout=20).strip()
    print(f"   which {b}: {p!r}")

print("\n=== 2. rutas completas (todas las tablas) ===")
print(adb("shell", "ip", "route", "show", "table", "all", timeout=30)[:1500])
print("--- ip rule ---")
print(adb("shell", "ip", "rule", timeout=20)[:800])

print("\n=== 3. TCP connect puro (python en el telefono? / nc) ===")
# probamos con 'toybox nc' o con shell /dev/tcp
for cmd in ("echo -e 'GET / HTTP/1.0\\r\\n\\r\\n' | nc -w 6 142.251.153.119 80",
            "nc -z -w 5 142.251.153.119 443",
            "nc -z -w 5 142.251.153.119 80"):
    out = adb("shell", cmd, timeout=30).strip()
    print(f"   $ {cmd}\n     -> {out[:300]!r}")

print("\n=== 4. test TCP con wget (si existe) ===")
print("   wget:", adb("shell", "wget", "-O", "-", "-T", "12", "http://142.251.153.119/", timeout=40)[:400].replace("\n", " | "))

print("\n=== 5. reloj del telefono (si el TLS falla por reloj) ===")
print("   date:", adb("shell", "date", timeout=20).strip())
print("   epoch:", adb("shell", "date", "+%s", timeout=20).strip())
print("   server time (VPS):", time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()))

print("\n=== 6. MTU ===")
print("   ip link wlan0:", adb("shell", "ip", "link", "show", "wlan0", timeout=25).strip()[:400])
print("   ping -s 1400:", adb("shell", "ping", "-c", "1", "-W", "3", "-s", "1400", "142.251.153.119", timeout=25).strip()[-200:])

print("\n=== 7. chrome: probar con QUIC deshabilitado ===")
print(adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
         "chrome://flags/#enable-quic", timeout=30)[:200])
time.sleep(3)
print("   (flags abierto; probando wget a https en su lugar)")
print("   https test:", adb("shell", "wget", "-O", "-", "-T", "12", "https://www.google.com", timeout=40)[:300].replace("\n", " | "))
