const $ = (id) => document.getElementById(id);
const state = {
  players: [],
  selected: null,
  rows: [],
  match: null,
  job: { status: "idle" },
  tab: "transcripts",
};
const base = new URL(".", location.href);
const endpoint = (route) => new URL(`api/${route}`, base);
function icon(name) {
  const paths = {
    folder: '<path d="M3 6h7l2 3h9v11H3Z" fill="currentColor" stroke="none"/>',
    download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    chevron: '<path d="m9 4 7 8-7 8"/>',
    text: '<path d="M6 3h8l4 4v14H6Z" fill="currentColor" stroke="none"/><path d="M9 10h6m-6 4h6m-6 3h6" stroke="#3b2616"/>',
    csv: '<path d="M4 3h16v18H4ZM4 9h16M4 15h16M10 3v18M15 3v18"/>',
  };
  const svg = new DOMParser().parseFromString(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name]}</svg>`,
    "image/svg+xml",
  ).documentElement;
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  return svg;
}
for (const [id, name] of [
  ["fetch", "download"],
  ["extract", "folder"],
  ["import", "folder"],
])
  $(id).prepend(icon(name));
document.querySelector(".searchbox").prepend(icon("search"));

async function api(route, body) {
  const response = await fetch(
    endpoint(route),
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notify(message) {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}
function attempt(fn) {
  return async () => {
    try {
      notify("");
      await fn();
    } catch (error) {
      notify(error.message);
    }
  };
}
function selectedPlayer() {
  return state.players.find((p) => p.profile_id === state.selected);
}
function matchKey(row) {
  return row.match_id || `unknown:${row.file}`;
}
function setBusy() {
  const running = state.job.status === "running";
  for (const id of [
    "add-player",
    "edit-player",
    "check-all",
    "fetch",
    "extract",
    "import",
  ]) {
    $(id).disabled =
      running ||
      (!selectedPlayer() &&
        ["edit-player", "fetch", "extract", "import"].includes(id)) ||
      (id === "check-all" && !state.players.length);
  }
  $("cancel").hidden = !running;
  document
    .querySelectorAll(".export a")
    .forEach((link) => link.setAttribute("aria-disabled", String(running)));
}
function renderPlayers() {
  $("players").replaceChildren();
  for (const player of state.players) {
    const button = element(
      "button",
      undefined,
      `player-row${player.profile_id === state.selected ? " selected" : ""}`,
    );
    button.setAttribute(
      "aria-pressed",
      String(player.profile_id === state.selected),
    );
    button.append(
      element("span", player.name),
      element("small", `Profile ${player.profile_id}`),
    );
    button.append(icon("chevron"));
    button.addEventListener(
      "click",
      attempt(async () => {
        state.selected = player.profile_id;
        state.match = null;
        renderPlayers();
        await loadReport();
      }),
    );
    $("players").append(button);
  }
  if (!state.players.length)
    $("players").append(
      element(
        "p",
        "Your watchlist is empty. Add a player, then fetch their replays or import local recordings.",
        "empty",
      ),
    );
  const player = selectedPlayer();
  $("player-name").textContent = player?.name || "Your local chat archive";
  $("player-profile").textContent = player
    ? `Profile ${player.profile_id}${player.since_match ? ` · Since match ${player.since_match}` : ""}`
    : "Add a player to get started.";
  setBusy();
}
async function loadReport() {
  const profile = state.selected;
  const data = profile
    ? await api(`report?profile_id=${profile}`)
    : { rows: [] };
  if (profile !== state.selected) return;
  state.rows = data.rows;
  renderMatches();
}
function matchingRows() {
  const query = $("search").value.trim().toLocaleLowerCase();
  return state.rows.filter(
    (row) =>
      (!$("target-only").checked || row.is_target === "True") &&
      (!query ||
        [
          row.message,
          row.speaker,
          row.match_id,
          row.map,
          row.opponents,
          row.date,
        ].some((value) => (value || "").toLocaleLowerCase().includes(query))),
  );
}
function renderMatches() {
  const groups = new Map();
  for (const row of matchingRows()) {
    const key = matchKey(row);
    if (!groups.has(key)) groups.set(key, row);
  }
  const matches = [...groups].sort(
    (a, b) =>
      (b[1].date || "").localeCompare(a[1].date || "") ||
      b[0].localeCompare(a[0]),
  );
  if (!groups.has(state.match)) state.match = matches[0]?.[0] || null;
  $("matches").replaceChildren();
  $("match-count").textContent = matches.length ? `(${matches.length})` : "";
  for (const [key, row] of matches) {
    const button = element(
      "button",
      undefined,
      `match-row${key === state.match ? " selected" : ""}`,
    );
    button.setAttribute("aria-pressed", String(key === state.match));
    button.append(
      element("span", row.match_id || "Unidentified match"),
      element(
        "small",
        `${row.map || "Unknown map"}${row.result ? ` · ${row.result}` : ""}`,
      ),
      element("small", row.date || "Unknown date"),
    );
    button.append(icon("chevron"));
    button.addEventListener("click", () => {
      state.match = key;
      renderMatches();
    });
    $("matches").append(button);
  }
  if (!matches.length)
    $("matches").append(
      element(
        "p",
        state.rows.length
          ? "No matches fit these filters."
          : "No transcripts yet.",
        "empty",
      ),
    );
  renderTranscript();
}
function renderTranscript() {
  const root = $("transcript");
  root.replaceChildren();
  if (!state.match) {
    const empty = element("div", undefined, "empty");
    empty.append(
      element(
        "h3",
        state.rows.length ? "No matching chat" : "Build your chat archive",
      ),
      element(
        "p",
        state.rows.length
          ? "Try another search or turn off Watched player only."
          : "Fetch recent replays, or import your own recordings and extract their chat. Match details and attribution will appear here.",
      ),
    );
    root.append(empty);
    return;
  }
  const rows = state.rows.filter(
    (row) =>
      matchKey(row) === state.match &&
      (!$("target-only").checked || row.is_target === "True"),
  );
  const first = rows[0];
  const top = element("div", undefined, "transcript-top");
  const heading = element("div");
  heading.append(
    element(
      "h3",
      first.match_id ? `Match ${first.match_id}` : "Unidentified match",
    ),
    element(
      "p",
      `${first.map || "Unknown map"} · vs ${first.opponents || "Unknown opponent"}`,
    ),
  );
  const exports = element("div", undefined, "export");
  for (const [format, label] of [
    ["txt", "Text"],
    ["csv", "CSV"],
  ]) {
    const link = element("a", label);
    link.prepend(icon(format === "txt" ? "text" : "csv"));
    link.href = endpoint(
      `export?profile_id=${state.selected}&format=${format}`,
    );
    link.setAttribute("download", "");
    link.title = `Export complete player report as ${label}`;
    exports.append(link);
    link.setAttribute("aria-disabled", String(state.job.status === "running"));
    link.addEventListener("click", (event) => {
      if (state.job.status === "running") {
        event.preventDefault();
        notify("Wait for extraction to finish before exporting.");
      }
    });
  }
  top.append(heading, exports);
  root.append(
    top,
    element(
      "p",
      "In-game times · attribution shown on each section",
      "caption",
    ),
  );
  let previousSection = "";
  for (const row of rows) {
    const key = `${row.section}|${row.attribution}`;
    if (key !== previousSection) {
      if (row.section !== "game") {
        const unverified =
          /unverified|unattributed|timing|could not|not in folder/i.test(
            row.attribution || "",
          ) || row.section === "unattributed";
        root.append(
          element(
            "p",
            `${row.section === "post-game" ? "Post-game" : "Unattributed"} · ${row.attribution || "No attribution available"}`,
            `section-note${unverified ? " warning" : ""}`,
          ),
        );
      } else if (previousSection)
        root.append(element("p", "In-game · recorded live", "section-note"));
      previousSection = key;
    }
    const line = element(
      "div",
      undefined,
      `chat-line${row.is_target === "True" ? " target" : ""}${row.type !== "chat" && row.type !== "taunt" ? " event" : ""}`,
    );
    const content = element("div");
    content.append(
      element("strong", `${row.speaker}: `),
      element("span", row.message),
    );
    line.append(element("time", row.game_time || "Post"), content);
    root.append(line);
  }
}
async function refresh() {
  const data = await api("state");
  const before = state.job.status;
  state.players = data.players;
  state.job = data.job;
  if (!state.players.some((p) => p.profile_id === state.selected))
    state.selected = state.players[0]?.profile_id || null;
  $("data-dir").textContent = `Local storage: ${data.data_dir}`;
  $("log").textContent = data.job.log;
  if (data.job.status === "running")
    $("status").textContent = `${data.job.label}…`;
  else if (data.job.status === "done")
    $("status").textContent =
      "Task finished. Review the task log for unavailable replays or parsing warnings.";
  else if (data.job.status === "failed") {
    $("status").textContent = "Task failed. See the task log for details.";
    $("task-log").open = true;
  } else if (data.job.status === "cancelled")
    $("status").textContent = "Task cancelled. Completed downloads are kept.";
  renderPlayers();
  if (before === "running" && data.job.status !== "running") {
    await loadReport();
    await loadSummary();
  }
}
async function loadSummary() {
  $("summary-text").textContent = (await api("summary")).text;
}
function openPlayer(editing) {
  const player = editing ? selectedPlayer() : null;
  $("dialog-title").textContent = player ? "Edit player" : "Add player";
  $("name").value = player?.name || "";
  $("profile").value = player?.profile_id || "";
  $("profile").readOnly = Boolean(player);
  $("since").value = player?.since_match || "";
  $("remove").hidden = !player;
  $("form-error").textContent = "";
  $("player-dialog").showModal();
  $("name").focus();
}
$("add-player").addEventListener("click", () => openPlayer(false));
$("edit-player").addEventListener("click", () => openPlayer(true));
$("dismiss").addEventListener("click", () => $("player-dialog").close());
$("player-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const player = {
      name: $("name").value.trim(),
      profile_id: $("profile").value,
      since_match: $("since").value,
    };
    await api("player", player);
    state.selected = Number(player.profile_id);
    state.match = null;
    $("player-dialog").close();
    await refresh();
    await loadReport();
  } catch (error) {
    $("form-error").textContent = error.message;
  }
});
$("remove").addEventListener(
  "click",
  attempt(async () => {
    await api("remove", { profile_id: state.selected });
    $("player-dialog").close();
    state.match = null;
    await refresh();
    await loadReport();
    notify(
      "Player removed from the watchlist. Existing recordings and reports are kept.",
    );
  }),
);
async function startJob(action) {
  await api("job", {
    action,
    profile_id: state.selected,
    pages: $("pages").value,
    offline: $("offline").checked,
  });
  $("task-log").open = true;
  await refresh();
}
$("fetch").addEventListener(
  "click",
  attempt(() => startJob("fetch")),
);
$("extract").addEventListener(
  "click",
  attempt(() => startJob("extract")),
);
$("check-all").addEventListener(
  "click",
  attempt(() => startJob("daily")),
);
$("cancel").addEventListener(
  "click",
  attempt(async () => {
    await api("cancel", {});
    await refresh();
  }),
);
$("quit").addEventListener(
  "click",
  attempt(async () => {
    await api("quit", {});
    stopped = true;
    document
      .querySelector("main")
      .replaceChildren(
        element(
          "p",
          "AOE2 Chat Investigator has stopped. You can close this browser tab.",
          "empty",
        ),
      );
    $("status").textContent = "Stopped. Your local data is saved.";
    document.querySelectorAll("button").forEach((button) => {
      button.disabled = true;
    });
  }),
);
$("search").addEventListener("input", renderMatches);
$("target-only").addEventListener("change", renderMatches);
for (const tab of ["transcripts", "summary"]) {
  $(`${tab}-tab`).addEventListener(
    "click",
    attempt(async () => {
      state.tab = tab;
      for (const other of ["transcripts", "summary"]) {
        $(other).hidden = other !== tab;
        $(`${other}-tab`).setAttribute("aria-selected", String(other === tab));
      }
      if (tab === "summary") await loadSummary();
    }),
  );
  $(`${tab}-tab`).addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "transcripts"
        : event.key === "End"
          ? "summary"
          : tab === "transcripts"
            ? "summary"
            : "transcripts";
    $(`${next}-tab`).focus();
    $(`${next}-tab`).click();
  });
}
$("import").addEventListener("click", () => $("files").click());
$("files").addEventListener(
  "change",
  attempt(async () => {
    const files = [...$("files").files];
    if (!files.length) return;
    const profile = state.selected;
    $("import").disabled = true;
    try {
      for (const file of files) {
        const url = endpoint(
          `import?profile_id=${profile}&filename=${encodeURIComponent(file.name)}`,
        );
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: file,
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
      }
      notify(
        `Imported ${files.length} replay file(s). Choose Extract local to build the transcript.`,
      );
    } finally {
      $("files").value = "";
      setBusy();
    }
  }),
);
let stopped = false;
async function poll() {
  if (stopped) return;
  try {
    await refresh();
  } catch (error) {
    notify(`Cannot reach the local application: ${error.message}`);
  }
  if (!stopped) setTimeout(poll, 1500);
}
try {
  await refresh();
  await loadReport();
  await loadSummary();
} catch (error) {
  notify(error.message);
}
setTimeout(poll, 1500);
