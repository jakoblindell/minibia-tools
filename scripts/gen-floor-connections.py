"""
Detect stairs/ladders/holes/ropeholes on the minimap and, for each one, guess
which direction(s) it connects - up a floor, down a floor, or both - purely
from the terrain images. Writes the result into data/derived/compendium.json
as a new top-level "floorConnections" map, for an experimental "show floor
connections" map toggle.

The client's minimap draws every one of these tile types as a flat bright
yellow (255,255,0) regardless of what's underneath - a distinct overlay
color, not part of the normal terrain palette. That marker is easy to find,
but it doesn't say which way it goes, so direction is inferred by looking at
the same spot (+/- a couple tiles, since a staircase often lands a tile or
two off from where it starts) on the floor above and below:

  1. Confirmed - the adjacent floor also has a yellow marker nearby. Two
     stacked markers is strong evidence of a real connection; if both floors
     around this one qualify, the tile continues in both directions (a
     landing partway up/down a multi-floor staircase or tower).
  2. Guessed - neither adjacent floor has a yellow marker nearby, but
     exactly one side has plain walkable ground there and the other doesn't
     (void/unexplored or blocked terrain). Weaker evidence - there's no
     paired marker, just an asymmetry - so this is flagged as lower
     confidence rather than mixed in with confirmed connections.
  3. Dead end - neither adjacent floor has a marker or any walkable ground
     nearby (only void, water, walls...). There's nothing to arrive on, so
     it can't lead anywhere - the decorative/blocked holes the real client
     also draws in yellow. Dropped, not queued for labeling.
  4. Unknown - both adjacent floors have walkable ground nearby but no
     marker on either, so the terrain can't tell which way it goes. About
     1% of markers land here (another ~6% are dead ends). They're written
     to a separate "floorConnectionsUnknown" list instead of guessed, for a
     hidden map tool that lets a human step through them one at a time and
     label each up/down/unknown, then export a JSON of those answers to
     fold back into this script as a manual override (load_manual_labels).

Validated against this snapshot: of ~34,700 yellow markers, 93% resolve to
a confirmed or guessed direction with this method (radius 2, see RADIUS).

Doors: the minimap draws doors in the same color as the wall around them,
so a house is a sealed box as far as the terrain can tell. The script also
writes data/derived/door-candidates.json: every 1-tile-thick building wall
tile (grey stone or red wall color) with walkable ground on two opposite
sides *that aren't otherwise connected on that floor*. The pathfinder may
step through those as assumed doors (at a small extra cost). Because a
crossing must join two separate walkable areas, a route can never use it
to cut through a wall it could have walked around.

Run:  python scripts/gen-floor-connections.py   (after gen-minimap.py and
      build-data.py - loads their output and rewrites compendium.json/.js
      in place, adding the floorConnections key, and writes
      door-candidates.json. scipy speeds up the door step if installed.)
"""
import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
RAW = os.path.join(ROOT, "data", "raw")
LABELS_PATH = os.path.join(RAW, "floor-connection-labels.json")

YELLOW_RGB = (255, 255, 0)
# Same table gen-floor-plausibility.py uses - see that script for how it was derived.
BLOCKING_IDX = {0, 12, 40, 86, 114, 186, 192}
RADIUS = 2

# Bit flags packed into each connection point's 3rd array element.
UP = 1
DOWN = 2
GUESSED = 4
DEAD_END = -1  # classify() sentinel, never written out


