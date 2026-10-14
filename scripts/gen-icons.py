"""
Item icons (data/icons.json) from the game client's sprite files.

The client files are too big for the repo (Minibia.spr is ~50MB), so they're
passed in from wherever they live:

  python scripts/gen-icons.py --spr path/Minibia.spr --patch path/Minibia.patch.spr \
      --dat path/Minibia.dat [--virtual-items path/virtual-items.js] [--all]

Where to get them (SERVER_VERSION is 760 at the time of writing, see fetch-live.py):
  Minibia.spr / Minibia.patch.spr / Minibia.dat
      https://minibia.com/data/760/<name>?v=<SPR_VERSION / SPR_PATCH_VERSION / DAT_VERSION>
      (the versions are constants in the client's src/core/index.js), or the
      browser's IndexedDB cache after playing.
  virtual-items.js
      https://minibia.com/b/<build>/src/data/virtual-items.js - only needed for
      items whose library `sid` is a client-side recolor (30000-30999).

Mapping: library.json item `sid` is the .dat object id (the client id the
sprites hang off); icons.json is keyed by the item's `cid` (the server id the
page looks icons up by). An icon is the object's first frame, pattern 0, layer
0, composed from its WxH tiles at native size (32x32, or e.g. 64x32 for a
2x1 item - the page scales them).

By default only items that have no icon yet are added; existing icons are kept
byte-for-byte. --all re-renders every item from the files.

Sprite files: u32 signature, u16 count (u32 with --extended, not used here),
then a u32 offset per sprite (0 = empty). Each sprite: 3 bytes transparent
colour, u16 data size, then runs of u16 transparent pixels, u16 coloured pixels,
RGB per coloured pixel. The patch file has the same format; patch-local id i is
global sprite id (base count + i).
"""
import argparse, base64, io, json, os, re, struct, sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(ROOT, "data", "raw", "library.json")
ICONS = os.path.join(ROOT, "data", "icons.json")

DAT_SIGNATURE_760 = 0x439D5A33


class SpriteFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        self.count = struct.unpack_from("<H", self.data, 4)[0]
        self.offsets = struct.unpack_from("<%dI" % self.count, self.data, 6)

    def image(self, local_id):
        """RGBA 32x32 for a 1-based id within this file, or None if empty."""
        if local_id < 1 or local_id > self.count:
            return None
        off = self.offsets[local_id - 1]
        if off == 0:
            return None
        size = struct.unpack_from("<H", self.data, off + 3)[0]
        p, end = off + 5, off + 5 + size
        px = bytearray(32 * 32 * 4)
        i = 0
        while p < end and i < 1024:
            transparent, coloured = struct.unpack_from("<HH", self.data, p)
            p += 4
            i += transparent
            for _ in range(coloured):
                if i >= 1024:
                    break
                px[i * 4:i * 4 + 3] = self.data[p:p + 3]
                px[i * 4 + 3] = 255
                p += 3
                i += 1
        return Image.frombytes("RGBA", (32, 32), bytes(px))


class Sprites:
    def __init__(self, spr_path, patch_path):
        self.base = SpriteFile(spr_path)
        self.patch = SpriteFile(patch_path) if patch_path else None

    def image(self, sprite_id):
        if sprite_id <= self.base.count:
            return self.base.image(sprite_id)
        if self.patch:
            return self.patch.image(sprite_id - self.base.count)
        return None


# Flags with a payload, numbered as in the client's ObjectBuffer.attributes
# (otclient's ThingAttr; 760 reads them unmapped): Ground, Writable,
# WritableOnce, Elevation, MinimapColor, LensHelp, Cloth, Usable take a u16;
# Light and Displacement two u16s; Market 6 bytes + u16-length string + 4 bytes.
# Everything else the client knows is bare.
U16_FLAGS = {0, 8, 9, 25, 28, 29, 32, 34}
U32_FLAGS = {21, 24}
MARKET_FLAG = 33
BARE_FLAGS = set(range(38)) | {100, 101, 252, 253, 254}


