"""Create a self-contained source ZIP, including the parser and no user data."""
from pathlib import Path
import zipfile
import time

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "dist").mkdir(exist_ok=True)
with zipfile.ZipFile(ROOT / "dist/AOE2-Chat-Investigator-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    def add(path, name):
        info = zipfile.ZipInfo(name, time.localtime(path.stat().st_mtime)[:6])
        info.create_system = 3
        info.external_attr = (0o100755 if path.suffix in ('.sh', '.command') else 0o100644) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes())
    for name in ("gui.py", "runtime.py", "chatlog.py", "fetch_replays.py", "daily_check.py", "README.md", "LICENSE", "Start Windows.bat", "Start macOS.command", "start-linux.sh"):
        add(ROOT / name, "AOE2-Chat-Investigator/" + name)
    for folder in ("ui", "mgz-fast/mgz"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                add(path, "AOE2-Chat-Investigator/" + path.relative_to(ROOT).as_posix())
    add(ROOT / "mgz-fast/LICENSE", "AOE2-Chat-Investigator/mgz-fast/LICENSE")
print("Created dist/AOE2-Chat-Investigator-source.zip")
