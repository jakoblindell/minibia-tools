### Minibia-tools

`minibia-tools.html` (the World Compendium page) loads `data/derived/compendium.json` and `data/icons.json` at runtime, plus the per-floor spawn map terrain images (`data/derived/minimap-z*.png`).

#### Updating game data

1. Update the raw sources in `data/raw/`:
   - `library.json` — monsters, items, npcs, spells, runes, achievements. Exported manually (the Library page is Cloudflare-gated), so there's no fetch script for it — replace it by hand when you have a fresh export.
   - `monster-spawns.json` — spawn point clusters. Fetch a fresh copy with `python scripts/fetch-live.py` (also refreshes `npc-trades.json`, `definitions.json`, `npc-poi.json`, `constants.json` and `minimap.bin`).
   - `minimap.bin` — the client's raw minimap, used for the Spawn Map tab's terrain. Also refreshed by `fetch-live.py`.
2. Regenerate the derived data, in this order:
   ```
   python scripts/gen-minimap.py            # minimap.bin -> data/derived/minimap-z*.png + minimap.meta.json
   python scripts/build-data.py             # data/raw/*  -> data/derived/compendium.json (+ merchant.json, CHANGELOG.md)
   python scripts/gen-floor-plausibility.py # appends a floor bitmask to every spawnMap point (needs the two above)
   python scripts/gen-floor-connections.py  # detects stairs/ladders/holes and guesses which floor(s) each connects to (needs the two above)
   ```
3. Commit `data/raw/` and `data/derived/` (and the updated `CHANGELOG.md`). GitHub Pages picks it up — no other build step.

`build-data.py` also writes `data/derived/merchant.json` (for a merchant-ledger page this repo doesn't have yet) and `.js` twins of both (`window.__MINIBIA_COMPENDIUM__ = ...` etc., for loading via `<script src>` instead of `fetch()` when a page needs to work over `file://`). `data/raw/npc-trades.json` and `data/raw/definitions.json` are currently empty placeholders (`{}`) — `build-data.py` requires them to exist, but nothing here reads `merchant.json` yet.

`scripts/gen-floor-plausibility.py` (not one of the original 4 scripts — added to restore the "Hide implausible floors" toggle, which the switch to raw-cluster spawn data had silently turned into a no-op) computes, per spawn point, which of the 16 floors are plausible from the terrain alone — void detection, then a walkability classification derived from the client's `.dat` minimap-color/not-walkable data (`BLOCKING_IDX` in the script), checked over a window around the point rather than a single pixel. It appends the result as a 4th element to each `spawnMap` point (`[x, y, count, floorMask]`); a point with no confident floor falls back to plausible-everywhere rather than guessing wrong. See the script's docstring for the full algorithm.

`scripts/gen-floor-connections.py` (also not one of the original 4 - added for a hidden, opt-in "show floor connections" map tool) finds every tile the minimap draws as a stairs/ladder/hole/ropehole (a distinct flat yellow the client uses as an overlay, not a terrain color) and guesses which adjacent floor(s) each connects to, purely from the terrain: a matching marker on the floor above/below is a confirmed connection, a plain walkable-vs-void asymmetry with no marker is a weaker guess, a marker with nothing walkable on either neighbouring floor is a dead end (dropped - the decorative/blocked holes the client also draws yellow, ~6%), and anything still ambiguous is written to a separate `floorConnectionsUnknown` list instead of guessed (~1% of markers, in this snapshot). The World Compendium page can step through that unknown list and let a human call each one by eye - see "Hidden map tools" below - and export the answers as JSON; drop that file at `data/raw/floor-connection-labels.json` and rerun this script to fold them in as confirmed, overriding the algorithm. See the script's docstring for the full method.

#### Hidden map tools

Four opt-in tools on the Spawn Map tab are hidden behind `#stairs-beta` in the URL (e.g. `minibia-tools.html#stairs-beta`) while still being verified against the real map - nothing changes for a normal visit without it:

- **Show floor connections** (checkbox) - draws `floorConnections` on the current floor and lets you click a marker to jump to whichever floor it resolves to; ambiguous ones (connects both up and down) don't jump, since there's nothing to disambiguate which one you meant.
- **Find path** (button) - click a start point, then an end point (switch floors in between if needed), and it draws a walking route. Walkability is decoded in the browser from the same terrain PNGs the map draws (1 bit per tile per floor), blocked by the same color table as the floor-plausibility filter, and floors only connect through `floorConnections` stairs/ladders/holes - never by walking over unwalkable tiles. The search is Jump Point Search A* in a Web Worker: the first use spends a few seconds decoding all 16 floors, then routes typically take milliseconds. It can't know about boats, teleports, doors drawn as walls, or tiles the color table misjudges, so "no route" between islands is expected.
- **Draw route** (button) - click out waypoints (switching floors between clicks as needed); each leg between two points follows the pathfinder's walking route, or a dashed straight line if it can't find one. Add a title, a note per point, and optionally loop back to the start. The whole route is packed into the URL (`#route=...`, base64 JSON - no server or storage), so "Copy share link" gives a link anyone can open: viewing a shared route is public and doesn't need `#stairs-beta`, only drawing does. Titles and notes from a link are only ever rendered as text.
- **Label unknowns** (button) - opens a small floating panel and steps through `floorConnectionsUnknown` one at a time (jumping the map to each), letting you call each Up/Down/Unknown by eye. Answers save to this browser's `localStorage` as you go (survives a reload) and "Export JSON" downloads them in the format `gen-floor-connections.py`'s manual-override loader expects.

`scripts/build-bundle.py` packages multiple tool pages (`site/index.html`, `merchant-ledger.html`, `compendium.html`, `accounts.html`) plus the minimap PNGs into a single self-contained `dist/minibia-tools.html`. It's kept here for reference but isn't wired up — this repo only has the one compendium page, served directly via GitHub Pages rather than bundled.

`data/icons.json` (item icon images, keyed by item id) isn't part of this pipeline and is updated separately.

Because the page fetches JSON at runtime, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
