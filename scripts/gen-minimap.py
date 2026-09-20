"""
Decode the client's minimap.bin into one PNG per floor for compendium.html's
spawn map.

minimap.bin format: "MMAP" + uint16 version, then repeated chunk records of
  uint16 xChunk, uint16 yChunk, uint8 z, then 128*128 bytes of palette indices
  (row-major, i = localX + localY*128). Index 0 = "no data" (transparent).
Palette = the 6x6x6 colour cube + 40 black, matching Minimap.prototype.colors
in src/rendering/minimap.js.

Each floor is cropped to its main explored cluster (chunk coords >= 240 on both
axes). A handful of far-flung chunks near the NW world corner are dropped -
including them would stretch every image to the full 32k-tile world extent for
~10 chunks of content. Writes minimap-z<z>.png for every floor that has data,
plus minimap.meta.json mapping z -> {worldOriginX, worldOriginY, imageWidth,
imageHeight}. minimap-z7.png / minimap-z7.meta.json are also kept (surface, the
default) for anything still referencing the old single-floor names.
"""
import struct, json, os
from collections import defaultdict
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "raw", "minimap.bin")
PNG_DIR = os.path.join(ROOT, "site")            # compendium.html loads minimap-z*.png from beside itself
META_DIR = os.path.join(ROOT, "data", "derived")  # generated meta sits with the other build outputs
CH = 128 * 128
DENSE_MIN_CHUNK = 240  # crop to chunk coords >= this on both axes

levels = [0x00, 0x33, 0x66, 0x99, 0xCC, 0xFF]
pal = np.zeros((256, 4), dtype=np.uint8)
for i in range(256):
    if i < 216:
        pal[i] = (levels[i // 36], levels[(i // 6) % 6], levels[i % 6], 255)
    else:
        pal[i] = (0, 0, 0, 255)
pal[0] = (0, 0, 0, 0)  # index 0 -> transparent

os.makedirs(PNG_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)

d = open(SRC, "rb").read()
assert d[:4] == b"MMAP", "bad magic"
version = struct.unpack_from("<H", d, 4)[0]
off = 6
by_z = defaultdict(list)
while off + 5 + CH <= len(d):
    xC = struct.unpack_from("<H", d, off)[0]
    yC = struct.unpack_from("<H", d, off + 2)[0]
    z = d[off + 4]
    data = d[off + 5: off + 5 + CH]
    off += 5 + CH
    by_z[z].append((xC, yC, data))

meta_all = {}
for z in sorted(by_z):
    dense = [c for c in by_z[z] if c[0] >= DENSE_MIN_CHUNK and c[1] >= DENSE_MIN_CHUNK]
    dropped = len(by_z[z]) - len(dense)
    if not dense:
        print(f"z={z}: no dense chunks, skipped")
        continue
    xs = [c[0] for c in dense]
    ys = [c[1] for c in dense]
    minXC, maxXC = min(xs), max(xs)
    minYC, maxYC = min(ys), max(ys)
    W = (maxXC - minXC + 1) * 128
    H = (maxYC - minYC + 1) * 128

    idx = np.zeros((H, W), dtype=np.uint8)
    for (xC, yC, data) in dense:
        block = np.frombuffer(data, dtype=np.uint8).reshape(128, 128)
        idx[(yC - minYC) * 128:(yC - minYC) * 128 + 128,
            (xC - minXC) * 128:(xC - minXC) * 128 + 128] = block

    out_png = os.path.join(PNG_DIR, f"minimap-z{z}.png")
    Image.fromarray(pal[idx], "RGBA").save(out_png, optimize=True)
    meta_all[z] = {
        "worldOriginX": minXC * 128,
        "worldOriginY": minYC * 128,
        "worldPixelsPerImagePixel": 1,
        "imageWidth": W,
        "imageHeight": H,
    }
    kb = os.path.getsize(out_png) / 1024
    fill = (idx != 0).mean()
    print(f"z={z:>2}: {out_png}  {W}x{H}  {kb:6.1f} KB  fill {fill:4.0%}  ({dropped} scatter chunks dropped)")

open(os.path.join(META_DIR, "minimap.meta.json"), "w").write(json.dumps(meta_all))
# keep the legacy single-floor name for the surface too
if 7 in meta_all:
    m7 = dict(meta_all[7]); m7["z"] = 7
    open(os.path.join(META_DIR, "minimap-z7.meta.json"), "w").write(json.dumps(m7))

total = sum(os.path.getsize(os.path.join(PNG_DIR, f"minimap-z{z}.png")) for z in meta_all)
print(f"\n{len(meta_all)} floors, {total/1024/1024:.1f} MB total")
print("meta -> minimap.meta.json")
