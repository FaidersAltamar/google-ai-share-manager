"""Diagnostico v11: iptables/redirecciones de volcproxy + auth SOCKS5 + listeners.

    python /tmp/diag_proxy4.py
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


print("connect:", adb("connect", f"127.0.0.1:{LP}")); time.sleep(3)
ensure_dev(); print("devices OK\n")

print("=== 0. identidad del shell adb ===")
print("   id:", adb("shell", "id").strip())
print("   whoami:", adb("shell", "whoami").strip())

print("\n=== 1. listeners (parse /proc/net/tcp) ===")
for proto in ("tcp", "tcp6"):
    out = adb("shell", "cat", f"/proc/net/{proto}")
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) > 3 and f[3] == "0A":
            la = f[1]
            ip, port = la.split(":")
            print(f"   {proto} LISTEN port {int(port,16)}")

print("\n=== 2. iptables nat (¿redirección a proxy local?) ===")
out = adb("shell", "iptables", "-t", "nat", "-L", "-n", "-v")
print(out[:3000] if out.strip() else "   (sin salida / sin permisos)")

print("\n=== 3. iptables mangle/filter REDIRECT ===")
out = adb("shell", "iptables", "-L", "-n")
for line in out.splitlines():
    if "REDIRECT" in line or "DNAT" in line:
        print("   ", line.strip()[:200])

print("\n=== 4. auth SOCKS5 verbose: id como usuario ===")
for u, p in (("api-lyqlunpisb8b", "KJiASPufi1MidDOS"), ("", "KJiASPufi1MidDOS")):
    r = adb("shell", "curl", "-v", "-sS", "-o", "/dev/null", "-m", "12",
            "--socks5-hostname", "proxy.naproxy.net:1000",
            "--proxy-user", f"{u}:{p}", "https://www.google.com/")
    socks_lines = [l.strip() for l in r.splitlines()
                   if any(k in l for k in ("SOCKS5", "Can't complete", "HTTP/1", "Connected", "SSL", "curl:"))]
    print(f"   user={u!r}:")
    for l in socks_lines[:8]:
        print("      ", l[:160])

print("\n=== 5. el proxy responde a dominios domesticos? ===")
for host in ("www.baidu.com", "www.qq.com", "www.taobao.com", "www.bilibili.com"):
    r = adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "--socks5-hostname", "proxy.naproxy.net:1000",
            "--proxy-user", ":KJiASPufi1MidDOS", "-m", "10", f"https://{host}/")
    print(f"   {host:22s} -> {r.strip()[:40]}")

print("\n=== 6. reconnect de red (airplane + dhcp) ===")
adb("shell", "cmd", "connectivity", "airplane-mode", "enable")
time.sleep(6)
adb("shell", "cmd", "connectivity", "airplane-mode", "disable")
time.sleep(15)
print("   ping gw:", "OK" if "bytes from" in adb("shell", "ping", "-c", "1", "-W", "2", "10.24.4.1", timeout=12) else "FAIL")
print("   curl https google:", adb("shell", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                   "-m", "12", "https://www.google.com/").strip()[:40])
print("   ip addr:", [l.strip() for l in adb("shell", "ip", "-4", "addr").splitlines() if "inet " in l])

print("\n=== 7. probar con la IP publica del VPS como proxy HTTP (bridge) ===")
print("   (el telefono no tiene ruta al VPS publico; se comprueba con ping)")
print("   ping 179.66.140.79:", adb("shell", "ping", "-c", "1", "-W", "2", "179.66.140.79", timeout=12).strip()[-160:])
