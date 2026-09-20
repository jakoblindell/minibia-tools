### Minibia-tools

`minibia-tools.html` loads its data at runtime from the `data/` folder:

- `data/game-data.json` — monsters, items, NPCs, spells, runes, achievements and the spawn map. This is the file to edit when adding or updating game data.
- `data/icons.json` — item icon images (base64).
- `data/map-floors.json` — spawn map floor background images (base64).

Because the page fetches these files, it needs to be served over HTTP (e.g. GitHub Pages, or `python3 -m http.server` locally) rather than opened directly as a `file://` URL.
