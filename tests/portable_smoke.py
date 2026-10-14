"""Exercise the built executable or the extracted, user-facing release archive."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import queue
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.portable_archive import MAC_APP, NAME, archive_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="store_true", help="test the extracted release archive")
    args = parser.parse_args()
    with ExitStack() as stack:
        data = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="aoe2 portable smoke ")))
        binary = ROOT / "dist" / (NAME + ".exe" if sys.platform == "win32" else NAME)
        bundle = None
        if args.archive:
            extracted = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="aoe2 extracted portable ")))
            archive_path = ROOT / "dist" / archive_name()
            if sys.platform == "win32":
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(extracted)
                binary = extracted / (NAME + ".exe")
            else:
                with tarfile.open(archive_path) as archive:
                    archive.extractall(extracted, filter="data")
                bundle = extracted / MAC_APP if sys.platform == "darwin" else None
                binary = bundle / "Contents/MacOS" / NAME if bundle else extracted / NAME
                assert binary.stat().st_mode & 0o111, "Release lost execute permissions"
            assert (extracted / "README.txt").is_file(), "Release has no launch instructions"
        lines = queue.Queue()
        stdout_file, stderr_file = data / "launch-stdout.txt", data / "launch-stderr.txt"
        launch_args = ["--data-dir", str(data), "--no-browser"]
        if bundle:
            # Exercise the same Launch Services entry point as opening in Finder.
            process = subprocess.Popen(["open", "-n", "-W", "--stdout", str(stdout_file),
                "--stderr", str(stderr_file), str(bundle), "--args", *launch_args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        else:
            process = subprocess.Popen([str(binary), *launch_args], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        reader = threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True)
        reader.start()
        base = None
        def request(route, payload=None):
            req = urllib.request.Request(base + route,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read()
        try:
            deadline = time.monotonic() + 60
            launch_log = ""
            while time.monotonic() < deadline:
                if bundle and stdout_file.exists():
                    launch_log = stdout_file.read_text(encoding="utf-8", errors="replace")
                else:
                    try:
                        launch_log += lines.get(timeout=.2)
                    except queue.Empty:
                        pass
                base = next((line.strip() for line in launch_log.splitlines() if line.startswith("http://")), None)
                if base:
                    break
                if process.poll() is not None:
                    reader.join(timeout=2)
                    while not lines.empty():
                        launch_log += lines.get_nowait()
                    raise AssertionError(f"Portable app exited: {process.returncode}\n{launch_log}")
                if bundle:
                    time.sleep(.1)
            errors = stderr_file.read_text(errors="replace") if stderr_file.exists() else ""
            assert base, f"Portable app did not start\n{launch_log}\n{errors}"
            assert b"AOE2 Chat Investigator" in request("")
            request("api/player", {"name": "PortableTest", "profile_id": 1234567})
            request("api/job", {"action": "extract", "profile_id": 1234567, "offline": True})
            wait_for_job(request, "0 unique replays")
            assert (data / "output/portabletest_chat.csv").exists()
            fixture = ROOT / "mgz-fast/tests/recs/de-67.2.aoe2record"
            import chatlog
            parsed = chatlog.parse_game(str(fixture))
            name = next(iter(parsed["players"].values()))
            request("api/player", {"name": name, "profile_id": 7654321})
            upload = urllib.request.Request(base + "api/import?profile_id=7654321&filename=fixture.aoe2record",
                data=fixture.read_bytes(), headers={"Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(upload, timeout=10) as response:
                assert response.status == 200
            request("api/job", {"action": "extract", "profile_id": 7654321, "offline": True})
            wait_for_job(request, "1 unique replays")
            request("api/quit", {})
            assert process.wait(timeout=20) == 0
            method = "Finder app archive" if bundle else "release archive" if args.archive else "built executable"
            print(f"Portable {method}: launch, assets, watchlist, real replay extraction and shutdown: PASS")
        finally:
            if base and process.poll() is None:
                try:
                    request("api/quit", {})
                    process.wait(timeout=10)
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdout.close()


def wait_for_job(request, expected_log):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = json.loads(request("api/state"))["job"]
        if job["status"] != "running":
            assert job["status"] == "done", job
            assert expected_log in job["log"] and "FAILED" not in job["log"], job
            return
        time.sleep(.2)
    raise AssertionError("Portable extraction timed out")


if __name__ == "__main__":
    main()
