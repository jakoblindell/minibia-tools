"""
What changed in data/raw/ since the last scrape - a readable report.

Compares the files in data/raw/ now with the same files at a git ref (by
default origin/main, i.e. what the live site was built from), and writes a
Markdown report:

  - which expected downloads are updated, unchanged (forgot to re-download?),
    missing, or unexpected in the folder;
  - library.json: added/removed monsters, items, NPCs, spells, runes,
    achievements, and which fields changed on which entries;
  - monster-spawns.json: monsters whose spawn points changed;
  - npc-trades.json / definitions.json / npc-poi.json: entries added, removed,
    changed;
  - the minimap: tiles changed per floor, how many are newly explored, and
    where.

Run:  python scripts/diff-raw.py                 # vs origin/main, writes data/changes/<today>.md
      python scripts/diff-raw.py --ref <commit>  # vs another commit/branch
      python scripts/diff-raw.py --out -         # print only
"""
import argparse
import datetime
import gzip
import json
import os
import struct
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

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
CH = 128 * 128


def git_show(ref, path):
    try:
        return subprocess.run(["git", "show", "%s:%s" % (ref, path)], cwd=ROOT,
                              capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def old_file(ref, name):
    blob = git_show(ref, "data/raw/" + name)
    if blob is None and name == "minimap.bin.gz":  # before the raw folder kept it gzipped
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


def keyed(v):
    """A dict keyed by id/name, whether the source is a dict or a list."""
    if isinstance(v, dict):
        return v
    out = {}
    for e in v or []:
        if isinstance(e, dict):
            out[e.get("id") or e.get("name") or json.dumps(e, sort_keys=True)] = e
    return out


ITEM_NAMES = {}  # item id -> name, from definitions.json (labels for trades/definitions)


def label(k, e):
    if isinstance(e, dict):
        n = e.get("name") or e.get("n") or (e.get("properties") or {}).get("name")
        if n:
            return n
    return ITEM_NAMES.get(str(k), k)


def short(v):
    """A field value shown inline if it's simple (text/number), else None."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        t = json.dumps(v, ensure_ascii=False)
        return t if len(t) <= 60 else t[:57] + "…"
    return None


def names(items, limit=25):
    items = sorted(str(x) for x in items)
    more = len(items) - limit
    return ", ".join(items[:limit]) + (" (+%d more)" % more if more > 0 else "")


def diff_dicts(old, new):
    oi, ni = keyed(old), keyed(new)
    added = [label(k, ni[k]) for k in ni if k not in oi]
    removed = [label(k, oi[k]) for k in oi if k not in ni]
    changed = []
    for k in ni:
        if k in oi and ni[k] != oi[k]:
            a, b = oi[k], ni[k]
            fields = []
            if isinstance(a, dict) and isinstance(b, dict):
                for f in sorted(set(a) | set(b)):
                    if a.get(f) == b.get(f):
                        continue
                    sa, sb = short(a.get(f)), short(b.get(f))
                    fields.append((f, "%s → %s" % (sa, sb) if sa is not None and sb is not None else None))
            changed.append((label(k, b), fields))
    return len(oi), len(ni), added, removed, changed


def section_entries(out, title, old, new, detail=40):
    no, nn, added, removed, changed = diff_dicts(old, new)
    if not (added or removed or changed):
        out.append("- **%s**: no changes (%d)" % (title, nn))
        return
    out.append("- **%s**: %d → %d" % (title, no, nn))
    if added:
        out.append("  - added (%d): %s" % (len(added), names(added)))
    if removed:
        out.append("  - removed (%d): %s" % (len(removed), names(removed)))
    if changed:
        by_field = Counter(f for _, fs in changed for f, _ in fs)
        out.append("  - changed (%d)%s" % (len(changed), ": " + ", ".join("%s ×%d" % kv for kv in by_field.most_common()) if by_field else ""))
        for name, fs in sorted(changed)[:detail]:
            out.append("    - %s%s" % (name, ": " + ", ".join(f + (" " + v if v else "") for f, v in fs) if fs else ""))
        if len(changed) > detail:
            out.append("    - … +%d more" % (len(changed) - detail))


def spawns_by_monster(v):
    """monster name -> number of spawn points, whatever the file's shape."""
    count = Counter()
    if isinstance(v, dict):
        for name, pts in v.items():
            count[name] += len(pts) if isinstance(pts, list) else 1
    elif isinstance(v, list):
        for e in v:
            if isinstance(e, dict):
                n = e.get("name") or e.get("monster")
                if n:
                    count[n] += 1
    return count


def minimap_chunks(blob):
    if not blob:
        return {}
    d = gzip.decompress(blob)
    if d[:4] != b"MMAP":
        return {}
    off, out = 6, {}
    while off + 5 + CH <= len(d):
        xc, yc = struct.unpack_from("<HH", d, off)
        out[(d[off + 4], xc, yc)] = d[off + 5: off + 5 + CH]
        off += 5 + CH
    return out


def section_minimap(out, old_blob, new_blob):
    a, b = minimap_chunks(old_blob), minimap_chunks(new_blob)
    if not a or not b:
        out.append("- **Minimap**: couldn't read %s" % ("the old copy" if not a else "the new copy"))
        return
    per_z = defaultdict(lambda: [0, 0, Counter()])  # changed, newly explored, chunk -> changed
    empty = bytes(CH)
    for key in set(a) | set(b):
        oa, nb = a.get(key, empty), b.get(key, empty)
        if oa == nb:
            continue
        changed = newly = 0
        for i in range(CH):
            if oa[i] != nb[i]:
                changed += 1
                if oa[i] == 0:
                    newly += 1
        z, xc, yc = key
        per_z[z][0] += changed
        per_z[z][1] += newly
        per_z[z][2][(xc, yc)] += changed
    if not per_z:
        out.append("- **Minimap**: no changes")
        return
    total = sum(v[0] for v in per_z.values())
    out.append("- **Minimap**: %d tiles changed, %d of them newly explored" % (total, sum(v[1] for v in per_z.values())))
    for z in sorted(per_z):
        changed, newly, chunks = per_z[z]
        where = ", ".join("x%d y%d (%d)" % (xc * 128 + 64, yc * 128 + 64, c) for (xc, yc), c in chunks.most_common(4))
        out.append("  - z%d: %d changed (%d newly explored) - around %s" % (z, changed, newly, where))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/main", help="git ref to compare against (default origin/main)")
    ap.add_argument("--out", default=None, help="report path, or - to only print (default data/changes/<today>.md)")
    args = ap.parse_args()
    ref_date = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short", args.ref, "--", "data/raw"],
                              cwd=ROOT, capture_output=True, text=True).stdout.strip()
    today = datetime.date.today().isoformat()
    out = ["# Raw data changes - %s" % today, "",
           "Compared with `%s`%s. Generated by `scripts/diff-raw.py`." % (args.ref, " (data from %s)" % ref_date if ref_date else ""), ""]

    out.append("## Files")
    present = set(os.listdir(RAW)) if os.path.isdir(RAW) else set()
    for name, needed in EXPECTED:
        old, new = old_file(args.ref, name), new_file(name)
        if new is None:
            state = "**missing**" + (" - the site needs it" if needed else " (optional)")
        elif old is None:
            state = "new"
        elif old == new:
            state = "**unchanged** since the last scrape - not re-downloaded?" if needed else "unchanged"
        else:
            state = "updated"
        out.append("- `%s`: %s" % (name, state))
    extra = sorted(present - {n for n, _ in EXPECTED} - NOT_DOWNLOADS)
    if extra:
        out.append("- not expected here: %s (hand-made inputs go in `data/manual/`)" % ", ".join("`%s`" % e for e in extra))
    out.append("")

    out.append("## What changed")
    defs = as_json(new_file("definitions.json")) or {}
    for k, e in (defs.items() if isinstance(defs, dict) else []):
        n = (e.get("properties") or {}).get("name") if isinstance(e, dict) else None
        if n:
            ITEM_NAMES[str(k)] = n
    lib_o, lib_n = as_json(old_file(args.ref, "library.json")), as_json(new_file("library.json"))
    if lib_n is not None:
        for cat in lib_n:
            section_entries(out, "Library - " + cat, (lib_o or {}).get(cat), lib_n.get(cat))
    sp_o, sp_n = spawns_by_monster(as_json(old_file(args.ref, "monster-spawns.json"))), spawns_by_monster(as_json(new_file("monster-spawns.json")))
    if sp_o != sp_n:
        diff = {m: (sp_o.get(m, 0), sp_n.get(m, 0)) for m in set(sp_o) | set(sp_n) if sp_o.get(m, 0) != sp_n.get(m, 0)}
        out.append("- **Monster spawns**: %d monsters' spawn points changed" % len(diff))
        for m, (a, b) in sorted(diff.items())[:60]:
            out.append("  - %s: %d → %d" % (m, a, b))
    else:
        out.append("- **Monster spawns**: no changes")
    for name, title in (("npc-trades.json", "NPC trades"), ("definitions.json", "Item definitions"), ("npc-poi.json", "NPC points of interest")):
        a, b = as_json(old_file(args.ref, name)), as_json(new_file(name))
        if b is not None:
            section_entries(out, title, a, b, detail=15)
    section_minimap(out, old_file(args.ref, "minimap.bin.gz"), new_file("minimap.bin.gz"))
    text = "\n".join(out) + "\n"

    print(text)
    if args.out != "-":
        path = args.out or os.path.join(ROOT, "data", "changes", today + ".md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("written to", os.path.relpath(path, ROOT), file=sys.stderr)


if __name__ == "__main__":
    main()
