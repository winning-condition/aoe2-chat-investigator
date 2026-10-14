"""Dependency-free local browser GUI. Run python gui.py or the portable app."""
import argparse
import csv
import datetime
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime import SOURCE, worker_command


def stem(name):
    return re.sub(r"[^\w-]", "_", name.lower())


def default_data_dir():
    if not getattr(sys, "frozen", False):
        return SOURCE
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "AOE2 Chat Investigator"


def validate_players(players):
    if not isinstance(players, list):
        raise ValueError("Watchlist must be a list of players.")
    ids, names = set(), set()
    clean = []
    for player in players:
        if not isinstance(player, dict):
            raise ValueError("Each player must have a name and profile ID.")
        name = str(player.get("name", "")).strip()
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError("Enter an in-game name between 1 and 100 characters.")
        file_stem = stem(name)
        if file_stem.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
            raise ValueError("That name is reserved by Windows; use an alternate spelling.")
        profile = player.get("profile_id")
        if isinstance(profile, bool) or not str(profile).isdigit() or not 0 < int(profile) < 2**63:
            raise ValueError("Profile ID must be a positive number.")
        profile = int(profile)
        if profile in ids or file_stem in names:
            raise ValueError("Player names and profile IDs must be unique (including their file names).")
        row = {"name": name, "profile_id": profile}
        since = player.get("since_match")
        if since not in (None, ""):
            if isinstance(since, bool) or not str(since).isdigit() or not 0 < int(since) < 2**63:
                raise ValueError("Since match must be a positive match ID.")
            row["since_match"] = int(since)
        ids.add(profile)
        names.add(file_stem)
        clean.append(row)
    return clean


