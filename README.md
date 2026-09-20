### Minibia-tools

`minibia-tools.html` loads its data at runtime from the `data/` folder and derives everything it displays (difficulty tiers, loot values, NPC sell-back listings, etc.) in the browser, so updating the tool is just replacing a JSON file and committing:

- `data/library.json` — the raw export of monsters, items, npcs, spells, runes and achievements. **This is the file to update** when monsters/items/npcs change; the page recomputes tiers, gold-per-kill and everything else from it on load.
- `data/spawn-map.json` — monster spawn point clusters used by the Spawn Map tab. Currently a static carry-over from before this data was split out; it'll be replaced by a build step from a raw `data/spawns.json` export once that's available.
- `data/icons.json` — item icon images (base64), keyed by item id.
- `data/map-floors.json` — spawn map floor background images (base64), keyed by floor number.

Because the page fetches these files, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
