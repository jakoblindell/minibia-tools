# data/raw — files as downloaded from minibia.com

Put fresh downloads here, **unchanged and with the same file names**. Nothing
else belongs in this folder: hand-made inputs live in `data/manual/`, and
everything the site loads is generated into `data/derived/` by the scripts.

| File | Where to get it | Used for |
|---|---|---|
| `library.json` | The Library page (behind Cloudflare) - save its JSON from the browser's Network tab | Monsters, items, NPCs, spells, runes, achievements |
| `monster-spawns.json` | https://minibia.com/play/monster-spawns.json | Spawn map dots, hunting info |
| `npc-trades.json` | https://minibia.com/play/npc-trades.json | Who buys/sells what |
| `definitions.json` | https://minibia.com/play/definitions.json | Item definitions for trades |
| `npc-poi.json` | https://minibia.com/play/npc-poi.json | Not used by the pages yet |
| `minimap.bin.gz` | https://minibia.com/data/{version}/minimap.bin.gz - keep it gzipped | Map terrain, stairs, pathfinding |
| `constants.json` | https://minibia.com/data/{version}/constants.json (optional) | Not used by the pages yet |

`{version}` is the client's server version (760 at the time of writing): look
for `/data/<number>/` in the Network tab on minibia.com/play.

After uploading, regenerate `data/derived/` (see the main README, "Updating
game data").
