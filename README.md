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
   ```
3. Commit `data/raw/` and `data/derived/` (and the updated `CHANGELOG.md`). GitHub Pages picks it up — no other build step.

`build-data.py` also writes `data/derived/merchant.json` (for a merchant-ledger page this repo doesn't have yet) and `.js` twins of both (`window.__MINIBIA_COMPENDIUM__ = ...` etc., for loading via `<script src>` instead of `fetch()` when a page needs to work over `file://`). `data/raw/npc-trades.json` and `data/raw/definitions.json` are currently empty placeholders (`{}`) — `build-data.py` requires them to exist, but nothing here reads `merchant.json` yet.

`scripts/gen-floor-plausibility.py` (not one of the original 4 scripts — added to restore the "Hide implausible floors" toggle, which the switch to raw-cluster spawn data had silently turned into a no-op) computes, per spawn point, which of the 16 floors are plausible from the terrain alone — void detection, then a walkability classification derived from the client's `.dat` minimap-color/not-walkable data (`BLOCKING_IDX` in the script), checked over a window around the point rather than a single pixel. It appends the result as a 4th element to each `spawnMap` point (`[x, y, count, floorMask]`); a point with no confident floor falls back to plausible-everywhere rather than guessing wrong. See the script's docstring for the full algorithm.

`scripts/build-bundle.py` packages multiple tool pages (`site/index.html`, `merchant-ledger.html`, `compendium.html`, `accounts.html`) plus the minimap PNGs into a single self-contained `dist/minibia-tools.html`. It's kept here for reference but isn't wired up — this repo only has the one compendium page, served directly via GitHub Pages rather than bundled.

`data/icons.json` (item icon images, keyed by item id) isn't part of this pipeline and is updated separately.

Because the page fetches JSON at runtime, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
