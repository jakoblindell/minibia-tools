### Minibia-tools

`minibia-tools.html` (the World Compendium page) loads `data/derived/compendium.json` and `data/icons.json` at runtime, plus the per-floor spawn map terrain images (`data/derived/minimap-z*.png`).

#### Updating game data

1. Update the raw sources in `data/raw/`:
   - `library.json` — monsters, items, npcs, spells, runes, achievements. Exported manually (the Library page is Cloudflare-gated), so there's no fetch script for it — replace it by hand when you have a fresh export.
   - `monster-spawns.json` — spawn point clusters. Fetch a fresh copy with `python scripts/fetch-live.py` (also refreshes `npc-trades.json`, `definitions.json`, `npc-poi.json`, `constants.json` and `minimap.bin`).
   - `minimap.bin` — the client's raw minimap, used for the Spawn Map tab's terrain. Also refreshed by `fetch-live.py`.
2. Regenerate the derived data:
   ```
   python scripts/gen-minimap.py   # minimap.bin -> data/derived/minimap-z*.png + minimap.meta.json
   python scripts/build-data.py    # data/raw/*  -> data/derived/compendium.json (+ merchant.json, CHANGELOG.md)
   ```
3. Commit `data/raw/` and `data/derived/` (and the updated `CHANGELOG.md`). GitHub Pages picks it up — no other build step.

`build-data.py` also writes `data/derived/merchant.json` (for a merchant-ledger page this repo doesn't have yet) and `.js` twins of both (`window.__MINIBIA_COMPENDIUM__ = ...` etc., for loading via `<script src>` instead of `fetch()` when a page needs to work over `file://`). `data/raw/npc-trades.json` and `data/raw/definitions.json` are currently empty placeholders (`{}`) — `build-data.py` requires them to exist, but nothing here reads `merchant.json` yet.

`scripts/build-bundle.py` packages multiple tool pages (`site/index.html`, `merchant-ledger.html`, `compendium.html`, `accounts.html`) plus the minimap PNGs into a single self-contained `dist/minibia-tools.html`. It's kept here for reference but isn't wired up — this repo only has the one compendium page, served directly via GitHub Pages rather than bundled.

`data/icons.json` (item icon images, keyed by item id) isn't part of this pipeline and is updated separately.

Because the page fetches JSON at runtime, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
