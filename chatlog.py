"""Extract chat logs from AoE2 DE replays (.aoe2record or .zip) for one player.

Usage:
    python -I chatlog.py <replay folder> --player <name> [--out <dir>] [--offline]

Scans the folder and its subfolders (duplicate replays are counted once) and
writes <out>/<player>_chat.txt (readable, games in order) and
<out>/<player>_chat.csv (one row per message). Games without any typed chat
or taunts are left out.

DE replays start with a block of chat carried over from the recorder's
previous game: the end of that game's chat plus post-game chat sent after its
recording stopped. Its player numbers refer to the previous game's lineup.
The player's public match history (aoe2companion.com) identifies which match
that was, so the chat is moved onto it - including matches whose replay is
not in the folder. With --offline (or if the history can't be fetched) the
previous replay in the folder is used when it ended shortly before, and the
chat is marked as matched by timing.
"""
import argparse
import csv
import datetime
import glob
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mgz-fast"))

from mgz.const import DE_MAP_NAMES  # noqa: E402
from mgz.fast import meta, operation  # noqa: E402
from mgz.fast.enums import Action, Operation  # noqa: E402
from mgz.fast.header import parse  # noqa: E402

TAUNTS = {
    1: "Yes.", 2: "No.", 3: "Food, please.", 4: "Wood, please.", 5: "Gold, please.",
    6: "Stone, please.", 7: "Ahh!", 8: "All hail, king of the losers!", 9: "Ooh!",
    10: "I'll beat you back to Age of Empires.", 11: "(Herb laugh)", 12: "Ah! Being rushed.",
    13: "Sure, blame it on your ISP.", 14: "Start the game already!",
    15: "Don't point that thing at me!", 16: "Enemy sighted!", 17: "It is good to be the king.",
    18: "Monk! I need a monk!", 19: "Long time, no siege.",
    20: "My granny could scrap better than that.", 21: "Nice town, I'll take it.",
    22: "Quit touching me!", 23: "Raiding party!", 24: "Dadgum.", 25: "Eh, smite me.",
    26: "The wonder, the wonder, the... no!", 27: "You played two hours to die like this?",
    28: "Yeah, well, you should see the other guy.", 29: "Roggan.", 30: "Wololo!",
    31: "Attack an enemy now.", 32: "Cease creating extra villagers.",
    33: "Create extra villagers.", 34: "Build a navy.", 35: "Stop building a navy.",
    36: "Wait for my signal to attack.", 37: "Build a wonder.",
    38: "Give me your extra resources.", 39: "(Ally sound)", 40: "(Enemy sound)",
    41: "(Neutral sound)", 42: "What age are you in?",
}
PLACEHOLDER = re.compile(r"<player_id,(\d+),\d+>")
MATCH_ID = re.compile(r"Replay_(\d+)")
HISTORY_URL = "https://data.aoe2companion.com/api/matches?profile_ids={}&page={}"
# A message sent to the echo channel (destinationMap 1) within this long of an identical
# message to the players is a second copy of it (seen in games with spectators).
ECHO_WINDOW_MS = 5000
# Timing fallback: next game starts within this many seconds of the previous one ending.
MAX_GAP_SECONDS = 20 * 60


def read_replay(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".aoe2record", ".mgz", ".mgx"))]
            return z.read(names[0])
    with open(path, "rb") as f:
        return f.read()


def fmt_time(ms):
    s = ms // 1000
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def fmt_date(epoch):
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def parse_game(path):
    data = read_replay(path)
    f = io.BytesIO(data)
    h = parse(f)
    de = h["de"]
    active = [p for p in de["players"] if p["number"] != -1]
    players = {p["number"]: p["name"].decode("utf-8", "replace") for p in active}
    meta(f)
    t, events, carried = 0, [], []
    while f.tell() < len(data):
        try:
            op, payload = operation(f)
        except EOFError:
            break
        if op == Operation.SYNC:
            t += payload[0]
        elif op == Operation.ACTION and payload[0] == Action.RESIGN:
            events.append({"t": t, "kind": "resign", "player": payload[1].get("player_id"), "text": ""})
        elif op == Operation.CHAT:
            try:
                j = json.loads(payload)
            except ValueError:
                continue
            msg = {"t": t, "player": j.get("player"), "text": j.get("message", ""),
                   "taunt": j.get("tauntNumber", -1), "all": j.get("channel") == 1,
                   "dest": j.get("destinationMap")}
            system = PLACEHOLDER.search(msg["text"]) is not None
            msg["kind"] = "system" if system else ("taunt" if msg["taunt"] > 0 else "chat")
            # Live messages carry a rendered messageAGP; carried-over history does not.
            (events if j.get("messageAGP") else carried).append(msg)
    events, carried = drop_echoes(events), drop_echoes(carried)
    match_id = MATCH_ID.search(os.path.basename(path))
    return {
        "file": os.path.basename(path),
        "guid": de["guid"],
        "match_id": int(match_id.group(1)) if match_id else None,
        "start": de["timestamp"],
        "speed": h["metadata"]["speed"] or 1.7,
        "duration_ms": t,
        "map": DE_MAP_NAMES.get(de["rms_map_id"], f"map #{de['rms_map_id']}"),
        "rated": de["rated"],
        "players": players,
        "profiles": {p["number"]: p["profile_id"] for p in active},
        "events": events,
        "carried": carried,
        "postgame": [],
        "postgame_note": "",
        "unattributed": [],
        "result": "",
    }


