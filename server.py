"""
PerfMon - live laptop performance dashboard.

Run:  python server.py            (opens a desktop window)
      python server.py --browser  (opens in the default browser instead)
"""
import hashlib
import json
import multiprocessing as mp
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

APP_NAME = "PerfMon"
APP_VERSION = "1.2.0"
HOST, PORT = "127.0.0.1", 8765
INTERVAL = 1.0          # seconds between samples
HISTORY = 300           # samples kept for the graphs (5 minutes)
# When frozen by PyInstaller, bundled files live under sys._MEIPASS.
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC = BASE / "static"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
BENCH_FILE = DATA_DIR / "benchmarks.json"
# LibreHardwareMonitor's "Remote Web Server" (Options -> Remote Web Server -> Run)
LHM_URL = os.environ.get("PERFMON_LHM_URL", "http://127.0.0.1:8085/data.json")


# --------------------------------------------------------------------------- #
# Temperatures (via LibreHardwareMonitor)
# --------------------------------------------------------------------------- #
# Windows has no standard non-admin API for CPU temperature, so PerfMon reads
# the JSON published by LibreHardwareMonitor's local web server.
_SKIP_TEMP = ("distance to tjmax", "warning temperature", "critical temperature",
              "thermal sensor limit")
_KIND_BY_ICON = {"cpu": "cpu", "nvidia": "gpu", "ati": "gpu", "amd": "gpu", "intel": "gpu",
                 "hdd": "disk", "mainboard": "board", "battery": "battery", "ram": "ram"}


def _parse_temp(v):
    """'65.0 °C' -> 65.0 ; converts °F to °C if LHM is set to Fahrenheit."""
    try:
        num = float(v.split()[0].replace(",", "."))
    except (ValueError, IndexError, AttributeError):
        return None
    return round((num - 32) * 5 / 9, 1) if v.rstrip().endswith("F") else num


