# GUI design

The primary reference is the supplied AOE2 Counter App. Its theme sources are
`memory-game-app/src/theme/colors.js`, `typography.js` and `PaperBackground.js`.
The implementation reuses its parchment texture and licensed local fonts.

`gui-concept.png` is the complete primary-screen concept generated with the
built-in Image Gen tool. The brief specified a local replay/chat workspace,
watchlist, match list, attributed transcript, daily summary, search, target
filter, import, extraction, export and shutdown. All controls and transcript
content are native HTML; the concept is a design reference, never the UI itself.

| Design token | Value / treatment |
|---|---|
| Parchment | `#e1c18f` with the reference app's 512px tiled texture |
| Ink | `#2c1b0c`; muted `#54391f` |
| Walnut | `#2b1c10`; button banner `#3b2616` |
| Brass | `#8a6a3c`; highlight `#b8935c` |
| Cream on walnut | `#f3e6c4` |
| Headings | Cinzel 600; player name Alegreya 700 |
| Reading text | Alegreya 400 / 700, lining numerals |
| Frames | 1px brass or bevel, 2–3px corners |
| Composition | Watchlist rail; workspace tabs; match list and transcript |
| Responsive | At 760px the rail and match list stack above the transcript |

The concept's decorative game logo and native window controls are omitted
because this is a browser-based local application. The functional additions are
Edit player, match count, target-line margin markers, extraction options,
local storage path, task log, cancellation, empty states and player dialog.
The target-only checkbox defaults off to preserve context. The search icon,
folder, download, document, CSV grid and row chevrons use code-native SVGs.
Data replaces all fictional concept names and match details at runtime.

The implementation deliberately stays with standard-library Python and static
HTML/CSS/JavaScript, matching the repository's dependency-free runtime. No
frontend build or Node installation is required to run it. Files are separated
into the server, worker launcher, UI shell, styling and interaction controller.
