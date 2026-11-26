<p align="center">
  <img src="packaging/icon.png" width="96" alt="PerfMon icon">
</p>

<h1 align="center">PerfMon</h1>

<p align="center">
  A live performance monitor and benchmark for Windows laptops and PCs —<br>
  real-time graphs for CPU, memory, disk, network and battery in a clean desktop app.
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="PerfMon overview dashboard" width="900">
</p>

## Features

- **Live dashboard (1-second refresh)** — animated ring gauges for CPU, memory, system drive and battery, with a health badge that tells you at a glance whether the machine is running smoothly or under load.
- **Live graphs (last 3 minutes)** — CPU usage (with average, peak and clock speed), RAM and page file, disk read/write, and network download/upload. Hover any graph for exact values at that moment.
- **Per-core load** — a fill bar for every logical processor.
- **Processes** — the top 15 apps by CPU or memory, with usage bars and a name filter.
- **Storage** — used / free space for every drive.
- **Benchmark** — a ~20 second test of single-core CPU, multi-core CPU, memory bandwidth and disk read/write speed, producing an overall score. Results are saved so you can track scores over time.
- **GPU** — utilisation, temperature and VRAM are shown automatically on machines with an NVIDIA GPU (`nvidia-smi`).
- **Dark and light themes**, native desktop window, no internet connection required.

## Install

Download `PerfMon-Setup-x.y.z.exe` from the [Releases](../../releases) page (or build it yourself — see below) and run it.

- No administrator rights needed (installs per-user by default).
- Optional desktop shortcut and "start when I sign in" option.
- Uninstall from **Settings → Apps** like any other program.

Requires Windows 10/11 (64-bit) with the Microsoft Edge WebView2 runtime, which is preinstalled on Windows 11.

## Run from source

Requires Python 3.10+.

```bat
git clone https://github.com/Sachintha1994/perfmon.git
cd perfmon
pip install -r requirements.txt
python server.py
```

Or just double-click `run.bat`.

Options:

| Command | What it does |
|---|---|
| `python server.py` | Opens PerfMon in its own desktop window |
| `python server.py --browser` | Opens the dashboard in your default browser instead |
| `set PERFMON_NO_BROWSER=1` then `python server.py` | Runs the server only (headless) |

The dashboard is served on `http://127.0.0.1:8765` (or a free port if 8765 is taken). It only listens on localhost.

## Build the installer

```bat
build.bat
```

This will:

1. install the build dependencies (PyInstaller, Pillow),
2. draw the app icon (`packaging/make_icon.py`),
3. bundle `dist/PerfMon/PerfMon.exe` with PyInstaller,
4. compile `installer/PerfMon-Setup-<version>.exe` with [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

If Inno Setup isn't installed, step 4 is skipped and the portable app in `dist/PerfMon/` still works.

## How it works

```
┌──────────────────────────── server.py ────────────────────────────┐
│ Sampler thread ── psutil every 1 s ──► latest snapshot + 3-min    │
│                                         history buffer            │
│ HTTP server (127.0.0.1)                                           │
│   GET  /                       dashboard (static/index.html)      │
│   GET  /stream                 Server-Sent Events, 1 msg/second   │
│   GET  /api/info               static system details              │
│   GET  /api/history            last 3 minutes of samples          │
│   POST /api/benchmark          start a benchmark run              │
│   GET  /api/benchmark          benchmark progress / result        │
│   GET  /api/benchmark/history  saved benchmark runs               │
└───────────────────────────────────────────────────────────────────┘
            ▲                                     
            │  pywebview (Edge WebView2) desktop window
            │  — or any browser with --browser
```

- The UI is a single dependency-free HTML file; charts are drawn on `<canvas>`.
- Benchmark CPU and memory tests run in separate worker processes so the app itself doesn't skew the result.
- Benchmark history is stored in `%LOCALAPPDATA%\PerfMon\benchmarks.json`.

### About the benchmark score

The score is a simple weighted composite (single-core 30%, multi-core 35%, memory 15%, disk write 20%) scaled so that a typical mid-range laptop lands around 1000. It's meant for comparing runs **on the same machine** — e.g. plugged in vs. on battery, before vs. after a cleanup — not as an industry-standard benchmark. For best results, plug in the charger and close heavy apps. Disk read speed may be inflated by the Windows file cache.

## Project structure

```
perfmon/
├── server.py              # sampler, benchmark, HTTP server, desktop window
├── static/index.html      # the dashboard UI
├── requirements.txt
├── run.bat                # run from source
├── build.bat              # build exe + installer
├── packaging/
│   ├── make_icon.py       # generates icon.ico / icon.png
│   └── PerfMon.iss        # Inno Setup installer script
└── docs/screenshot.png
```

## Tech stack

Python · [psutil](https://github.com/giampaolo/psutil) · [pywebview](https://pywebview.flowrl.com/) · HTML/CSS/JavaScript (canvas) · PyInstaller · Inno Setup
