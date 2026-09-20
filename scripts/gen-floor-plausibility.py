"""
Append a per-floor plausibility bitmask to every spawn point in
data/derived/compendium.json, so the World Compendium's "Hide implausible
floors" toggle has something to filter on.

Spawn points only ever carry [x, y, count] - no floor (z). Since many dungeon
levels stack on top of each other at the same x/y, every spawn dot would
otherwise be drawn on all 16 floors regardless of where the monster actually
lives. This computes, per point, which floors are plausible from the terrain
alone and appends that as a 4th array element: [x, y, count, floorMask].

Pipeline (all offline, using data/derived/minimap-z*.png from gen-minimap.py):

  1. Void filtering - a floor's terrain PNG is transparent wherever that floor
     is unexplored. A point can't be on a floor that's still void there.
  2. Walkability - being painted isn't the same as walkable (walls/water/lava
     are drawn too). BLOCKING_IDX below is the set of minimap palette indices
     that came out >=70% "not_walkable" when cross-referenced against the
     client's .dat item flags (wall/cliff/lava/water/dense-forest/void); this
     table is a property of the game's client assets, not of any one spawn
     export, so it's a checked-in constant rather than recomputed per run.
  3. Neighborhood, not a single pixel - a spawn point is roughly the center of
     a spawn area, not a tile a creature stands on. A window around each point
     (radius scaled by spawn count) is checked for *any* walkable ground,
     rather than testing the exact recorded coordinate.
  4. Safety net - a point with zero plausible floors falls back to "plausible
     everywhere" (0xFFFF). The toggle only ever hides dots it has good
     evidence are wrong; it never invents or hides a floor on a guess.

Run:  python scripts/gen-floor-plausibility.py   (after gen-minimap.py and
      build-data.py - it loads their output and rewrites compendium.json/.js
      in place with the 4th element added to every spawn point)
"""
import base64
import io
import json
import math
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")

# Minimap palette indices measured (via the client's .dat minimap_color +
# not_walkable flags) to be blocking >=70% of the time: void, dense forest,
# water, wall, cliff, lava, lava-variant.
BLOCKING_IDX = {0, 12, 40, 86, 114, 186, 192}
WALKABLE_MIN = 5  # min walkable pixels in a point's window to count a floor as plausible


def idx_to_rgb(idx):
    steps = [0, 51, 102, 153, 204, 255]
    return (steps[(idx // 36) % 6], steps[(idx // 6) % 6], steps[idx % 6])


BLOCKING_RGB = {idx_to_rgb(i) for i in BLOCKING_IDX}


def radius_for_count(cnt):
    return int(max(6, min(20, round(math.sqrt(max(cnt, 1)) * 3))))


def load_walkable_masks(minimap_meta):
    masks = {}
    for z_str in minimap_meta:
        path = os.path.join(DERIVED, "minimap-z%s.png" % z_str)
        if not os.path.exists(path):
            continue
        arr = np.array(Image.open(path).convert("RGBA"))
        opaque = arr[:, :, 3] > 0
        is_blocking = np.zeros(arr.shape[:2], dtype=bool)
        for rgb in BLOCKING_RGB:
            is_blocking |= (arr[:, :, 0] == rgb[0]) & (arr[:, :, 1] == rgb[1]) & (arr[:, :, 2] == rgb[2])
        masks[z_str] = opaque & ~is_blocking
    return masks


def floor_mask_for_point(x, y, cnt, minimap_meta, walkable_masks):
    mask = 0
    r = radius_for_count(cnt)
    for z_str, m in minimap_meta.items():
        wm = walkable_masks.get(z_str)
        if wm is None:
            continue
        px, py = x - m["worldOriginX"], y - m["worldOriginY"]
        if not (0 <= px < m["imageWidth"] and 0 <= py < m["imageHeight"]):
            continue
        y0, y1 = max(0, py - r), min(wm.shape[0], py + r + 1)
        x0, x1 = max(0, px - r), min(wm.shape[1], px + r + 1)
        if wm[y0:y1, x0:x1].sum() >= WALKABLE_MIN:
            mask |= 1 << int(z_str)
    return mask if mask != 0 else 0xFFFF  # unknown -> plausible everywhere, never hide a real spawn


def main():
    comp_path = os.path.join(DERIVED, "compendium.json")
    with open(comp_path, encoding="utf-8") as f:
        comp = json.load(f)

    minimap_meta = comp.get("minimapMeta")
    if not minimap_meta:
        raise SystemExit("compendium.json has no minimapMeta - run build-data.py after gen-minimap.py first")

    walkable_masks = load_walkable_masks(minimap_meta)
    if not walkable_masks:
        raise SystemExit("no data/derived/minimap-z*.png found - run gen-minimap.py first")

    n_points = 0
    n_fallback = 0
    for mo in comp["spawnMap"]["monsters"]:
        new_points = []
        for p in mo["points"]:
            x, y, cnt = p[0], p[1], p[2]
            mask = floor_mask_for_point(x, y, cnt, minimap_meta, walkable_masks)
            if mask == 0xFFFF:
                n_fallback += 1
            new_points.append([x, y, cnt, mask])
            n_points += 1
        mo["points"] = new_points

    def dump(obj, stem, global_name):
        blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(DERIVED, stem + ".json"), "w", encoding="utf-8") as f:
            f.write(blob)
        with open(os.path.join(DERIVED, stem + ".js"), "w", encoding="utf-8") as f:
            f.write("window.%s=%s;\n" % (global_name, blob))

    dump(comp, "compendium", "__MINIBIA_COMPENDIUM__")

    print("floor plausibility: %d points, %d fell back to all-floors (no confident placement)"
          % (n_points, n_fallback))


if __name__ == "__main__":
    main()