def drop_echoes(msgs):
    """Drop second copies sent to the echo channel; keep echo-only messages."""
    used, kept = set(), []
    for m in msgs:
        if m.get("dest") == 1:
            twin = next((i for i, o in enumerate(msgs) if i not in used and o.get("dest") not in (None, 1)
                         and chat_key(o) == chat_key(m) and abs(o["t"] - m["t"]) <= ECHO_WINDOW_MS), None)
            if twin is not None:
                used.add(twin)
                continue
        kept.append(m)
    return kept


def audience(msg, players):
    """Note when a message was not addressed to every player (bit n+1 = player n)."""
    dest = msg.get("dest")
    if dest is None or msg["kind"] not in ("chat", "taunt"):
        return ""
    to = [name for n, name in players.items() if dest & (1 << (n + 1))]
    if len(to) == len(players):
        return ""
    return f" [sent only to: {', '.join(to)}]" if to else " [not addressed to any player]"


def fetch_history(profile_id, since):
    """The player's matches (oldest first) back to the given start time."""
    matches = {}
    for page in range(1, 51):
        req = urllib.request.Request(HISTORY_URL.format(profile_id, page), headers={"User-Agent": "chatlog.py"})
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.load(r)["matches"]
        for m in batch:
            matches[m["matchId"]] = m
        if not batch or min(iso_epoch(m["started"]) for m in batch) < since:
            break
    return sorted(matches.values(), key=lambda m: iso_epoch(m["started"]))


