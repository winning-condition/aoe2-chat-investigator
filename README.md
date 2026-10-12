# aoe2-chat-investigator

An application that monitors known bad actors in the AOE2 community, downloads their available (or latest) recorded games, and parses them for spicy content in chat. Assists in the generation of evidence of code of conduct violations for user reports to moderators.

---

## In plain terms

If you've ever reported someone in **Age of Empires II: Definitive Edition** for abuse in chat, you know the hard part is proof. The game keeps no chat history you can scroll back through. By the time you file a report, all you have is your memory and maybe a screenshot.

The proof does exist, though. **Every ranked match is recorded**, and the recording includes every chat line and taunt. aoe2-chat-investigator collects those recordings for you and turns them into a readable transcript:

1. **You tell it who to watch.** List a player's in-game name and profile ID in a small local file.
2. **It downloads their recent games** from the official replay service, the same files the game's "watch replay" feature uses.
3. **It extracts the chat** from every game: who said what, when in the match, and whether it went to everyone or only to some players.
4. **It writes a report**: one text file to read and one spreadsheet (CSV) to filter, with every line tied to a match ID that moderators can look up.
5. **Optionally, it runs every day** and writes a short summary: either *"nothing new"* or *"ALERT: new chat from this player"*.

It doesn't judge anything. It doesn't flag swear words or decide what counts as abuse. It gives you a complete, accurately attributed record, and you decide what's worth reporting.

### Who it's for

- Players who keep running into the same toxic opponent and want a solid report instead of "he was rude, trust me".
- Anyone checking whether a player's behaviour changed after support acted on a report.
- Community organisers who need a fair, checkable record before taking action.

### What it is not

