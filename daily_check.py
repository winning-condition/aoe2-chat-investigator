"""Daily check on the players in watchlist.json: download new replays, rebuild
each chat log and summarise what's new.

Usage:
    python -I daily_check.py [--watchlist watchlist.json]

watchlist.json (kept out of git) lists the players to check:

    [{"name": "SomePlayer", "profile_id": 1234567, "since_match": 500000123}]

"since_match" is optional: the first match after an event such as support
acting on a report; lines from that match on are totalled separately.
Replays go to replays/<name>/ and logs to output/<name>_chat.txt (.csv).

Writes output/daily/<date>.txt and output/latest_check.txt. "New" means chat
lines in a player's CSV that weren't there at the previous check; that
includes post-game chat recovered for an older match from a newer replay.
"""
import argparse
import collections
import csv
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")


def run(script, *args):
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, script), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=HERE)
    return p.returncode, p.stdout + p.stderr


def replay_ids(folder):
    return {int(m.group(1)) for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
            if (m := re.search(r"Replay_(\d+)", os.path.basename(p)))}


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def key(r):
    return r["match_id"], r["section"], r["game_time"], r["speaker"], r["type"], r["message"]


def is_chat(r):
    return r["type"] in ("chat", "taunt")


def line(r):
    who = ">>" if r["is_target"] == "True" else "  "
    return f"    {r['game_time'] or '(post)':>7}  {who} {r['speaker']}: {r['message']}"


def check(player):
    """Refresh one player. Returns (count of their new lines, report lines)."""
    name = player["name"]
    stem = re.sub(r"[^\w-]", "_", name.lower())  # matches chatlog.py's file naming
    replays = os.path.join(HERE, "replays", stem)
    csv_path = os.path.join(OUT, f"{stem}_chat.csv")
    state = os.path.join(OUT, "daily", stem)
    prev_csv, prev_ids = os.path.join(state, "previous_chat.csv"), os.path.join(state, "previous_replays.txt")
    os.makedirs(state, exist_ok=True)

    before = replay_ids(replays)
    known = set(open(prev_ids).read().split()) if os.path.exists(prev_ids) else {str(i) for i in before}
    fetch_rc, fetch_log = run("fetch_replays.py", str(player["profile_id"]), replays, "--pages", "3")
    parse_rc, parse_log = run("chatlog.py", replays, "--player", name, "--out", OUT)
    now_ids = replay_ids(replays)
    new_ids = sorted(i for i in now_ids if str(i) not in known)

    rows = read_rows(csv_path)
    prev = collections.Counter(key(r) for r in read_rows(prev_csv))
    new_rows = []
    for r in rows:
        if prev[key(r)]:
            prev[key(r)] -= 1
        else:
            new_rows.append(r)
    new_chat = [r for r in new_rows if is_chat(r)]
    theirs_new = [r for r in new_chat if r["is_target"] == "True"]

    verdict = (f"ALERT: {len(theirs_new)} new chat/taunt line(s) from {name}" if theirs_new
               else f"Nothing new from {name}")
    out = ["=" * 70, verdict, "",
           f"New replays since the last check: {len(new_ids)}" + (f"  ({', '.join(map(str, new_ids))})" if new_ids else "")]
    since = player.get("since_match")
    if since:
        later = [r for r in rows if r["match_id"].isdigit() and int(r["match_id"]) >= since]
        theirs = [r for r in later if is_chat(r) and r["is_target"] == "True"]
        out.append(f"Since match {since}: {sum(i >= since for i in now_ids)} replays, "
                   f"{len(theirs)} chat/taunt lines from {name}")
    out.append("")
    by_match = collections.defaultdict(list)
    for r in new_chat:
        by_match[r["match_id"]].append(r)
    if by_match:
        out.append(f"New chat since the last check (>> = {name}):")
        for mid, rs in by_match.items():
            r0 = rs[0]
            out.append(f"  {r0['date']} | Match {mid} | {r0['map']} | vs {r0['opponents']} | {r0['result'] or '?'}")
            out += [line(r) for r in rs]
            out.append("")
    else:
        out += ["No new chat from anyone since the last check.", ""]
    if fetch_rc or parse_rc:
        out.append("WARNING: a step failed; see the log below.")
    out += ["-" * 70, "fetch_replays.py:", fetch_log.strip(), "", "chatlog.py:", parse_log.strip(), ""]

    # Only advance the baseline when the log was rebuilt, so a failed run's lines show up next time.
    if parse_rc == 0 and os.path.exists(csv_path):
        shutil.copyfile(csv_path, prev_csv)
        with open(prev_ids, "w") as f:
            f.write("\n".join(map(str, sorted(now_ids))))
    return len(theirs_new), verdict, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default=os.path.join(HERE, "watchlist.json"))
    args = ap.parse_args()
    with open(args.watchlist, encoding="utf-8") as f:
        players = json.load(f)

    stamp = datetime.datetime.now()
    results = [check(p) for p in players]
    alerts = sum(n for n, _, _ in results)
    head = [f"Daily chat check - {stamp:%Y-%m-%d %H:%M}",
            f"ALERT: new chat from {sum(n > 0 for n, _, _ in results)} watched player(s)" if alerts
            else "Nothing new from any watched player", ""]
    head += [v for _, v, _ in results] + [""]
    text = "\n".join(head + [ln for _, _, out in results for ln in out]) + "\n"
    os.makedirs(os.path.join(OUT, "daily"), exist_ok=True)
    for path in (os.path.join(OUT, "daily", f"{stamp:%Y-%m-%d}.txt"), os.path.join(OUT, "latest_check.txt")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(head[1])


if __name__ == "__main__":
    main()
