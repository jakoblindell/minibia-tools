"""
Deduce which floor our spawn clusters are on from a real-Tibia spawn export,
and write data/derived/known-floors.json for the World Compendium's "Real-
Tibia floors" map toggle.

Minibia's spawns (spawnMap points [x, y, count, floorMask]) carry no floor;
gen-floor-plausibility.py only narrows each to the floors its terrain allows.
Minibia's world is largely the real Tibia map, so a real-Tibia monster
database export pins most clusters down: a cluster with real spawns of the
same monster within RADIUS tiles (Chebyshev) takes their floor(s) - only
floors the terrain mask already allows, keeping those within +2 tiles of the
nearest. Monsters are matched by name (case/punctuation-insensitive, plus
ALIASES for the few Minibia renames); clusters with no real spawn nearby
(Minibia-only areas) are simply left out.

Input: the export as JSON - anything containing {"monster": {"name"},
"spots": [{"spawns": [{"x", "y", "z"}]}]} blocks (a list of them, one, or
nested). It isn't kept in the repo; only the small result is:

  {"radius": 8, "monsters": {"<our name>": [[x, y, floorMask], ...]}}

Run:  python scripts/gen-known-floors.py path/to/export.json
      (after gen-floor-plausibility.py - it reads compendium.json's masks)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
RADIUS = 8
# Minibia name -> real-Tibia name, where they differ.
ALIASES = {
    "beholder": "bonelord",
    "elder beholder": "elder bonelord",
    "blue butterfly": "butterfly blue",
    "red butterfly": "butterfly red",
    "yellow butterfly": "butterfly",
}


def norm(name):
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def find_entries(root):
    out, stack = [], [root]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            mon = node.get("monster")
            if isinstance(mon, dict) and isinstance(mon.get("name"), str) and isinstance(node.get("spots"), list):
                out.append(node)
            else:
                stack.extend(v for v in node.values() if isinstance(v, (list, dict)))
    return out


def tibia_spawns(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    spawns = {}
    for e in find_entries(data):
        lst = spawns.setdefault(norm(e["monster"]["name"]), [])
        for spot in e["spots"]:
            for s in (spot or {}).get("spawns") or []:
                if all(isinstance(s.get(k), int) for k in ("x", "y", "z")) and 0 <= s["z"] <= 15:
                    lst.append((s["x"], s["y"], s["z"]))
    return {k: v for k, v in spawns.items() if v}


def known_mask(x, y, terrain, grid):
    best = {}
    for gx in range((x - RADIUS) >> 4, ((x + RADIUS) >> 4) + 1):
        for gy in range((y - RADIUS) >> 4, ((y + RADIUS) >> 4) + 1):
            for tx, ty, tz in grid.get((gx, gy), ()):
                d = max(abs(tx - x), abs(ty - y))
                if d <= RADIUS and d < best.get(tz, RADIUS + 1):
                    best[tz] = d
    allowed = {z: d for z, d in best.items() if terrain is None or terrain & 0xFFFF == 0xFFFF or (terrain >> z) & 1}
    if not allowed:
        return 0
    dmin = min(allowed.values())
    mask = 0
    for z, d in allowed.items():
        if d <= dmin + 2:
            mask |= 1 << z
    return mask


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    tibia = tibia_spawns(sys.argv[1])
    with open(os.path.join(DERIVED, "compendium.json"), encoding="utf-8") as f:
        comp = json.load(f)

    out = {}
    n_mon = n_pts = n_known = n_single = 0
    for mo in comp["spawnMap"]["monsters"]:
        key = norm(mo["name"])
        pts = tibia.get(ALIASES.get(key, key))
        if not pts:
            continue
        n_mon += 1
        grid = {}
        for t in pts:
            grid.setdefault((t[0] >> 4, t[1] >> 4), []).append(t)
        rows = []
        for p in mo["points"]:
            n_pts += 1
            mask = known_mask(p[0], p[1], p[3] if len(p) > 3 else None, grid)
            if mask:
                rows.append([p[0], p[1], mask])
                n_single += (mask & (mask - 1)) == 0
        if rows:
            out[mo["name"]] = rows
            n_known += len(rows)

    with open(os.path.join(DERIVED, "known-floors.json"), "w", encoding="utf-8") as f:
        json.dump({"radius": RADIUS, "monsters": out}, f, separators=(",", ":"))
    print("known floors: %d of our monsters have real-Tibia spawn data; %d of their %d spawn clusters got a known floor "
          "(%d single-floor), written to known-floors.json" % (n_mon, n_known, n_pts, n_single))


if __name__ == "__main__":
    main()
