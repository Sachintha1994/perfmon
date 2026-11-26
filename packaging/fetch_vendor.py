"""
Downloads the third-party components bundled into the PerfMon installer and
verifies them against pinned SHA-256 hashes (from the projects' GitHub releases).

  vendor/LibreHardwareMonitor/   LibreHardwareMonitor 0.9.6 (MPL-2.0) - reads sensors
  vendor/PawnIO_setup.exe        PawnIO 2.2.0 (GPL-2.0) - signed driver LHM uses for CPU sensors

Run by build.bat; safe to re-run (skips downloads that are already verified).
"""
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
DL = VENDOR / "downloads"

COMPONENTS = [
    {
        "name": "LibreHardwareMonitor 0.9.6",
        "url": "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip",
        "sha256": "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001",
        "file": "LibreHardwareMonitor-0.9.6.zip",
    },
    {
        "name": "PawnIO 2.2.0",
        "url": "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe",
        "sha256": "1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032",
        "file": "PawnIO_setup-2.2.0.exe",
    },
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(c):
    dest = DL / c["file"]
    if dest.exists() and sha256(dest) == c["sha256"]:
        print(f"  {c['name']}: cached")
        return dest
    print(f"  {c['name']}: downloading")
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(c["url"], headers={"User-Agent": "PerfMon-build"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    got = sha256(tmp)
    if got != c["sha256"]:
        tmp.unlink()
        sys.exit(f"SHA-256 mismatch for {c['name']}: expected {c['sha256']}, got {got}")
    tmp.replace(dest)
    return dest


def main():
    DL.mkdir(parents=True, exist_ok=True)
    lhm_zip, pawnio = (fetch(c) for c in COMPONENTS)

    out = VENDOR / "LibreHardwareMonitor"
    if out.exists():
        shutil.rmtree(out)
    with zipfile.ZipFile(lhm_zip) as z:
        for m in z.infolist():
            target = (out / m.filename).resolve()
            if not str(target).startswith(str(out.resolve())):  # zip-slip guard
                sys.exit(f"unsafe path in zip: {m.filename}")
            if Path(m.filename).name.lower() == "librehardwaremonitor.config":
                continue  # PerfMon ships its own preset config
            z.extract(m, out)
    if not (out / "LibreHardwareMonitor.exe").exists():
        sys.exit("LibreHardwareMonitor.exe not found in the zip")
    shutil.copy2(pawnio, VENDOR / "PawnIO_setup.exe")
    print("  vendor/ ready")


if __name__ == "__main__":
    main()