def iso_epoch(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def stub_game(m, target):
    """A match from the history whose replay isn't in the folder."""
    players = {p["slot"] + 1: p["name"] for t in m["teams"] for p in t["players"]}
    return {
        "file": None, "guid": None, "match_id": m["matchId"], "start": iso_epoch(m["started"]),
        "speed": 1.7, "duration_ms": None, "map": m.get("mapName") or "?", "rated": True,
        "players": players, "events": [], "carried": [], "postgame": [], "postgame_note": "",
        "unattributed": [], "result": result_for(m, target), "missing": True,
    }


def result_for(m, target):
    for t in m["teams"]:
        for p in t["players"]:
            if p["name"].lower() == target.lower() and p.get("won") is not None:
                return "won" if p["won"] else "lost"
    return ""


def order_carried(carried):
    """Carried chat is replayed in chunks (one per tick): chunks newest-first,
    messages inside a chunk oldest-first. Return it oldest-first."""
    chunks = {}
    for m in carried:
        chunks.setdefault(m["t"], []).append(m)
    return [m for t in sorted(chunks, reverse=True) for m in chunks[t]]


def chat_key(m):
    return m["player"], m["text"]


def drop_repeats(carried, prev):
    """Keep only the chat sent after the previous match's recording stopped.

    The chat window also holds whatever the previous match already had: what it carried in
    and its live chat. Their order isn't reliable (chat that passes through a match can be
    stored reshuffled), so each line the previous match already had cancels one matching
    copy, wherever it sits. A genuine post-game repeat of an earlier line (a second "gg") can
    be lost this way, but nothing is credited to the wrong match."""
    known = [chat_key(m) for m in prev["carried"] + prev["events"] if m["kind"] in ("chat", "taunt")]
    kept = []
    for m in carried:
        if m["kind"] == "system":
            continue
        if chat_key(m) in known:
            known.remove(chat_key(m))
        else:
            kept.append(m)
    return kept


def link_by_history(games, history, target):
    """Attach each replay's carried chat to the match that preceded it in the history.
    Returns the full list of games including stubs for matches not in the folder."""
    by_id = {g["match_id"]: g for g in games}
    order = [m["matchId"] for m in history]
    stubs = {}
    for m in history:
        if m["matchId"] in by_id:
            g = by_id[m["matchId"]]
            g["result"] = result_for(m, target)
            if g["map"].startswith("map #") and m.get("mapName"):
                g["map"] = m["mapName"]
    for g in games:
        if not g["carried"]:
            continue
        carried = order_carried(g["carried"])
        if g["match_id"] not in order or order.index(g["match_id"]) == 0:
            g["unattributed"] = carried
            continue
        i = order.index(g["match_id"])
        prev_id = order[i - 1]
        prev = by_id.get(prev_id)
        if prev is None:
            # Chat can pass through a match unchanged, so also drop what the match before it already had.
            before = by_id.get(order[i - 2]) if i >= 2 else None
            prev = stubs.setdefault(prev_id, stub_game(history[i - 1], target))
            prev["postgame"] = drop_repeats(carried, before) if before else carried
            prev["postgame_note"] = (f"UNVERIFIED - replay of this match is not in the folder; its closing "
                                     f"chat was recovered from the next replay ({g['file']}). Speakers are "
                                     f"matched by player slot and some lines may be from the match before")
        else:
            prev["postgame"] = drop_repeats(carried, prev)
            prev["postgame_note"] = "recovered from the next replay; verified against match history"
    # Matches missing from the folder whose replays (or successors' replays) may hold more chat.
    local = [i for i in order if i in by_id]
    missing = []
    if local:
        lo, hi = order.index(local[0]), min(order.index(local[-1]) + 1, len(order) - 1)
        missing = [history[i] for i in range(lo, hi + 1) if order[i] not in by_id]
    return games + list(stubs.values()), missing


def link_by_timing(games):
    for prev, game in zip([None] + games[:-1], games):
        if not game["carried"]:
            continue
        carried = order_carried(game["carried"])
        if prev is not None:
            prev_end = prev["start"] + prev["duration_ms"] / 1000 / prev["speed"]
            if -60 <= game["start"] - prev_end <= MAX_GAP_SECONDS:
                prev["postgame"] = drop_repeats(carried, prev)
                prev["postgame_note"] = "recovered from the next replay; matched by timing only (unverified)"
                continue
        game["unattributed"] = carried
    return games


def render(msg, players, target):
    name = players.get(msg["player"], f"P{msg['player']}")
    if msg["kind"] == "resign":
        return f"-- {name} resigned --"
    text = PLACEHOLDER.sub(lambda m: players.get(int(m.group(1)), f"P{m.group(1)}"), msg["text"])
    if msg["kind"] == "system":
        return f"-- {text} --"
    if msg["kind"] == "taunt":
        label = TAUNTS.get(msg["taunt"])
        text = f"[taunt {msg['taunt']}: {label}]" if label else f"[taunt {msg['taunt']}]"
    marker = ">>" if name.lower() == target.lower() else "  "
    scope = " (All)" if msg["all"] and len(players) > 2 else ""
    return f"{marker} {name}{scope}: {text}{audience(msg, players)}"


def has_chat(g):
    msgs = g["events"] + g["postgame"] + g["unattributed"]
    return any(m["kind"] in ("chat", "taunt") for m in msgs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--player", required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--offline", action="store_true", help="don't fetch match history; link by timing")
    args = ap.parse_args()
    target = args.player
    # Opponent names can hold characters the Windows console codepage can't print.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    paths = sorted(p for ext in ("*.zip", "*.aoe2record")
                   for p in glob.glob(os.path.join(args.folder, "**", ext), recursive=True))
    games, failed, seen = [], [], set()
    for p in paths:
        try:
            g = parse_game(p)
        except Exception as e:  # keep going past a bad file
            failed.append((os.path.basename(p), e))
            continue
        if g["guid"] in seen:
            continue
        seen.add(g["guid"])
        if any(n.lower() == target.lower() for n in g["players"].values()):
            games.append(g)
    games.sort(key=lambda g: g["start"])
    duplicates = len(paths) - len(failed) - len(seen)

    missing, history_note = [], "match history: not used (--offline)"
    profile_id = next((g["profiles"][n] for g in games for n, name in g["players"].items()
                       if name.lower() == target.lower()), None)
    if not args.offline and games and profile_id:
        try:
            history = fetch_history(profile_id, games[0]["start"] - 86400)
            games, missing = link_by_history(games, history, target)
            history_note = f"match history: aoe2companion.com, profile {profile_id}"
        except Exception as e:
            history_note = f"match history: unavailable ({e}); post-game chat matched by timing"
            games = link_by_timing(games)
    else:
        games = link_by_timing(games)
    games.sort(key=lambda g: g["start"])

    os.makedirs(args.out, exist_ok=True)
    stem = re.sub(r"[^\w-]", "_", target.lower())
    txt_path = os.path.join(args.out, f"{stem}_chat.txt")
    csv_path = os.path.join(args.out, f"{stem}_chat.csv")
    shown = [g for g in games if has_chat(g)]
    target_lines = 0

    # Keep the last complete report readable while the GUI rebuilds it. A failed
    # or cancelled worker must not replace it with a half-written transcript.
    txt_temp, csv_temp = txt_path + ".tmp", csv_path + ".tmp"
    with open(txt_temp, "w", encoding="utf-8") as txt, open(csv_temp, "w", encoding="utf-8-sig", newline="") as cf:
        w = csv.writer(cf)
        w.writerow(["date", "match_id", "file", "map", "opponents", "result", "section", "game_time",
                    "speaker", "is_target", "type", "message", "attribution"])
        txt.write(f"Chat logs for {target}" + (f" (profile {profile_id})" if profile_id else "") + "\n")
        txt.write(f"{len(shown)} matches with chat, of {len(games)} matches parsed. {history_note}\n")
        txt.write(">> marks lines sent by the player. Times are in-game time; runs of identical\n"
                  "times usually mean the game was paused.\n\n")
        for g in shown:
            names = list(g["players"].values())
            opponents = ", ".join(n for n in names if n.lower() != target.lower())
            date = fmt_date(g["start"])
            length = fmt_time(g["duration_ms"]) if g["duration_ms"] is not None else "length ?"
            result = f"{target} {g['result']}" if g["result"] else ""
            head = " | ".join(x for x in (date, f"Match {g['match_id'] or '?'}", g["map"], f"vs {opponents}",
                                          length, result) if x)
            txt.write("=" * 78 + "\n" + head + "\n")
            txt.write(f"Replay: {g['file']}\n" if g["file"] else "Replay: NOT IN FOLDER\n")
            txt.write("-" * 78 + "\n")
            sections = [("game", g["events"], g["players"], ""),
                        ("post-game", g["postgame"], g["players"], g["postgame_note"]),
                        ("unattributed", g["unattributed"], {}, "carried over from an earlier match that "
                         "could not be identified; P1/P2 are that match's player slots")]
            for section, msgs, players, note in sections:
                if not msgs:
                    continue
                if section != "game":
                    txt.write(f"  [{section} chat, no timestamps: {note}]\n")
                for m in msgs:
                    line = render(m, players, target)
                    stamp = fmt_time(m["t"]) if section == "game" else ""
                    txt.write(f"{stamp:>7}  {line}\n")
                    speaker = players.get(m["player"], f"P{m['player']}")
                    is_target = speaker.lower() == target.lower()
                    target_lines += is_target and m["kind"] in ("chat", "taunt")
                    w.writerow([date, g["match_id"], g["file"] or "", g["map"], opponents, g["result"], section,
                                stamp, speaker, is_target, m["kind"], line.split(": ", 1)[-1].strip("- "),
                                note if section != "game" else "recorded live"])
            txt.write("\n")

    os.replace(txt_temp, txt_path)
    os.replace(csv_temp, csv_path)
    skipped = [g for g in games if not has_chat(g) and not g.get("missing")]
    print(f"Parsed {len(seen)} unique replays ({duplicates} duplicates skipped, {len(failed)} failed).")
    print(history_note)
    print(f"{len(shown)} matches have chat; {len(skipped)} without chat left out. "
          f"{target_lines} chat/taunt lines from {target}.")
    for name, e in failed:
        print(f"  FAILED {name}: {e}")
    if missing:
        print(f"\n{len(missing)} matches in this period have no replay in the folder. Downloading them "
              f"would add their chat\nand the post-game chat of the match before each:")
        for m in missing:
            opp = ", ".join(p["name"] for t in m["teams"] for p in t["players"] if p["name"].lower() != target.lower())
            print(f"  {m['matchId']}  {fmt_date(iso_epoch(m['started']))}  vs {opp}")
    print(f"\nWrote {txt_path}\nWrote {csv_path}")


if __name__ == "__main__":
    main()
