### Minibia-tools

`minibia-tools.html` loads its data at runtime from the `data/` folder and derives everything it displays (difficulty tiers, loot values, NPC sell-back listings, etc.) in the browser, so updating the tool is just replacing a JSON file and committing:

- `data/library.json` — the raw export of monsters, items, npcs, spells, runes and achievements. **This is the file to update** when monsters/items/npcs change; the page recomputes tiers, gold-per-kill and everything else from it on load.
- `data/monster-spawns.json` — raw spawn point clusters (`{n, x, y, c, t}` per cluster) used by the Spawn Map tab. **Update this file to add spawn locations** for new monsters; the page groups clusters by monster name and reconciles tiers with `library.json` on load.
- `data/icons.json` — item icon images (base64), keyed by item id.
- `data/map-floors.json` — spawn map floor background images (base64), keyed by floor number.

Because the page fetches these files, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
