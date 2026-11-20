"""Diagnostico v9: que deja pasar el proxy del telefono + puertos locales de volcproxy.

    python /tmp/diag_proxy2.py
"""
import sys, os, json, time, socket, threading, select, subprocess, urllib.request, re

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
ADB = "/opt/platform-tools/platform-tools/adb"
LP = int(os.environ.get("DIAG_PORT", "19536"))

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


def adb(*a, timeout=18):
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
    raise RuntimeError("sin dispositivo: " + adb("devices"))


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
ensure_dev(); print("devices OK\n")

print("=== 1. puertos escuchando en el telefono (volcproxy local) ===")
for pat in ("tcp", "udp"):
    out = adb("shell", "cat", f"/proc/net/{pat}")
    lines = out.splitlines()[1:]
    for line in lines:
        f = line.split()
        if len(f) > 3:
            la, st = f[1], f[3]
            if st == "0A":  # LISTEN
                ip, port = la.split(":")
                p = int(port, 16)
                if p in (0,) or p > 1000:
                    print(f"   LISTEN {pat} port {p}")

print("\n=== 2. iptables NAT (redirecciones de proxy) ===")
print(adb("shell", "su", "-c", "iptables -t nat -L -n")[:2500])

print("\n=== 3. configuracion volcproxy ===")
for c in (["shell", "getprop", "persist.sys.proxy_status"],
          ["shell", "getprop", "persist.sys.proxy_mode"],
          ["shell", "getprop", "proxy_byte/address"],
          ["shell", "getprop", "proxy_byte/port"],
          ["shell", "getprop", "proxy_byte/type"],
          ["shell", "getprop", "proxy_byte/oversea"]):
    print(f"   {' '.join(c[1:])} = {adb(*c).strip()[:120]!r}")

print("\n=== 4. probar SOCKS5 desde el propio telefono con creds ===")
PWD = "KJiASPufi1MidDOS"
for host in ("www.google.com", "www.youtube.com", "share.google.com", "api.ipify.org",
             "www.baidu.com", "www.facebook.com", "www.instagram.com"):
    r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "--socks5-hostname", "proxy.naproxy.net:1000",
            "--proxy-user", f":{PWD}", "-m", "12", f"https://{host}/")
    print(f"   https://{host:26s} -> {r.strip()[:80]}")

print("\n=== 5. probar SOCKS5 SIN creds (por si ignora auth) ===")
for host in ("www.google.com", "api.ipify.org"):
    r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "--socks5-hostname", "proxy.naproxy.net:1000", "-m", "12", f"https://{host}/")
    print(f"   https://{host:26s} -> {r.strip()[:80]}")

print("\n=== 6. probar otros puertos socks en proxy.naproxy.net ===")
for p in (1000, 1080, 1081, 7890, 7891, 8080, 8888, 80):
    r = adb("shell", "nc", "-w", "3", "proxy.naproxy.net", str(p), timeout=10)
    print(f"   :{p} -> {r.strip()[:100]!r}")

print("\n=== 7. el proxy acepta HTTP CONNECT? ===")
r = adb("shell", "curl", "-v", "-sS", "-o", "/dev/null", "-m", "10",
        "--proxy", "http://proxy.naproxy.net:1000", "--proxy-user", f":{PWD}",
        "https://www.google.com", timeout=25)
print(r[:1200])