class Application:
    def __init__(self, data_dir):
        self.data = Path(data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.job = {"status": "idle", "log": "", "label": "Ready"}
        self.process = None
        self.cancelled = threading.Event()
        self.report_snapshot = {}

    def players(self):
        path = self.data / "watchlist.json"
        return validate_players(json.loads(path.read_text(encoding="utf-8-sig"))) if path.exists() else []

    def player(self, profile):
        return next((p for p in self.players() if p["profile_id"] == int(profile)), None)

    def rows(self, player):
        with self.lock:
            if self.job["status"] == "running" and player["profile_id"] in self.report_snapshot:
                return self.report_snapshot[player["profile_id"]]
        path = self.data / "output" / (stem(player["name"]) + "_chat.csv")
        if not path.exists():
            return []
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def save_player(self, payload):
        with self.lock:
            self.require_idle()
            players = self.players()
            item = validate_players([payload])[0]
            old = self.player(item["profile_id"])
            if old and old["name"] != item["name"]:
                old_stem, new_stem = stem(old["name"]), stem(item["name"])
                # Changing spelling must not silently abandon downloaded recordings.
                if old_stem != new_stem and (self.data / "replays" / old_stem).exists():
                    destination = self.data / "replays" / new_stem
                    if destination.exists():
                        raise ValueError("A replay folder already exists for this name. Choose another spelling.")
                    validate_players([p for p in players if p["profile_id"] != item["profile_id"]] + [item])
                    (self.data / "replays" / old_stem).rename(destination)
            players = validate_players([p for p in players if p["profile_id"] != item["profile_id"]] + [item])
            self.write_players(players)

    def write_players(self, players):
        path = self.data / "watchlist.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(players, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def require_idle(self):
        if self.job["status"] == "running":
            raise ValueError("Wait for the current task to finish, or cancel it first.")

    def start_job(self, payload):
        with self.lock:
            self.require_idle()
            action = payload.get("action")
            if action == "daily":
                if not self.players():
                    raise ValueError("Add a player before checking the watchlist.")
                commands = [("daily_check.py", ["--watchlist", str(self.data / "watchlist.json")])]
            elif action in ("fetch", "extract"):
                player = self.player(payload.get("profile_id", 0))
                if not player:
                    raise ValueError("Select a watched player first.")
                folder = self.data / "replays" / stem(player["name"])
                folder.mkdir(parents=True, exist_ok=True)
                pages = payload.get("pages", 3)
                if isinstance(pages, bool) or not str(pages).isdigit() or not 1 <= int(pages) <= 50:
                    raise ValueError("History pages must be between 1 and 50.")
                commands = []
                if action == "fetch":
                    commands.append(("fetch_replays.py", [str(player["profile_id"]), str(folder), "--pages", str(pages)]))
                args = [str(folder), "--player=" + player["name"], "--out", str(self.data / "output")]
                if payload.get("offline"):
                    args.append("--offline")
                commands.append(("chatlog.py", args))
            else:
                raise ValueError("Unknown task.")
            self.cancelled.clear()
            self.report_snapshot = {p["profile_id"]: self.rows(p) for p in self.players()}
            self.job = {"status": "running", "label": {"daily": "Checking all players", "fetch": "Fetching & extracting", "extract": "Extracting local replays"}[action], "log": "", "started": time.time()}
            threading.Thread(target=self._run_job, args=(commands,), daemon=True).start()

    def _run_job(self, commands):
        status = "done"
        try:
            for script, args in commands:
                with self.lock:
                    if self.cancelled.is_set():
                        break
                    self.job["log"] += f"\n{script}\n"
                    self.process = subprocess.Popen(worker_command(script, args, self.data), cwd=self.data,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        start_new_session=sys.platform != "win32")
                    process = self.process
                for line in process.stdout:
                    with self.lock:
                        self.job["log"] = (self.job["log"] + line)[-100000:]
                rc = process.wait()
                process.stdout.close()
                if rc and not self.cancelled.is_set():
                    status = "failed"
                    break
        except Exception as exc:
            with self.lock:
                self.job["log"] += f"\n{exc}\n"
            status = "failed"
        finally:
            with self.lock:
                self.process = None
                self.job["status"] = "cancelled" if self.cancelled.is_set() else status

    def cancel(self):
        with self.lock:
            # Quit, request cancellation and shutdown can arrive together. Once
            # a worker was signalled, do not signal its process group again:
            # macOS can reject that group while the killed child is being reaped.
            if self.cancelled.is_set():
                return
            self.cancelled.set()
            if self.process and self.process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    # Each worker is its own process group, including daily-check children.
                    import signal
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    @property
    def app(self):
        return self.server.app

    def respond(self, data, status=200, mime="application/json; charset=utf-8", filename=None):
        if mime.startswith("application/json"):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
        self.end_headers()
        self.wfile.write(data)

    def route(self):
        parsed = urllib.parse.urlsplit(self.path)
        prefix = "/" + self.server.token + "/"
        if self.headers.get("Host") != self.server.host or not parsed.path.startswith(prefix):
            raise PermissionError("Open the application's launch URL.")
        return urllib.parse.unquote(parsed.path[len(prefix):]), urllib.parse.parse_qs(parsed.query)

    def do_GET(self):
        try:
            route, query = self.route()
            if route == "api/state":
                with self.app.lock:
                    self.respond({"players": self.app.players(), "job": dict(self.app.job), "data_dir": str(self.app.data)})
            elif route == "api/report":
                player = self.app.player(query.get("profile_id", [0])[0])
                if not player:
                    raise ValueError("Player not found.")
                self.respond({"rows": self.app.rows(player)})
            elif route == "api/summary":
                path = self.app.data / "output/latest_check.txt"
                self.respond({"text": path.read_text(encoding="utf-8") if path.exists() else "No daily checks yet. Use Check all players to create a summary."})
            elif route == "api/export":
                self.app.require_idle()
                player = self.app.player(query.get("profile_id", [0])[0])
                if not player:
                    raise ValueError("Player not found.")
                fmt = query.get("format", ["txt"])[0]
                if fmt not in ("txt", "csv"):
                    raise ValueError("Choose text or CSV.")
                path = self.app.data / "output" / f"{stem(player['name'])}_chat.{fmt}"
                if not path.exists():
                    raise ValueError("Extract chat before exporting a report.")
                self.respond(path.read_bytes(), mime="text/plain; charset=utf-8" if fmt == "txt" else "text/csv; charset=utf-8", filename=path.name)
            else:
                path = (SOURCE / "ui" / (route or "index.html")).resolve()
                if not path.is_relative_to((SOURCE / "ui").resolve()) or not path.is_file():
                    self.respond({"error": "Not found"}, 404)
                    return
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.respond(path.read_bytes(), mime=mime)
        except PermissionError as exc:
            self.respond({"error": str(exc)}, 403)
        except (ValueError, OSError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            route, query = self.route()
            if self.headers.get("Origin") not in (None, "http://" + self.server.host):
                raise PermissionError("Request origin rejected.")
            length = int(self.headers.get("Content-Length", "0"))
            limit = 256 * 1024 * 1024 if route == "api/import" else 65536
            if not 0 <= length <= limit:
                raise ValueError("File is too large (maximum 256 MB per replay).")
            if route == "api/import":
                with self.app.lock:
                    self.app.require_idle()
                    player = self.app.player(query.get("profile_id", [0])[0])
                    if not player:
                        raise ValueError("Select a player before importing.")
                    name = query.get("filename", [""])[0]
                    if Path(name).name != name or "/" in name or "\\" in name or Path(name).suffix.lower() not in (".zip", ".aoe2record"):
                        raise ValueError("Choose .zip or .aoe2record files.")
                    data = self.rfile.read(length)
                    if len(data) != length or not data:
                        raise ValueError("Incomplete or empty file.")
                    folder = self.app.data / "replays" / stem(player["name"]) / "imported"
                    folder.mkdir(parents=True, exist_ok=True)
                    # Content-derived filenames avoid overwrites and duplicate imports.
                    path = folder / (hashlib.sha256(data).hexdigest() + Path(name).suffix.lower())
                    path.write_bytes(data)
                self.respond({"ok": True})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("JSON request required.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Invalid request.")
            if route == "api/player":
                self.app.save_player(payload)
            elif route == "api/remove":
                with self.app.lock:
                    self.app.require_idle()
                    self.app.write_players([p for p in self.app.players() if p["profile_id"] != int(payload["profile_id"])])
            elif route == "api/job":
                self.app.start_job(payload)
            elif route == "api/cancel":
                self.app.cancel()
            elif route == "api/quit":
                self.app.cancel()
                # Complete the HTTP response before allowing the server process
                # to exit; request threads are daemons and cannot keep it alive.
                self.respond({"ok": True})
                self.wfile.flush()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                raise ValueError("Unknown action.")
            self.respond({"ok": True})
        except PermissionError as exc:
            self.respond({"error": str(exc)}, 403)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)


def create_server(data_dir, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.app = Application(data_dir)
    server.token = secrets.token_urlsafe(32)
    server.host = f"127.0.0.1:{server.server_port}"
    return server


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=default_data_dir())
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--worker", choices=("chatlog.py", "fetch_replays.py", "daily_check.py"), help=argparse.SUPPRESS)
    ap.add_argument("worker_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        import importlib
        module = importlib.import_module(args.worker[:-3])
        if args.worker == "daily_check.py":
            module.HERE = str(args.data_dir.resolve())
            module.OUT = str(args.data_dir.resolve() / "output")
        worker_args = args.worker_args[1:] if args.worker_args[:1] == ["--"] else args.worker_args
        sys.argv = [args.worker, *worker_args]
        module.main()
        return
    server = create_server(args.data_dir, args.port)
    url = f"http://{server.host}/{server.token}/"
    print(f"AOE2 Chat Investigator\n{url}\nData: {server.app.data}\nUse Quit in the GUI to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.app.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
