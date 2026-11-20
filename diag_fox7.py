"""Diagnostico v7: egress del telefono (proxy / TLS / MTU).

    python /tmp/diag7.py
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


def adb(*a, timeout=18):
    try:
        r = subprocess.run([ADB, "-s", f"127.0.0.1:{LP}", *a], capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return f"<TIMEOUT {timeout}s>"


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

print("=== 1. curl verbose a https (ver punto de fallo) ===")
print(adb("shell", "curl", "-v", "-sS", "-o", "/dev/null", "-m", "8", "https://www.google.com", timeout=30)[:1500])

print("\n=== 2. curl verbose a http puerto 80 ===")
print(adb("shell", "curl", "-v", "-sS", "-o", "/dev/null", "-m", "8", "http://neverssl.com", timeout=30)[:1200])

print("\n=== 3. proxy en props ===")
out = adb("shell", "getprop", timeout=18)
for line in out.splitlines():
    if any(k in line.lower() for k in ("proxy", "http_", "qemu", "gsm.sim", "operator", "wifi.")):
        print("   ", line.strip()[:220])

print("\n=== 4. settings proxy / pac ===")
for c in (["shell", "settings", "get", "global", "http_proxy"],
          ["shell", "settings", "get", "global", "global_http_proxy_host"],
          ["shell", "settings", "get", "global", "global_http_proxy_port"],
          ["shell", "settings", "get", "global", "proxy_pac_url"],
          ["shell", "settings", "get", "global", "captive_portal_mode"]):
    print(f"   $ {' '.join(c[1:])} -> {adb(*c).strip()[:150]!r}")

print("\n=== 5. MTU y MSS ===")
print("   link:", adb("shell", "ip", "link", "show", "wlan0").strip()[:300])
print("   mtu probes:")
for sz in (1200, 1400, 1472):
    r = adb("shell", "ping", "-c", "1", "-W", "2", "-s", str(sz), "142.251.153.119", timeout=15)
    ok = "bytes from" in r
    print(f"     size {sz}: {'OK' if ok else 'FAIL'}")

print("\n=== 6. DNS real ===")
print("   ", adb("shell", "getprop", "net.dns1").strip(), adb("shell", "getprop", "net.dns2").strip())
print("   ping 1.1.1.1:", "OK" if "bytes from" in adb("shell", "ping", "-c", "1", "-W", "2", "1.1.1.1", timeout=12) else "FAIL")
print("   ping 10.24.4.1 (gw):", "OK" if "bytes from" in adb("shell", "ping", "-c", "1", "-W", "2", "10.24.4.1", timeout=12) else "FAIL")
print("   traceroute:", adb("shell", "traceroute", "-n", "-w", "1", "-q", "1", "142.251.153.119", timeout=22)[:800])

print("\n=== 7. chrome: estado de red / policies ===")
print("   chrome policy:", adb("shell", "dumpsys", "device_policy", timeout=25)[:900])
