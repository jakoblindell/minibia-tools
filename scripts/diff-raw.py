"""
What changed in data/raw/ since the last scrape.

Compares the files in data/raw/ now with the same files at a git ref (by
default origin/main, i.e. what the live site was built from) and records:

  - which expected downloads are updated, unchanged (forgot to re-download?),
    missing, or unexpected in the folder;
  - library.json, field by field: monsters (health, experience, speed,
    armor, elements, immunities; loot per item - added, removed, chance and
    amount; attacks per name - damage min/max), items (matched by their id,
    so a rename is a rename; prices per NPC, dropped-by, stats), NPCs,
    spells, runes, achievements;
  - monster-spawns.json: spawn points per monster (names matched ignoring
    capitalisation, which drifts between exports);
  - npc-trades.json / definitions.json / npc-poi.json: counts;
  - the minimap: tiles changed per floor, how many newly explored, and the
    areas where it happened.

Writes data/derived/changes.json (the site's "Versions" page - every update
is kept, newest first; re-running on the same day replaces that day's
entry) and a Markdown copy in data/changes/<date>.md.

Run:  python scripts/diff-raw.py                 # vs origin/main
      python scripts/diff-raw.py --ref <commit>  # vs another commit/branch
      python scripts/diff-raw.py --dry-run       # print only, write nothing
"""
import argparse
import datetime
import gzip
import json
import os
import struct
import subprocess
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CHANGES_JSON = os.path.join(ROOT, "data", "derived", "changes.json")
CHANGES_MD_DIR = os.path.join(ROOT, "data", "changes")

# The downloads data/raw/ should hold (see data/raw/README.md), and whether
# the site needs them.
EXPECTED = [
    ("library.json", True),
    ("monster-spawns.json", True),
    ("npc-trades.json", True),
    ("definitions.json", True),
    ("minimap.bin.gz", True),
    ("npc-poi.json", False),
    ("constants.json", False),
]
NOT_DOWNLOADS = {"README.md"}

# library.json categories: (key, title, how entries are matched, fields
# that are lists of named sub-entries -> the key naming them).
LIBRARY = [
    ("monsters", "Monsters", ("name",), {"loot": "name", "attacks": "name"}),
    ("items", "Items", ("cid", "name"), {"sellTo": "name", "droppedBy": "name"}),  # cid is unique, sid isn't (bread/toast)
    ("npcs", "NPCs", ("name",), {"sells": "name", "buys": "name"}),
    ("spells", "Spells", ("id", "name"), {}),
    ("runes", "Runes", ("sid", "name"), {}),
    ("achievements", "Achievements", ("id", "name"), {}),
]
CH = 128 * 128
MAP_CELL = 32             # map changes are grouped on a 32x32-tile grid ...
MAP_AREAS_PER_FLOOR = 12  # ... merged into areas; the biggest few per floor are listed


