import sys, os, time, re, json
import urllib.request
import paramiko
import socket
import threading
import select
import subprocess

# Global constants and utilities
API = os.environ.get("VPS_API", "http://ai-share-manager:8000")
GAPP = "com.google.android.googlequicksearchbox"
ADB_BIN = os.environ.get("ADB_BIN", "/opt/platform-tools/platform-tools/adb")
DEBUG_LOG_API = API + "/debug/log"


def log(msg):
    sys.stdout.write(f"FoxWorkerLOG: {msg}\n")
    sys.stdout.flush()
    try:
        urllib.request.urlopen(urllib.request.Request(
            DEBUG_LOG_API,
            data=json.dumps({"line": str(msg)[:500]}).encode(),
            headers={"Content-Type": "application/json"}
        ), timeout=5)
    except Exception:
        pass


class FoxWorker:
    def __init__(self):
        self.ssh_transport = None
        self.local_port = int(os.environ.get("DIAG_PORT", "19536"))
        self._ssh_config = None

    def _get_ssh_config(self):
        if self._ssh_config is None:
            with urllib.request.urlopen(API + "/adb-creds", timeout=15) as r:
                self._ssh_config = json.loads(r.read().decode())
        return self._ssh_config

    def SSHConnect(self, timeout=120):
        cfg = self._get_ssh_config()
        try:
            self.ssh_transport = paramiko.Transport((cfg["host"], cfg["port"]))
            self.ssh_transport.connect(username=cfg["user"], password=cfg["pass"])
            
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.local_port))
            srv.listen(10)
            
            def handler():
                for cs, _ in iter(srv.accept, None):
                    try:
                        ch = self.ssh_transport.open_channel(
                            "direct-tcpip", (cfg["rhost"], cfg["rport"]), cs.getpeername()
                        )
                    except Exception:
                        cs.close()
                        continue
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
            
            threading.Thread(target=handler, daemon=True).start()
            time.sleep(1)
            
            return self._wait_device(10)
        except Exception as e:
            log(f"SSHConnect failed: {e}")
            return False

    def _wait_device(self, tries=10):
        for _ in range(tries):
            out = self.adb("devices")
            if "127.0.0.1" in out and "\tdevice" in out:
                return True
            self.adb("disconnect", f"127.0.0.1:{self.local_port}")
            self.adb("connect", f"127.0.0.1:{self.local_port}")
            time.sleep(3)
        return False

    def adb(self, *args, timeout=20):
        try:
            r = subprocess.run([ADB_BIN, "-s", f"127.0.0.1:{self.local_port}", *args],
                             capture_output=True, timeout=timeout)
            return (r.stdout + r.stderr).decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return "<TIMEOUT>"

    def wipe_app_state(self):
        self.adb("shell", "am", "force-stop", GAPP)
        time.sleep(1)
        self.adb("shell", "pm", "clear", GAPP)
        time.sleep(2)

    def launch_google(self):
        self.adb("shell", "input", "keyevent", "3")
        time.sleep(1)
        self.adb("shell", "monkey", "-p", GAPP, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
        time.sleep(5)

    def type_text(self, text):
        # Tap the search box first
        xml = self.dump_ui()
        nodes = self.parse_nodes(xml)
        box = None
        for n in nodes:
            if "googleapp_facade_search_box" in n["rid"] or "search_box" in n["rid"] or n["text"] == "Buscar":
                box = n
                break
        if box:
            self.tap(box["x"], box["y"])
            time.sleep(1)
        
        escaped = text.replace(" ", "%s")
        self.adb("shell", "input", "text", escaped, timeout=30)
        time.sleep(2)

    def press_enter(self):
        self.adb("shell", "input", "keyevent", "66")
        time.sleep(3)

    def tap(self, x, y):
        self.adb("shell", "input", "tap", str(x), str(y))
        time.sleep(1)

    def dump_ui(self):
        self.adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=30)
        xml = self.adb("shell", "cat", "/sdcard/ui.xml", timeout=15)
        return xml

    def parse_nodes(self, xml):
        nodes = []
        for m in re.finditer(r'<node[^>]*?>', xml):
            node = m.group(0)
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if not bm:
                continue
            g = lambda p: (re.search(p, node).group(1) if re.search(p, node) else "")
            x1, y1, x2, y2 = map(int, bm.groups())
            nodes.append({
                "text": g(r'text="([^"]*)"'),
                "desc": g(r'content-desc="([^"]*)"'),
                "rid": g(r'resource-id="([^"]*)"'),
                "pkg": g(r'package="([^"]*)"'),
                "x": (x1 + x2) // 2,
                "y": (y1 + y2) // 2
            })
        return nodes

    def find_and_tap_suggestion(self, url):
        domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        xml = self.dump_ui()
        nodes = self.parse_nodes(xml)
        for n in nodes:
            if n["text"] and domain in n["text"].lower() and "search_box" not in n["rid"]:
                self.tap(n["x"], n["y"])
                time.sleep(5)
                return True
        return False

    def find_and_tap_organic_result(self, url):
        domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        xml = self.dump_ui()
        nodes = self.parse_nodes(xml)
        for n in nodes:
            if n["pkg"] == GAPP and n["text"] and domain.lower() in n["text"].lower():
                if "search_box" not in n["rid"] and "srp_search_box" not in n["rid"]:
                    self.tap(n["x"], n["y"])
                    time.sleep(5)
                    return True
        return False

    def type_url_direct(self, url):
        clean = url.replace("https://", "").replace("http://", "")
        clean = re.sub(r"[^A-Za-z0-9._\-/]", "%s", clean)
        self.type_text(clean)
        self.press_enter()
        time.sleep(8)

    def extract_token(self):
        xml = self.dump_ui()
        for n in self.parse_nodes(xml):
            if "Compartir" in (n["text"] or "") or "Compartir" in (n["desc"] or ""):
                self.tap(n["x"], n["y"])
                time.sleep(5)
                xml2 = self.dump_ui()
                toks = re.findall(r"https://share\.google/[A-Za-z0-9_\-]+", xml2)
                if toks:
                    return toks[-1]
        return None

    def quit(self):
        if self.ssh_transport:
            self.ssh_transport.close()


