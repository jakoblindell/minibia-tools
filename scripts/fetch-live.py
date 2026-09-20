"""
Pull the un-gated live game data into data/raw/.

These endpoints are served straight off minibia.com with no Cloudflare
challenge (unlike the Library and the highscores API, which need a browser).
Anything that fails is reported and skipped - a stale copy stays in place.

Run:  python scripts/fetch-live.py
"""
import gzip, io, json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

# gameClient.SERVER_VERSION - the {version} segment in /data/{version}/... .
# Bump this after a client deploy (check the Network tab on minibia.com/play,
# or src/ if you have a fresh pull). A wrong value just makes those two files
# 404 and skip; the JSON endpoints below don't depend on it.
SERVER_VERSION = "760"

BASE = "https://minibia.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) minibia-tools/refresh"

# (url, out filename, is_gzip)
TARGETS = [
    (f"{BASE}/play/monster-spawns.json", "monster-spawns.json", False),
    (f"{BASE}/play/npc-trades.json",     "npc-trades.json",      False),
    (f"{BASE}/play/definitions.json",    "definitions.json",     False),
    (f"{BASE}/play/npc-poi.json",        "npc-poi.json",         False),
    (f"{BASE}/data/{SERVER_VERSION}/constants.json", "constants.json", False),
    (f"{BASE}/data/{SERVER_VERSION}/minimap.bin.gz", "minimap.bin",    True),
]


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    os.makedirs(RAW, exist_ok=True)
    ok, failed = [], []
    for url, name, is_gz in TARGETS:
        dest = os.path.join(RAW, name)
        try:
            t0 = time.time()
            blob = fetch(url)
            if is_gz:
                blob = gzip.decompress(blob)
            else:
                json.loads(blob)  # validate
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dest)
            kb = len(blob) / 1024
            print(f"  ok   {name:22} {kb:9.1f} KB  ({time.time()-t0:.1f}s)")
            ok.append(name)
        except Exception as e:
            print(f"  FAIL {name:22} {url}\n       {e}")
            failed.append(name)

    print(f"\n{len(ok)}/{len(TARGETS)} fetched into data/raw/")
    if failed:
        print("kept existing copies for:", ", ".join(failed))
    # monster-spawns / npc-trades / definitions are what the pages actually
    # need - fail hard only if one of those is missing entirely.
    critical = {"monster-spawns.json", "npc-trades.json", "definitions.json"}
    missing = [c for c in critical if not os.path.exists(os.path.join(RAW, c))]
    if missing:
        print("MISSING critical inputs:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