def git_show(ref, path):
    try:
        return subprocess.run(["git", "show", "%s:%s" % (ref, path)], cwd=ROOT,
                              capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def old_file(ref, name):
    blob = git_show(ref, "data/raw/" + name)
    if blob is None and name == "minimap.bin.gz":  # before data/raw kept it gzipped
        raw = git_show(ref, "data/raw/minimap.bin")
        return gzip.compress(raw) if raw is not None else None
    return blob


def new_file(name):
    p = os.path.join(RAW, name)
    return open(p, "rb").read() if os.path.exists(p) else None


def as_json(blob):
    try:
        return json.loads(blob) if blob else None
    except ValueError:
        return None


def norm(s):
    return (s or "").strip().lower()


# --- field-level diff -------------------------------------------------------

def scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def diff_value(field, a, b, sublists):
    """One field's change as a dict, or None if equal. Lists of named
    entries (loot, attacks, prices...) are compared entry by entry."""
    if a == b:
        return None
    if field in sublists and (isinstance(a, list) or a is None) and (isinstance(b, list) or b is None):
        key = sublists[field]
        oa = {norm(e.get(key)): e for e in (a or []) if isinstance(e, dict)}
        nb = {norm(e.get(key)): e for e in (b or []) if isinstance(e, dict)}
        out = {"field": field,
               "added": [nb[k] for k in nb if k not in oa],
               "removed": [oa[k] for k in oa if k not in nb],
               "changed": []}
        for k in nb:
            if k in oa and oa[k] != nb[k]:
                ch = [{"field": f, "old": oa[k].get(f), "new": nb[k].get(f)}
                      for f in sorted(set(oa[k]) | set(nb[k])) if oa[k].get(f) != nb[k].get(f)]
                out["changed"].append({"name": nb[k].get(key), "changes": ch})
        return out if (out["added"] or out["removed"] or out["changed"]) else None
    if isinstance(a, list) and isinstance(b, list) and all(scalar(x) for x in a + b):
        return {"field": field, "added": [x for x in b if x not in a], "removed": [x for x in a if x not in b], "changed": []}
    if isinstance(a, dict) and isinstance(b, dict):
        ch = [{"field": f, "old": a.get(f), "new": b.get(f)} for f in sorted(set(a) | set(b)) if a.get(f) != b.get(f)]
        return {"field": field, "parts": ch}
    return {"field": field, "old": a, "new": b}


def entry_key(e, keys):
    for k in keys:
        if e.get(k) not in (None, ""):
            return "%s:%s" % (k, norm(str(e[k])))
    return json.dumps(e, sort_keys=True)


def keyed(entries, keys):
    """Entries by key; a key shared by several entries (NPCs with the same
    name in different towns) gets the entry's position added."""
    entries = [e for e in (entries or []) if isinstance(e, dict)]
    count = Counter(entry_key(e, keys) for e in entries)
    out = {}
    for e in entries:
        k = entry_key(e, keys)
        if count[k] > 1:
            k += "@" + json.dumps(e.get("position"), sort_keys=True)
        out[k] = e
    return out


def diff_category(old, new, keys, sublists):
    oi, ni = keyed(old, keys), keyed(new, keys)
    added = [ni[k] for k in ni if k not in oi]
    removed = [oi[k] for k in oi if k not in ni]
    changed = []
    for k in ni:
        a, b = oi.get(k), ni[k]
        if a is None or a == b:
            continue
        ch = [d for f in sorted(set(a) | set(b)) for d in [diff_value(f, a.get(f), b.get(f), sublists)] if d]
        changed.append({"name": b.get("name") or a.get("name"), "changes": ch})
    changed.sort(key=lambda c: norm(c["name"]))
    return len(oi), len(ni), added, removed, changed


# --- spawns ------------------------------------------------------------------

def clusters_of(v):
    return (v.get("clusters") if isinstance(v, dict) else v) or []


def spawn_counts(v, spelling):
    """monster name (library spelling) -> number of spawn points."""
    count = Counter()
    for c in clusters_of(v):
        if isinstance(c, dict) and c.get("n"):
            count[spelling.get(norm(c["n"]), c["n"])] += 1
    return count


def spawn_spellings(v):
    return {c["n"] for c in clusters_of(v) if isinstance(c, dict) and c.get("n")}


# --- minimap -----------------------------------------------------------------

def minimap_chunks(blob):
    if not blob:
        return {}
    d = gzip.decompress(blob)
    if d[:4] != b"MMAP":
        return {}
    off, out = 6, {}
    while off + 5 + CH <= len(d):
        xc, yc = struct.unpack_from("<HH", d, off)
        out[(d[off + 4], xc, yc)] = np.frombuffer(d, dtype=np.uint8, count=CH, offset=off + 5).reshape(128, 128)
        off += 5 + CH
    return out


def diff_minimap(old_blob, new_blob):
    a, b = minimap_chunks(old_blob), minimap_chunks(new_blob)
    if not a or not b:
        return None
    empty = np.zeros((128, 128), dtype=np.uint8)
    cells = {}  # z -> {(cx, cy): [changed, newly]}
    for key in set(a) | set(b):
        oa, nb = a.get(key, empty), b.get(key, empty)
        diff = oa != nb
        if not diff.any():
            continue
        z, xc, yc = key
        newly = diff & (oa == 0)
        per = cells.setdefault(z, {})
        for gy in range(0, 128, MAP_CELL):
            for gx in range(0, 128, MAP_CELL):
                c = int(diff[gy:gy + MAP_CELL, gx:gx + MAP_CELL].sum())
                if c:
                    cell = ((xc * 128 + gx) // MAP_CELL, (yc * 128 + gy) // MAP_CELL)
                    per[cell] = [c, int(newly[gy:gy + MAP_CELL, gx:gx + MAP_CELL].sum())]
    floors = []
    for z in sorted(cells):
        per = cells[z]
        # touching cells (8-neighbourhood) form one area
        seen, areas = set(), []
        for start in per:
            if start in seen:
                continue
            stack, members = [start], []
            seen.add(start)
            while stack:
                cx, cy = stack.pop()
                members.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (cx + dx, cy + dy)
                        if n in per and n not in seen:
                            seen.add(n)
                            stack.append(n)
            xs = [m[0] for m in members]
            ys = [m[1] for m in members]
            areas.append({
                "x0": min(xs) * MAP_CELL, "y0": min(ys) * MAP_CELL,
                "x1": (max(xs) + 1) * MAP_CELL - 1, "y1": (max(ys) + 1) * MAP_CELL - 1,
                "changed": sum(per[m][0] for m in members), "newly": sum(per[m][1] for m in members),
            })
        areas.sort(key=lambda r: -r["changed"])
        floors.append({"z": z, "changed": sum(v[0] for v in per.values()), "newly": sum(v[1] for v in per.values()),
                       "areaCount": len(areas), "areas": areas[:MAP_AREAS_PER_FLOOR]})
    return {"changed": sum(f["changed"] for f in floors), "newly": sum(f["newly"] for f in floors), "floors": floors}


# --- markdown ----------------------------------------------------------------

def fmt(v):
    if isinstance(v, float):
        return ("%.4f" % v).rstrip("0").rstrip(".")
    if v is None:
        return "-"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def md_change(c):
    if "old" in c or "new" in c:
        return "%s %s → %s" % (c["field"], fmt(c.get("old")), fmt(c.get("new")))
    if "parts" in c:
        return "%s: %s" % (c["field"], ", ".join("%s %s → %s" % (p["field"], fmt(p["old"]), fmt(p["new"])) for p in c["parts"]))
    bits = []
    for e in c.get("added", []):
        bits.append("+" + (e.get("name") if isinstance(e, dict) else fmt(e)))
    for e in c.get("removed", []):
        bits.append("−" + (e.get("name") if isinstance(e, dict) else fmt(e)))
    for e in c.get("changed", []):
        bits.append("%s (%s)" % (e["name"], ", ".join("%s %s → %s" % (p["field"], fmt(p["old"]), fmt(p["new"])) for p in e["changes"])))
    return "%s: %s" % (c["field"], "; ".join(bits))


def markdown(u):
    out = ["# Raw data changes - %s" % u["date"], "",
           "Compared with `%s`%s. Generated by `scripts/diff-raw.py`." % (u["comparedWith"], " (data from %s)" % u["previousDate"] if u.get("previousDate") else ""), "",
           "## Files"]
    for f in u["files"]:
        out.append("- `%s`: %s" % (f["name"], f["status"]))
    for e in u.get("unexpectedFiles", []):
        out.append("- `%s`: not a download - hand-made inputs go in `data/manual/`" % e)
    out += ["", "## Library"]
    for s in u["library"]:
        if not (s["added"] or s["removed"] or s["changed"]):
            out.append("- **%s**: no changes (%d)" % (s["title"], s["after"]))
            continue
        out.append("- **%s**: %d → %d" % (s["title"], s["before"], s["after"]))
        if s["added"]:
            out.append("  - added: %s" % ", ".join(e.get("name", "?") for e in s["added"]))
        if s["removed"]:
            out.append("  - removed: %s" % ", ".join(e.get("name", "?") for e in s["removed"]))
        for c in s["changed"]:
            out.append("  - %s: %s" % (c["name"], "; ".join(md_change(x) for x in c["changes"])))
    sp = u.get("spawns")
    out += ["", "## Monster spawns"]
    if sp:
        out.append("- %d → %d spawn points" % (sp["before"], sp["after"]))
        for r in sp["changed"]:
            out.append("  - %s: %d → %d" % (r["name"], r["before"], r["after"]))
        if sp["respelled"]:
            out.append("  - spelled differently in the export (same monster): %s" % ", ".join("%s → %s" % (r["old"], r["new"]) for r in sp["respelled"]))
    out += ["", "## Other files"]
    for o in u.get("other", []):
        out.append("- %s: %s → %s entries" % (o["title"], fmt(o["before"]), fmt(o["after"])))
    m = u.get("map")
    out += ["", "## Map"]
    if m:
        out.append("- %d tiles changed, %d newly explored" % (m["changed"], m["newly"]))
        for f in m["floors"]:
            out.append("  - z%d: %d changed (%d newly explored), %d areas; biggest: %s" % (
                f["z"], f["changed"], f["newly"], f["areaCount"],
                ", ".join("x%d-%d y%d-%d (%d)" % (a["x0"], a["x1"], a["y0"], a["y1"], a["changed"]) for a in f["areas"][:4])))
    return "\n".join(out) + "\n"


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main", help="git ref to compare against (default origin/main)")
    ap.add_argument("--dry-run", action="store_true", help="print the Markdown report only")
    args = ap.parse_args()
    prev_date = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short", args.ref, "--", "data/raw"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
    u = {"date": datetime.date.today().isoformat(), "comparedWith": args.ref, "previousDate": prev_date or None}

    files = []
    for name, needed in EXPECTED:
        old, new = old_file(args.ref, name), new_file(name)
        if new is None:
            state, kind = ("missing - the site needs it" if needed else "missing (optional)"), "missing"
        elif old is None:
            state, kind = "new", "new"
        elif old == new:
            state, kind = ("unchanged since the last scrape - not re-downloaded?" if needed else "unchanged"), "unchanged"
        else:
            state, kind = "updated", "updated"
        files.append({"name": name, "needed": needed, "status": state, "kind": kind})
    u["files"] = files
    present = set(os.listdir(RAW)) if os.path.isdir(RAW) else set()
    u["unexpectedFiles"] = sorted(present - {n for n, _ in EXPECTED} - NOT_DOWNLOADS)

    lib_o = as_json(old_file(args.ref, "library.json")) or {}
    lib_n = as_json(new_file("library.json")) or {}
    u["library"] = []
    for key, title, keys, sublists in LIBRARY:
        before, after, added, removed, changed = diff_category(lib_o.get(key), lib_n.get(key), keys, sublists)
        u["library"].append({"key": key, "title": title, "before": before, "after": after,
                             "added": added, "removed": removed, "changed": changed})

    spelling = {norm(m["name"]): m["name"] for m in (lib_n.get("monsters") or []) if m.get("name")}
    sp_o_raw, sp_n_raw = as_json(old_file(args.ref, "monster-spawns.json")), as_json(new_file("monster-spawns.json"))
    if sp_n_raw is not None:
        co, cn = spawn_counts(sp_o_raw, spelling), spawn_counts(sp_n_raw, spelling)
        old_sp, new_sp = spawn_spellings(sp_o_raw), spawn_spellings(sp_n_raw)
        respelled = sorted({(o, n) for o in old_sp for n in new_sp if o != n and norm(o) == norm(n)})
        u["spawns"] = {
            "before": sum(co.values()), "after": sum(cn.values()),
            "changed": [{"name": m, "before": co.get(m, 0), "after": cn.get(m, 0)}
                        for m in sorted(set(co) | set(cn), key=norm) if co.get(m, 0) != cn.get(m, 0)],
            "respelled": [{"old": o, "new": n} for o, n in respelled],
        }

    other = []
    for name, title in (("npc-trades.json", "NPC trades"), ("definitions.json", "Item definitions"), ("npc-poi.json", "NPC points of interest")):
        a, b = as_json(old_file(args.ref, name)), as_json(new_file(name))
        if b is not None:
            other.append({"title": title, "before": len(a) if a is not None else None, "after": len(b)})
    u["other"] = other
    u["map"] = diff_minimap(old_file(args.ref, "minimap.bin.gz"), new_file("minimap.bin.gz"))

    text = markdown(u)
    print(text)
    if args.dry_run:
        return
    os.makedirs(CHANGES_MD_DIR, exist_ok=True)
    with open(os.path.join(CHANGES_MD_DIR, u["date"] + ".md"), "w", encoding="utf-8") as f:
        f.write(text)
    hist = {"updates": []}
    if os.path.exists(CHANGES_JSON):
        with open(CHANGES_JSON, encoding="utf-8") as f:
            hist = json.load(f)
    hist["updates"] = [u] + [h for h in hist.get("updates", []) if h.get("date") != u["date"]]
    with open(CHANGES_JSON, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
    print("written: data/derived/changes.json, data/changes/%s.md" % u["date"])


if __name__ == "__main__":
    main()