def idx_to_rgb(idx):
    steps = [0, 51, 102, 153, 204, 255]
    return (steps[(idx // 36) % 6], steps[(idx // 6) % 6], steps[idx % 6])


BLOCKING_RGB = {idx_to_rgb(i) for i in BLOCKING_IDX}
DOOR_WALL_RGB = {idx_to_rgb(86), idx_to_rgb(186)}  # grey stone wall, red wall


def label_components(walk):
    """4-connected components of a boolean grid. 4-connectivity matches the
    pathfinder, which never cuts a diagonal corner past a blocked tile."""
    try:
        from scipy import ndimage
        lab, _ = ndimage.label(walk)
        return lab
    except ImportError:
        pass
    from collections import deque
    H, W = walk.shape
    lab = np.zeros((H, W), dtype=np.int32)
    ys, xs = np.nonzero(walk)
    n = 0
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if lab[sy, sx]:
            continue
        n += 1
        lab[sy, sx] = n
        q = deque([(sy, sx)])
        while q:
            y, x = q.popleft()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < H and 0 <= nx < W and walk[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n
                    q.append((ny, nx))
    return lab


def door_candidates(arr, m):
    """Flat [x, y, orient, ...] (orient 0 = passes west<->east, 1 = north<->
    south) for 1-thick wall tiles joining two different walkable areas."""
    opaque = arr[:, :, 3] > 0
    rgb = arr[:, :, :3]
    blocking = np.zeros(opaque.shape, dtype=bool)
    for c in BLOCKING_RGB:
        blocking |= (rgb[:, :, 0] == c[0]) & (rgb[:, :, 1] == c[1]) & (rgb[:, :, 2] == c[2])
    wall = np.zeros(opaque.shape, dtype=bool)
    for c in DOOR_WALL_RGB:
        wall |= (rgb[:, :, 0] == c[0]) & (rgb[:, :, 1] == c[1]) & (rgb[:, :, 2] == c[2])
    lab = np.pad(label_components(opaque & ~blocking), 1)
    wall &= opaque
    lw, le, ln, ls = lab[1:-1, :-2], lab[1:-1, 2:], lab[:-2, 1:-1], lab[2:, 1:-1]
    horiz = wall & (lw > 0) & (le > 0) & (lw != le)
    vert = wall & (ln > 0) & (ls > 0) & (ln != ls) & ~horiz
    out = []
    ox, oy = m["worldOriginX"], m["worldOriginY"]
    for orient, mask in ((0, horiz), (1, vert)):
        ys, xs = np.nonzero(mask)
        for x, y in zip((xs + ox).tolist(), (ys + oy).tolist()):
            out.extend((x, y, orient))
    return out


def load_floors(minimap_meta):
    floors = {}
    for z_str, m in minimap_meta.items():
        path = os.path.join(DERIVED, "minimap-z%s.png" % z_str)
        if not os.path.exists(path):
            continue
        arr = np.array(Image.open(path).convert("RGBA"))
        floors[int(z_str)] = (arr, m)
    return floors


def yellow_points(arr, m):
    opaque = arr[:, :, 3] > 0
    is_yellow = (arr[:, :, 0] == YELLOW_RGB[0]) & (arr[:, :, 1] == YELLOW_RGB[1]) & (arr[:, :, 2] == YELLOW_RGB[2])
    ys, xs = np.where(is_yellow & opaque)
    ox, oy = m["worldOriginX"], m["worldOriginY"]
    return set(zip((xs + ox).tolist(), (ys + oy).tolist()))


def has_yellow_nearby(yellow_sets, z, wx, wy, radius):
    pts = yellow_sets.get(z)
    if not pts:
        return False
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if (wx + dx, wy + dy) in pts:
                return True
    return False


def terrain_state(floors, z, wx, wy, radius):
    """'walkable' / 'blocked' (explored, not walkable) / 'void' (nothing explored nearby)."""
    if z not in floors:
        return "void"
    arr, m = floors[z]
    ox, oy = m["worldOriginX"], m["worldOriginY"]
    any_opaque = False
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            px, py = wx + dx - ox, wy + dy - oy
            if 0 <= px < m["imageWidth"] and 0 <= py < m["imageHeight"]:
                r, g, b, a = arr[py, px]
                if a > 0:
                    any_opaque = True
                    if (r, g, b) not in BLOCKING_RGB:
                        return "walkable"
    return "blocked" if any_opaque else "void"


def load_manual_labels():
    """Optional data/raw/floor-connection-labels.json - the JSON exported by
    the hidden "Label unknowns" map tool once a human has stepped through
    the unresolved markers. A flat list of {"x":,"y":,"z":,"dir":"up"|
    "down"|"both"}; missing/absent entries are left as unknown, same as
    if this file didn't exist."""
    if not os.path.exists(LABELS_PATH):
        return {}
    with open(LABELS_PATH, encoding="utf-8") as f:
        rows = json.load(f)
    dir_flags = {"up": UP, "down": DOWN, "both": UP | DOWN}
    out = {}
    for r in rows:
        flags = dir_flags.get(r.get("dir"))
        if flags is not None:
            out[(int(r["z"]), int(r["x"]), int(r["y"]))] = flags
    return out


def classify(floors, yellow_sets, z, wx, wy, manual_labels):
    manual = manual_labels.get((z, wx, wy))
    if manual is not None:
        return manual

    up_yellow = has_yellow_nearby(yellow_sets, z - 1, wx, wy, RADIUS)
    down_yellow = has_yellow_nearby(yellow_sets, z + 1, wx, wy, RADIUS)
    if up_yellow or down_yellow:
        flags = 0
        if up_yellow:
            flags |= UP
        if down_yellow:
            flags |= DOWN
        return flags

    up_state = terrain_state(floors, z - 1, wx, wy, RADIUS)
    down_state = terrain_state(floors, z + 1, wx, wy, RADIUS)
    if up_state == "walkable" and down_state != "walkable":
        return UP | GUESSED
    if down_state == "walkable" and up_state != "walkable":
        return DOWN | GUESSED
    if up_state != "walkable" and down_state != "walkable":
        return DEAD_END  # nothing to land on either way
    return None  # unknown - walkable both ways, no marker to break the tie


def main():
    comp_path = os.path.join(DERIVED, "compendium.json")
    with open(comp_path, encoding="utf-8") as f:
        comp = json.load(f)

    minimap_meta = comp.get("minimapMeta")
    if not minimap_meta:
        raise SystemExit("compendium.json has no minimapMeta - run build-data.py after gen-minimap.py first")

    floors = load_floors(minimap_meta)
    if not floors:
        raise SystemExit("no data/derived/minimap-z*.png found - run gen-minimap.py first")

    yellow_sets = {z: yellow_points(arr, m) for z, (arr, m) in floors.items()}
    manual_labels = load_manual_labels()

    connections = {}
    unknowns = {}
    n_total = n_confirmed = n_guessed = n_manual = n_dead = n_unknown = 0
    for z, pts in yellow_sets.items():
        rows = []
        unk_rows = []
        for (wx, wy) in pts:
            n_total += 1
            is_manual = (z, wx, wy) in manual_labels
            flags = classify(floors, yellow_sets, z, wx, wy, manual_labels)
            if flags == DEAD_END:
                n_dead += 1
                continue
            if flags is None:
                n_unknown += 1
                unk_rows.append([wx, wy])
                continue
            if is_manual:
                n_manual += 1
            elif flags & GUESSED:
                n_guessed += 1
            else:
                n_confirmed += 1
            rows.append([wx, wy, flags])
        if rows:
            connections[str(z)] = rows
        if unk_rows:
            unknowns[str(z)] = unk_rows

    comp["floorConnections"] = connections
    comp["floorConnectionsUnknown"] = unknowns

    def dump(obj, stem, global_name):
        blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(DERIVED, stem + ".json"), "w", encoding="utf-8") as f:
            f.write(blob)
        with open(os.path.join(DERIVED, stem + ".js"), "w", encoding="utf-8") as f:
            f.write("window.%s=%s;\n" % (global_name, blob))

    dump(comp, "compendium", "__MINIBIA_COMPENDIUM__")

    doors = {str(z): door_candidates(arr, m) for z, (arr, m) in floors.items()}
    doors = {z: v for z, v in doors.items() if v}
    with open(os.path.join(DERIVED, "door-candidates.json"), "w", encoding="utf-8") as f:
        json.dump(doors, f, separators=(",", ":"))
    n_doors = sum(len(v) // 3 for v in doors.values())

    print("floor connections: %d yellow markers found, %d confirmed, %d guessed, %d manually labeled, "
          "%d dead ends (dropped), %d still unresolved"
          % (n_total, n_confirmed, n_guessed, n_manual, n_dead, n_unknown))
    print("door candidates: %d (written to door-candidates.json)" % n_doors)


if __name__ == "__main__":
    main()