- **Not a public shame list.** Watched players, downloaded games and chat logs stay on your machine and are never committed to this repository (see [Privacy](#privacy-and-what-stays-local)).
- **Not a toxicity detector.** It records what was said; reading it is up to you.
- **Not a moderation tool.** Only the official support team can act on an account. This project helps you send them a better report.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [The watchlist and daily checks](#the-watchlist-and-daily-checks)
- [Reading the chat log](#reading-the-chat-log)
- [Accuracy: how chat is attributed](#accuracy-how-chat-is-attributed)
- [Turning a log into a report](#turning-a-log-into-a-report)
- [Privacy and what stays local](#privacy-and-what-stays-local)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Credits and license](#credits-and-license)

---

## How it works

```
 watchlist.json ──► fetch_replays.py ──► replays/<player>/       (.zip recordings)
  (who to watch)       │                        │
                       │ match list from        ▼
                       │ aoe2companion.com   chatlog.py ──► output/<player>_chat.txt  (readable)
                       │                        │          output/<player>_chat.csv  (one row per line)
                       ▼                        ▼
               official replay service    daily_check.py ──► output/latest_check.txt (what's new today)
               (aoe.ms)                                       output/daily/<date>.txt (history of checks)
```

| Script | What it does |
|---|---|
| `fetch_replays.py` | Reads a player's match history from [aoe2companion.com](https://www.aoe2companion.com) and downloads each game's recording from the official AoE2 DE replay service. It skips games already in the folder and stops once it reaches recordings that have expired. |
| `chatlog.py` | Parses every recording in a folder and its subfolders, removes duplicates, and writes the chat log as text and CSV. It also uses match history to work out which match each piece of carried-over post-game chat belongs to (see [Accuracy](#accuracy-how-chat-is-attributed)). |
| `daily_check.py` | Runs both scripts for each player in `watchlist.json`, compares the result with the previous check, and writes a short summary of anything new. |
| `mgz-fast/` | The replay parser library ([AoEInsights/mgz-fast](https://github.com/AoEInsights/mgz-fast)), included as a git submodule. |

---

## Requirements

- **Python 3.8 or newer** (tested on 3.14). There's nothing to `pip install`; everything else is in the standard library or the bundled `mgz-fast`.
- **Git**, to clone the project with its submodule.
- **An internet connection**, to read match history and download recordings.
- The **profile ID** of each player you want to watch (see below).

Works on Windows, macOS and Linux. The scheduled daily check described below uses Windows Task Scheduler; cron does the same job on macOS and Linux.

---

## Installation

```
git clone --recursive https://github.com/winning-condition/aoe2-chat-investigator.git
cd aoe2-chat-investigator
```

If you cloned without `--recursive`, the `mgz-fast` folder will be empty. Fill it with:

```
git submodule update --init
```

### Finding a player's profile ID

Search for the player on [aoe2companion.com](https://www.aoe2companion.com) and open their profile. The number in the address bar is the profile ID, for example `https://www.aoe2companion.com/profile/1234567` → `1234567`. The same ID appears in the profile URL on [aoe2insights.com](https://www.aoe2insights.com).

---

## Quick start

To log a single player once (`SomePlayer` and `1234567` are placeholders):

```
python -I fetch_replays.py 1234567 replays/someplayer --pages 3
python -I chatlog.py replays/someplayer --player SomePlayer --out output
```

Then open `output/someplayer_chat.txt`.

- `--pages` sets how far back to look in match history, at 20 matches per page. Recordings expire after a few weeks, so going further back rarely finds more.
- `--player` must match the in-game name exactly as it appears in the recordings. Capitalisation doesn't matter.
- Replays you downloaded yourself (for example from aoe2insights.com or the game client) can go in the same folder, including subfolders. Duplicates are counted once.
- The `-I` flag runs Python in isolated mode, so nothing in the folder can be picked up as a Python module. It's a sensible habit with downloaded files.

---

## The watchlist and daily checks

To watch a player over time, list them in `watchlist.json` in the project folder. Create the file yourself; it's ignored by git, so it never leaves your machine:

```json
[
  {"name": "SomePlayer", "profile_id": 1234567},
  {"name": "AnotherPlayer", "profile_id": 7654321, "since_match": 500000123}
]
```

| Field | Meaning |
|---|---|
| `name` | In-game name, as it appears in the recordings. |
| `profile_id` | The player's profile ID. |
| `since_match` | *Optional.* A match ID marking an event, such as support saying they'd handled your report. Each check then gives a running total of this player's chat from that match on, so you can see whether their behaviour changed. |

Then run:

```
python -I daily_check.py
```

It updates every watched player and writes `output/latest_check.txt`:

```
Daily chat check - 2026-01-15 09:00
ALERT: new chat from 1 watched player(s)

ALERT: 3 new chat/taunt line(s) from SomePlayer
Nothing new from AnotherPlayer

======================================================================
ALERT: 3 new chat/taunt line(s) from SomePlayer

New replays since the last check: 4  (...)

New chat since the last check (>> = SomePlayer):
  2026-01-14 21:17 | Match 500000001 | Arabia | vs Opponent | won
      12:45     Opponent: gl hf
      13:02  >> SomePlayer: ...
```

The first run for a player treats everything as already seen. From then on, a check reports only what's new since the previous one, including post-game chat recovered later from a newer recording.

### Running it every day (Windows)

In PowerShell, from the project folder:

```powershell
$py  = (Get-Command pythonw).Source      # pythonw runs without a console window
$dir = (Get-Location).Path
Register-ScheduledTask -TaskName 'aoe2-chat-investigator daily check' `
  -Action   (New-ScheduledTaskAction -Execute $py -Argument "-I `"$dir\daily_check.py`"" -WorkingDirectory $dir) `
  -Trigger  (New-ScheduledTaskTrigger -Daily -At 9:00AM) `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable)
```

`-StartWhenAvailable` means that if the PC was off at 9:00, the check runs as soon as it can. To remove the task, run `Unregister-ScheduledTask -TaskName 'aoe2-chat-investigator daily check'`.

On macOS or Linux, add a cron entry instead: `0 9 * * * cd /path/to/aoe2-chat-investigator && python3 -I daily_check.py`.

---

## Reading the chat log

`output/<player>_chat.txt` lists each match that has chat, oldest first. Matches with no chat are left out. Here's an example with made-up names:

```
==============================================================================
2026-01-14 21:17 | Match 500000001 | Arabia | vs Opponent | 34:10 | SomePlayer won
Replay: AgeIIDE_Replay_500000001.zip
------------------------------------------------------------------------------
  09:50  -- Opponent advanced to the Feudal Age. --
  12:45     Opponent: gl hf
  13:02  >> SomePlayer: [taunt 11: (Herb laugh)]
  20:14  >> SomePlayer: ...
  34:10  -- Opponent resigned --
  [post-game chat, no timestamps: recovered from the next replay; verified against match history]
            Opponent: gg
```

| Marker | Meaning |
|---|---|
| `>>` | A line sent by the watched player. |
| `12:45` | **In-game** time, not clock time. Ranked games run at 1.7× speed, so 30 in-game minutes is about 18 real minutes. |
| Several lines with the same time | Usually means the game was paused while people typed. |
| `(All)` | In team games: sent to all players, opponents included. |
| `[sent only to: …]` | A private message to some players only. |
| `[taunt N: …]` | A numbered taunt, shown with its standard text. |
| `-- … --` | Game events: age-ups and resignations. |
| `########` | Text the game's own chat filter censored before it was recorded. The original words aren't in the recording. |
| Post-game section | Chat sent after the recording stopped (see below). |

The CSV has the same content with one row per line. Columns are date, match ID, file, map, opponents, result, section, game time, speaker, `is_target`, type, message, and how the line was attributed. Open it in Excel or Google Sheets to filter by speaker or search across every match at once.

---

## Accuracy: how chat is attributed

If a log is used as evidence, attributing a line to the wrong person is far worse than missing one. The parser is built around that.

**Live chat is exact.** Lines typed during a match are recorded with the sender's player slot and the game time, so they're attributed with certainty.

**Post-game chat needs care.** A match's recording stops when the game ends, but people often keep chatting on the results screen. AoE2 DE stores that chat at the start of the *next* recording the player makes, as a block of history from the previous game. Its player numbers refer to the previous game's lineup, not the new one. `chatlog.py` handles this in three steps:

- It uses the player's public **match history** to identify which match came before. Only then does it attach the chat to that match, marked *"verified against match history"*.
- It removes lines the earlier match already contained, so nothing appears twice. A genuine repeated "gg" can occasionally be lost this way, but nothing is credited to the wrong match.
- If the previous match's own recording is missing, the chat is still recovered but marked **UNVERIFIED**. If the source match can't be identified at all, the chat goes in an **unattributed** section labelled with player slots (P1/P2) instead of names.

When reporting, treat *verified* and live lines as solid. Quote UNVERIFIED or unattributed lines only alongside something that corroborates them.

`--offline` skips the match-history lookup. Post-game chat is then matched by timing alone (the next game started shortly after) and marked *"matched by timing only (unverified)"*.

---

## Turning a log into a report

1. Open `output/<player>_chat.txt` and find the lines that break the game's code of conduct.
2. For each incident, note the **date**, the **match ID** and the **in-game time**. Moderators can find the match from its ID.
3. Quote the lines exactly, with a few lines before and after for context. That makes it clear you aren't quoting selectively.
4. Report through the in-game report button and/or [Age of Empires Support](https://support.ageofempires.com). Attach the relevant part of the log, or the CSV filtered to that player.
5. After support responds, add a `since_match` to the watchlist so you can see whether anything changed.

Keep to what the log actually shows. If the other side provoked the exchange, include those lines too: a report that leaves them out is easy to dismiss.

---

## Privacy and what stays local

This repository contains **software only**. The `.gitignore` keeps everything below on your machine:

| Kept local | Why |
|---|---|
| `watchlist.json` | Names the players you're watching. |
| `replays/` | Downloaded game recordings. |
| `output/` | Chat logs, CSVs and daily summaries, i.e. other people's words. |

Don't publish logs of other players. Send them to the game's support team, who are the only ones who can act on them. All the data this tool reads (match history and recordings) is already available to anyone through the game and the services above. The tool just organises it.

---

## Limitations

- **Recordings expire.** The official service keeps them for a few weeks; older matches can't be recovered. `fetch_replays.py` reports how many were no longer available.
- **A match still being played has no recording yet.** It's picked up on the next run.
- **Silence isn't proof of reform.** A player who stops chatting may have changed, or may be under a chat restriction from support. The recordings look the same either way.
- **Only what was sent is recorded.** Voice chat and Steam or Xbox messages aren't in the recording. Text the game's filter censored shows up as `########`.
- **Result and map** come from match history and can be blank for very recent matches.
- **Match history comes from aoe2companion.com**, a community service. If it's unreachable, post-game chat falls back to timing-based matching and is marked as unverified.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'mgz'` | The submodule is missing. Run `git submodule update --init`. |
| A player has no matches in the log | Check that `--player` matches the in-game name in the recordings (renamed accounts keep the old name in older games) and that the profile ID is right. |
| `Downloaded 0; N no longer available` | Those recordings have expired or were never uploaded to the replay service. |
| `HTTP Error 429` | Too many requests too quickly. The scripts already wait and retry; try again later. |
| `UnicodeEncodeError` when printing names | Update to the current `chatlog.py`, which prints UTF-8. Output files are always UTF-8. |
| The daily task doesn't seem to run | In Task Scheduler, check the task's *Last Run Result*, then open `output/latest_check.txt` and read the log at the bottom. |

---

## Credits and license

- Replay parsing by [mgz-fast](https://github.com/AoEInsights/mgz-fast) (MIT), based on [aoc-mgz](https://github.com/happyleavesaoc/aoc-mgz) by happyleaves.
- Match history from [aoe2companion.com](https://www.aoe2companion.com).
- Recordings from the official Age of Empires II: DE replay service.

Not affiliated with or endorsed by Microsoft, World's Edge or Forgotten Empires.

Licensed under the MIT License. See [LICENSE](LICENSE).