def read_dat_items(path):
    """{object id: (width, height, layers, px, py, pz, frames, [sprite ids])} for items."""
    with open(path, "rb") as f:
        d = f.read()
    sig, items = struct.unpack_from("<IH", d, 0)
    if sig != DAT_SIGNATURE_760:
        sys.exit("Unexpected .dat signature %08X (this reads the 7.60 layout, %08X)" % (sig, DAT_SIGNATURE_760))
    p = 12
    out = {}
    for oid in range(100, items + 1):
        while True:
            flag = d[p]
            p += 1
            if flag == 0xFF:
                break
            if flag in U16_FLAGS:
                p += 2
            elif flag in U32_FLAGS:
                p += 4
            elif flag == MARKET_FLAG:
                p += 6
                p += 2 + struct.unpack_from("<H", d, p)[0]
                p += 4
            elif flag not in BARE_FLAGS:
                sys.exit("Unknown .dat flag %d on object %d" % (flag, oid))
        w, h = d[p], d[p + 1]
        p += 2
        if w > 1 or h > 1:
            p += 1  # exact size
        layers, px, py, pz, frames = d[p:p + 5]
        p += 5
        n = w * h * layers * px * py * pz * frames
        sprites = struct.unpack_from("<%dH" % n, d, p)
        p += 2 * n
        out[oid] = (w, h, layers, px, py, pz, frames, sprites)
    return out


def read_virtual_maps(path):
    """{virtual id: (base id, {(r,g,b): (r,g,b)})} for the exact-colour-map recipes."""
    if not path:
        return {}
    src = open(path, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r"^\s*(\d+):\s*\{\s*base:\s*(\d+),\s*map:\s*(\{[^}]*\})", src, re.M):
        cmap = {}
        for k, v in json.loads(m.group(3)).items():
            cmap[tuple(bytes.fromhex(k[1:]))] = tuple(bytes.fromhex(v[1:]))
        out[int(m.group(1))] = (int(m.group(2)), cmap)
    return out


def render(obj, sprites):
    w, h, layers, px, py, pz, frames, ids = obj
    img = Image.new("RGBA", (w * 32, h * 32), (0, 0, 0, 0))
    # Sprite index order: frame, z, y, x pattern, layer, height, width. First
    # frame/pattern/layer -> the first w*h ids; tiles draw up and to the left.
    for ty in range(h):
        for tx in range(w):
            tile = sprites.image(ids[ty * w + tx])
            if tile:
                img.alpha_composite(tile, ((w - 1 - tx) * 32, (h - 1 - ty) * 32))
    return img


def recolor(img, cmap):
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a and (r, g, b) in cmap:
                px[x, y] = cmap[(r, g, b)] + (a,)
    return img


def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--spr", required=True)
    ap.add_argument("--patch")
    ap.add_argument("--dat", required=True)
    ap.add_argument("--virtual-items")
    ap.add_argument("--all", action="store_true", help="re-render every item, not just missing ones")
    ap.add_argument("--dump", help="also write each new icon as <dir>/<cid>.png for eyeballing")
    a = ap.parse_args()

    sprites = Sprites(a.spr, a.patch)
    dat = read_dat_items(a.dat)
    virtual = read_virtual_maps(a.virtual_items)
    items = json.load(open(LIBRARY, encoding="utf-8"))["items"]
    icons = json.load(open(ICONS, encoding="utf-8"))
    if a.dump:
        os.makedirs(a.dump, exist_ok=True)

    added, skipped = [], []
    for it in items:
        key = str(it["cid"])
        if key in icons and not a.all:
            continue
        sid, cmap = it["sid"], None
        if sid in virtual:
            sid, cmap = virtual[sid]
        if sid not in dat:
            skipped.append("%s (sid %s: not in .dat%s)" % (it["name"], it["sid"],
                           "" if a.virtual_items or it["sid"] < 30000 else ", pass --virtual-items"))
            continue
        img = render(dat[sid], sprites)
        if cmap:
            img = recolor(img, cmap)
        if not img.getbbox():
            skipped.append("%s (sid %s: blank sprite)" % (it["name"], it["sid"]))
            continue
        if key not in icons:
            added.append(it["name"])
        icons[key] = png_b64(img)
        if a.dump:
            img.save(os.path.join(a.dump, "%s.png" % key))

    with open(ICONS, "w", encoding="utf-8") as f:
        json.dump(icons, f, separators=(",", ":"))
    print("%d icons (%d new)" % (len(icons), len(added)))
    for n in added:
        print("  + " + n)
    for s in skipped:
        print("  ! skipped " + s)


if __name__ == "__main__":
    main()