def _try_s2_autocomplete(worker, url):
    log(f"[S2] Trying autocomplete for {url}")
    worker.wipe_app_state()
    worker.launch_google()
    
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    worker.type_text(domain[:15])
    time.sleep(2)
    
    # Look for exact URL match in suggestions
    xml = worker.dump_ui()
    nodes = worker.parse_nodes(xml)
    for n in nodes:
        if n["text"] and url.replace("https://", "").replace("http://", "") in n["text"]:
            worker.tap(n["x"], n["y"])
            time.sleep(8)
            return worker.extract_token()
    
    # If no exact match, press ENTER on first suggestion
    worker.press_enter()
    time.sleep(8)
    return worker.extract_token()


def _try_s3_organic(worker, url):
    log(f"[S3] Trying organic search for {url}")
    worker.wipe_app_state()
    worker.launch_google()
    
    domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    worker.type_text(domain)
    worker.press_enter()
    time.sleep(8)
    
    # Look for result containing our domain
    xml = worker.dump_ui()
    nodes = worker.parse_nodes(xml)
    for n in nodes:
        if n["pkg"] == "com.android.chrome" and n["text"] and domain.lower() in n["text"].lower():
            worker.tap(n["x"], n["y"])
            time.sleep(8)
            return worker.extract_token()
    
    # Fallback: tap first result
    for n in nodes:
        if n["pkg"] == "com.android.chrome" and n["text"]:
            worker.tap(n["x"], n["y"])
            time.sleep(8)
            return worker.extract_token()
    
    return None


def _try_s1_direct(worker, url):
    log(f"[S1] Trying direct URL entry for {url}")
    worker.wipe_app_state()
    worker.launch_google()
    
    clean = url.replace("https://", "").replace("http://", "")
    clean = re.sub(r"[^A-Za-z0-9._\-/]", "%s", clean)
    worker.type_text(clean)
    time.sleep(1)
    worker.press_enter()
    time.sleep(10)
    
    return worker.extract_token()


def _try_strategies(url):
    worker = FoxWorker()
    if not worker.SSHConnect(120):
        return {"ok": False, "error": "SSH connection failed"}
    
    strategies = [
        (_try_s2_autocomplete, "S2-autocomplete"),
        (_try_s3_organic, "S3-organic"),
        (_try_s1_direct, "S1-direct"),
    ]
    
    for fn, name in strategies:
        log(f"Attempting {name}...")
        token = fn(worker, url)
        if token:
            log(f"Success with {name}: {token}")
            worker.quit()
            return token
    
    worker.quit()
    return None


def acunar(url):
    return _try_strategies(url)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python app/worker_fox.py <URL>")
        sys.exit(1)
    url = sys.argv[1]
    print(f"Minting token for: {url}")
    token = acunar(url)
    if token:
        print(f"SUCCESS: {token}")
    else:
        print("FAILED: No token obtained")