# Installed layout: <app>\PerfMon.exe + <app>\LibreHardwareMonitor\ ; from source: vendor\
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent / "vendor"
BUNDLED_LHM = APP_DIR / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe"
SENSOR_TASK = r"\PerfMon\Sensors"  # created by the installer; runs LHM elevated without a UAC prompt
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_lhm_exe():
    cands = [str(BUNDLED_LHM), shutil.which("LibreHardwareMonitor")]
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    cands += [str(p) for p in (la / "Microsoft" / "WinGet" / "Packages").glob(
        "LibreHardwareMonitor*/LibreHardwareMonitor.exe")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), str(la / "Programs")):
        if base:
            cands.append(str(Path(base) / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe"))
    return next((c for c in cands if c and Path(c).is_file()), None)


def lhm_running():
    return any((p.info["name"] or "").lower() == "librehardwaremonitor.exe"
               for p in psutil.process_iter(["name"]))


def sensor_task_exists():
    try:
        return subprocess.run(["schtasks", "/Query", "/TN", SENSOR_TASK], capture_output=True,
                              creationflags=_NO_WINDOW, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def start_lhm(allow_uac=True):
    """Start LibreHardwareMonitor: via the installer's scheduled task (no prompt) if present,
    otherwise directly (its manifest triggers a UAC prompt). Returns how it was started."""
    try:
        if subprocess.run(["schtasks", "/Run", "/TN", SENSOR_TASK], capture_output=True,
                          creationflags=_NO_WINDOW, timeout=10).returncode == 0:
            return "task"
    except (OSError, subprocess.SubprocessError):
        pass
    exe = find_lhm_exe()
    if exe and allow_uac:
        os.startfile(exe)
        return "direct"
    return None


def autostart_sensors():
    """On launch: if temperatures aren't available yet, quietly start the bundled sensor task."""
    time.sleep(2.5)
    if sampler and not sampler.thermals.ok and not lhm_running():
        start_lhm(allow_uac=False)


class Thermals:
    """Polls LibreHardwareMonitor; falls back to NVIDIA GPU temp if that's all there is."""

    def __init__(self):
        self._next_try = 0.0
        self.ok = False

    def _fetch(self):
        with urllib.request.urlopen(LHM_URL, timeout=0.6) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def read(self, gpu=None):
        data = None
        now = time.monotonic()
        if self.ok or now >= self._next_try:
            try:
                data = self._fetch()
                self.ok = True
            except Exception:
                self.ok = False
                self._next_try = now + 5  # don't stall the sampler while LHM is absent
        if data is None:
            res = {"source": "none", "sensors": [], "cpu": None, "gpu": None, "disk": None}
            if gpu and gpu.get("temp") is not None:
                res.update(source="nvidia", gpu=gpu["temp"], sensors=[{
                    "id": "nvidia/0", "hw": gpu["name"], "kind": "gpu", "name": "GPU Core",
                    "value": gpu["temp"], "max": None}])
            return res

        sensors, limits = [], {}

        def walk(node, hw=None, kind=None):
            if node.get("HardwareId"):
                hw = node.get("Text")
                icon = (node.get("ImageURL") or "").rsplit("/", 1)[-1].split(".")[0].lower()
                kind = _KIND_BY_ICON.get(icon, "other")
            if node.get("Type") == "Temperature":
                name = node.get("Text") or "?"
                val = _parse_temp(node.get("Value"))
                low = name.lower()
                if any(k in low for k in ("warning temperature", "critical temperature")):
                    limits.setdefault(hw, {})["warn" if "warning" in low else "crit"] = val
                elif val is not None and not any(k in low for k in _SKIP_TEMP) and val > 0:
                    sensors.append({"id": node.get("SensorId"), "hw": hw, "kind": kind,
                                    "name": name, "value": val,
                                    "max": _parse_temp(node.get("Max"))})
            for c in node.get("Children", []):
                walk(c, hw, kind)

        walk(data)
        for s in sensors:
            if s["hw"] in limits:
                s["limits"] = limits[s["hw"]]

        def pick(kind, *prefer):
            group = [s for s in sensors if s["kind"] == kind]
            for want in prefer:
                for s in group:
                    if s["name"].lower() == want:
                        return s["value"]
            return max((s["value"] for s in group), default=None)

        return {"source": "lhm", "sensors": sensors,
                "cpu": pick("cpu", "cpu package", "core max", "core average", "cpu cores"),
                "gpu": pick("gpu", "gpu core", "gpu hot spot"),
                "disk": pick("disk", "composite temperature", "temperature")}

# --------------------------------------------------------------------------- #
# Sampler
# --------------------------------------------------------------------------- #
class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.cond = threading.Condition()
        self.latest = None
        self.history = deque(maxlen=HISTORY)
        self.seq = 0
        self._procs = {}
        self._nvidia = shutil.which("nvidia-smi")
        self._last_disk = psutil.disk_io_counters()
        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        self.thermals = Thermals()
        psutil.cpu_percent(percpu=True)  # prime

    # ---- helpers ---------------------------------------------------------- #
    def _top_processes(self, n=15):
        # Reuse Process objects between samples so cpu_percent() has a baseline.
        seen, items = {}, []
        ncpu = psutil.cpu_count() or 1
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                proc = self._procs.get(p.pid, p)
                cpu = proc.cpu_percent(None)
                seen[p.pid] = proc
                if p.pid == 0:  # System Idle Process
                    continue
                mi = p.info["memory_info"]
                items.append({"pid": p.pid, "name": p.info["name"] or "?",
                              "cpu": round(cpu / ncpu, 1),
                              "mem": mi.rss if mi else 0})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self._procs = seen
        by_cpu = sorted(items, key=lambda i: i["cpu"], reverse=True)[:n]
        by_mem = sorted(items, key=lambda i: i["mem"], reverse=True)[:n]
        return by_cpu, by_mem, len(items)

    def _gpu(self):
        if not self._nvidia:
            return None
        try:
            out = subprocess.run(
                [self._nvidia,
                 "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip().splitlines()[0]
            name, util, used, total, temp = [x.strip() for x in out.split(",")]
            return {"name": name, "util": float(util), "mem_used": float(used),
                    "mem_total": float(total), "temp": float(temp)}
        except Exception:
            self._nvidia = None
            return None

    def _partitions(self):
        parts = []
        for p in psutil.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
                parts.append({"mount": p.mountpoint, "fs": p.fstype,
                              "total": u.total, "used": u.used, "percent": u.percent})
            except (PermissionError, OSError):
                pass
        return parts

    # ---- main sample ------------------------------------------------------ #
    def sample(self, tick):
        now = time.monotonic()
        dt = max(now - self._last_t, 1e-6)
        self._last_t = now

        per_core = psutil.cpu_percent(percpu=True)
        cpu = sum(per_core) / len(per_core)
        freq = psutil.cpu_freq()
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()

        d = psutil.disk_io_counters()
        n = psutil.net_io_counters()
        disk_r = (d.read_bytes - self._last_disk.read_bytes) / dt if d else 0
        disk_w = (d.write_bytes - self._last_disk.write_bytes) / dt if d else 0
        net_rx = (n.bytes_recv - self._last_net.bytes_recv) / dt
        net_tx = (n.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_disk, self._last_net = d, n

        bat = psutil.sensors_battery()
        snap = {
            "t": time.time(),
            "cpu": round(cpu, 1),
            "cores": [round(c, 1) for c in per_core],
            "freq": round(freq.current) if freq else None,
            "freq_max": round(freq.max) if freq else None,
            "mem": {"percent": vm.percent, "used": vm.used, "total": vm.total,
                    "available": vm.available},
            "swap": {"percent": sw.percent, "used": sw.used, "total": sw.total},
            "disk_io": {"read": max(disk_r, 0), "write": max(disk_w, 0)},
            "net": {"rx": max(net_rx, 0), "tx": max(net_tx, 0)},
            "battery": None if bat is None else {
                "percent": round(bat.percent, 1), "plugged": bat.power_plugged,
                "secsleft": bat.secsleft if bat.secsleft not in (
                    psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else None},
            "uptime": time.time() - psutil.boot_time(),
        }
        # heavier stuff every 2nd tick
        if tick % 2 == 0 or self.latest is None:
            by_cpu, by_mem, count = self._top_processes()
            snap.update(procs_cpu=by_cpu, procs_mem=by_mem, proc_count=count,
                        partitions=self._partitions(), gpu=self._gpu())
        else:
            for k in ("procs_cpu", "procs_mem", "proc_count", "partitions", "gpu"):
                snap[k] = self.latest.get(k)
        snap["temps"] = self.thermals.read(snap.get("gpu"))
        return snap

    def run(self):
        tick = 0
        while True:
            start = time.monotonic()
            try:
                snap = self.sample(tick)
                with self.cond:
                    self.latest = snap
                    self.history.append(snap)
                    self.seq += 1
                    self.cond.notify_all()
            except Exception as e:  # never let the sampler die
                print("sampler error:", e)
            tick += 1
            time.sleep(max(0, INTERVAL - (time.monotonic() - start)))


def cpu_name():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def system_info():
    vm = psutil.virtual_memory()
    return {
        "app": APP_NAME, "version": APP_VERSION,
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()} (build {platform.version()})",
        "cpu": cpu_name(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(),
        "ram_total": vm.total,
        "python": platform.python_version(),
    }


# --------------------------------------------------------------------------- #
# Benchmark (runs on demand)
# --------------------------------------------------------------------------- #
def _cpu_work(seconds):
    """Hash 64 KB blocks for `seconds`, return MB hashed."""
    block = os.urandom(65536)
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end:
        hashlib.sha256(block).digest()
        n += 1
    return n * 65536 / 1e6


def _mem_work(seconds):
    """Copy a 256 MB buffer into a pre-allocated one; return GB/s copied."""
    size = 256 * 1024 * 1024
    src, dst = bytearray(size), bytearray(size)
    dst[:] = src  # touch pages once
    reps, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        dst[:] = src
        reps += 1
    return reps * size / (time.perf_counter() - t0) / 1e9


def run_benchmark(progress):
    res = {}
    dur = 3.0

    # CPU/memory tests run in separate worker processes so the server's own
    # threads don't interfere with the measurement.
    progress("CPU single-core")
    with mp.Pool(1) as pool:
        res["cpu_single_mbs"] = round(pool.apply(_cpu_work, (dur,)) / dur, 1)

    progress("CPU multi-core")
    workers = psutil.cpu_count() or 1
    with mp.Pool(workers) as pool:
        total = sum(pool.map(_cpu_work, [dur] * workers))
    res["cpu_multi_mbs"] = round(total / dur, 1)
    res["cpu_workers"] = workers

    progress("Memory bandwidth")
    with mp.Pool(1) as pool:
        res["mem_copy_gbs"] = round(pool.apply(_mem_work, (2.0,)), 2)

    progress("Disk write")
    fsize = 512 * 1024 * 1024
    chunk = os.urandom(4 * 1024 * 1024)
    fd, path = tempfile.mkstemp(prefix="perfmon_bench_")
    try:
        t0 = time.perf_counter()
        with os.fdopen(fd, "wb", buffering=0) as f:
            for _ in range(fsize // len(chunk)):
                f.write(chunk)
            os.fsync(f.fileno())
        res["disk_write_mbs"] = round(fsize / (time.perf_counter() - t0) / 1e6, 1)

        progress("Disk read")
        t0 = time.perf_counter()
        with open(path, "rb", buffering=0) as f:
            while f.read(len(chunk)):
                pass
        # note: may be served from OS cache, so read is an upper bound
        res["disk_read_mbs"] = round(fsize / (time.perf_counter() - t0) / 1e6, 1)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    # Simple composite score (arbitrary reference = 1000 on a mid-range 2022 laptop)
    score = (res["cpu_single_mbs"] / 1500 * 300 +
             res["cpu_multi_mbs"] / 10000 * 350 +
             res["mem_copy_gbs"] / 10 * 150 +
             min(res["disk_write_mbs"], 5000) / 1500 * 200)
    res["score"] = round(score)
    progress("done")
    return res


def load_bench_history():
    try:
        return json.loads(BENCH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_bench_result(r):
    hist = load_bench_history()
    hist.append({**r, "t": time.time(),
                 "plugged": (psutil.sensors_battery() or type("b", (), {"power_plugged": None})).power_plugged})
    hist = hist[-50:]
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BENCH_FILE.write_text(json.dumps(hist), encoding="utf-8")
    except OSError:
        pass


class Bench:
    lock = threading.Lock()
    state = {"running": False, "stage": None, "result": None, "error": None}

    @classmethod
    def start(cls):
        with cls.lock:
            if cls.state["running"]:
                return False
            cls.state = {"running": True, "stage": "starting", "result": None, "error": None}

        def go():
            try:
                r = run_benchmark(lambda s: cls.state.__setitem__("stage", s))
                cls.state.update(result=r)
                save_bench_result(r)
            except Exception as e:
                cls.state.update(error=str(e))
            finally:
                cls.state["running"] = False
        threading.Thread(target=go, daemon=True).start()
        return True


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
sampler = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/info":
            self._json(system_info())
        elif self.path == "/api/history":
            with sampler.cond:
                self._json(list(sampler.history))
        elif self.path == "/api/benchmark":
            self._json(Bench.state)
        elif self.path == "/api/temps/status":
            self._json({"installed": bool(find_lhm_exe()), "bundled": BUNDLED_LHM.is_file(),
                        "task": sensor_task_exists(), "running": lhm_running(),
                        "connected": sampler.thermals.ok, "url": LHM_URL})
        elif self.path == "/api/benchmark/history":
            self._json(load_bench_history())
        elif self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last = -1
            try:
                while True:
                    with sampler.cond:
                        sampler.cond.wait_for(lambda: sampler.seq != last, timeout=5)
                        last, snap = sampler.seq, sampler.latest
                    if snap:
                        self.wfile.write(f"data: {json.dumps(snap)}\n\n".encode())
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/temps/start-lhm":
            try:
                how = start_lhm()
            except OSError as e:
                return self._json({"started": False, "reason": str(e)}, 500)
            if not how:
                return self._json({"started": False, "reason": "not_installed"}, 404)
            return self._json({"started": True, "via": how})
        if self.path == "/api/benchmark":
            started = Bench.start()
            self._json({"started": started}, 202 if started else 409)
        else:
            self.send_error(404)


def make_server():
    for port in (PORT, 0):  # fall back to any free port if 8765 is taken
        try:
            srv = ThreadingHTTPServer((HOST, port), Handler)
            srv.daemon_threads = True
            return srv
        except OSError:
            continue
    raise RuntimeError("could not bind a local port")


def main():
    global sampler
    sampler = Sampler()
    sampler.start()
    srv = make_server()
    url = f"http://{HOST}:{srv.server_address[1]}"
    if "--page" in sys.argv[:-1]:  # e.g. --page thermals
        url += "/#" + sys.argv[sys.argv.index("--page") + 1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=autostart_sensors, daemon=True).start()

    use_browser = "--browser" in sys.argv or os.environ.get("PERFMON_BROWSER") == "1"
    if os.environ.get("PERFMON_NO_BROWSER") == "1":
        print(f"{APP_NAME} running at {url}")
        threading.Event().wait()
        return
    if not use_browser:
        try:
            import webview
            # open maximized: always fits the screen, whatever the display scaling
            webview.create_window(f"{APP_NAME} — Performance Monitor", url,
                                  width=1440, height=900, min_size=(980, 600), maximized=True,
                                  background_color="#0a0e1a")
            webview.start()
            return  # window closed -> exit app
        except Exception as e:  # no WebView2 etc. -> fall back to browser
            print("desktop window unavailable, using browser:", e)
    print(f"{APP_NAME} running at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    mp.freeze_support()
    main()
