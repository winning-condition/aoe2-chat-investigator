"""Build a portable binary on the OS it will run on (developer tooling only)."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--name", "AOE2-Chat-Investigator", "--paths", str(ROOT / "mgz-fast"),
        "--add-data", f"{ROOT / 'ui'}:ui", "--add-data", f"{ROOT / 'mgz-fast/LICENSE'}:licenses",
        "--hidden-import", "chatlog",
        "--hidden-import", "fetch_replays", "--hidden-import", "daily_check",
        "--collect-submodules", "mgz", "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"), str(ROOT / "gui.py")]
subprocess.run(args, cwd=ROOT, check=True)
