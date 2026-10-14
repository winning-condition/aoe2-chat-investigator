"""Launch the same CLI workers from source and from the portable executable."""
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent


def worker_command(script, args, data_dir):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--data-dir", str(data_dir), "--worker", script, "--", *map(str, args)]
    return [sys.executable, "-I", "-u", "-X", "utf8", str(SOURCE / "gui.py"),
            "--data-dir", str(data_dir), "--worker", script, "--", *map(str, args)]
