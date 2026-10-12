"""Download a player's match replays from the official AoE2 DE replay service.

Usage:
    python -I fetch_replays.py <profile id> <replay folder> [--pages N]

Reads the player's match history from aoe2companion.com and downloads every
replay not already somewhere under <replay folder> into <replay folder>/fetched.
Replays the service no longer has (they expire) are reported and skipped.
"""
import argparse
import glob
import json
import os
import re
import time
import urllib.error
import urllib.request

HISTORY_URL = "https://data.aoe2companion.com/api/matches?profile_ids={}&page={}"
REPLAY_URL = "https://aoe.ms/replay/?gameId={}&profileId={}"


def get(url, timeout=60, retries=5):
    req = urllib.request.Request(url, headers={"User-Agent": "fetch_replays.py"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 10 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile_id", type=int)
    ap.add_argument("folder")
    ap.add_argument("--pages", type=int, default=50, help="history pages to read (20 matches each)")
    args = ap.parse_args()

    have = {int(m.group(1)) for p in glob.glob(os.path.join(args.folder, "**", "*"), recursive=True)
            if (m := re.search(r"Replay_(\d+)", os.path.basename(p)))}
    matches = []
    for page in range(1, args.pages + 1):
        batch = json.loads(get(HISTORY_URL.format(args.profile_id, page)))["matches"]
        if not batch:
            break
        matches += batch
        time.sleep(1.5)
    print(f"History: {len(matches)} matches; {len(have)} replays already in the folder.")

    out = os.path.join(args.folder, "fetched")
    os.makedirs(out, exist_ok=True)
    got, gone, failed, misses = 0, 0, [], 0
    for m in sorted(matches, key=lambda m: m["started"], reverse=True):
        mid = m["matchId"]
        if mid in have:
            continue
        try:
            data = get(REPLAY_URL.format(mid, args.profile_id))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                gone += 1
                misses += 1
                # Replays expire oldest-first; stop once a long run is already gone.
                if misses >= 15:
                    print(f"  {misses} unavailable in a row; older replays have likely expired. Stopping.")
                    break
                continue
            failed.append((mid, e))
            continue
        except Exception as e:
            failed.append((mid, e))
            continue
        if not data.startswith(b"PK"):
            gone += 1
            misses += 1
            continue
        misses = 0
        with open(os.path.join(out, f"AgeIIDE_Replay_{mid}.zip"), "wb") as f:
            f.write(data)
        got += 1
        print(f"  downloaded {mid}  {m['started'][:16]}")
        time.sleep(0.5)
    print(f"Downloaded {got}; {gone} no longer available; {len(failed)} failed.")
    for mid, e in failed:
        print(f"  FAILED {mid}: {e}")


if __name__ == "__main__":
    main()
