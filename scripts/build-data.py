"""
Turn the raw scrape (data/raw/) into the two derived datasets the pages load:

    data/derived/compendium.json   <- library.json + monster-spawns.json + minimap.meta.json
    data/derived/merchant.json     <- library.json + npc-trades.json + definitions.json

Pure and offline: no network, deterministic, safe to re-run. This replaces the
one-off build step that produced the old inline `const DATA = {...}` blocks in
compendium.html / merchant-ledger.html.

Run:  python scripts/build-data.py
"""
import json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
DERIVED = os.path.join(ROOT, "data", "derived")


def load(name, where=RAW):
    with open(os.path.join(where, name), encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    return (s or "").strip().lower()


# --- monster difficulty tier -------------------------------------------------
# The bestiary has no difficulty field, so tier is bucketed from experience.
# Cut points are the midpoints of the gaps observed in the Aug-2026 data
# (tiers 0..4 there spanned exp 0-25 / 28-100 / 105-450 / 500-1450 / 1550+),
# and reproduce the tier of all 270 monsters from that snapshot exactly.
# Tier 4 ("Very Hard") then splits into 4 and 5 ("Boss") by spawn count -
# see eff_tier() in build_compendium(). Labels live in compendium.html
# (TIER_LABELS): 0 Novice / 1 Easy / 2 Medium / 3 Hard / 4 Very Hard / 5 Boss.
TIER_CUTS = [26, 102, 475, 1500]


def tier_for_exp(exp):
    for i, cut in enumerate(TIER_CUTS):
        if exp <= cut:
            return i
    return len(TIER_CUTS)


# ==========================================================================
#  compendium.json
# ==========================================================================
def build_compendium(lib, spawns, minimap_meta):
    items = lib["items"]

    # item name -> best price any NPC pays for it (from library sellTo). Plus the
    # hardcoded cases the source doesn't list a sellTo for: the currency coins
    # themselves, valued by their fixed gold-coin exchange rate (1 platinum =
    # 100 gold, 1 crystal = 100 platinum = 10,000 gold).
    sell_price = {"gold coin": 1, "platinum coin": 100, "crystal coin": 10000}
    for it in items:
        st = it.get("sellTo") or []
        if st:
            sell_price.setdefault(norm(it["name"]), max(s["price"] for s in st))

    # distinct spawn locations per monster (case-insensitive name match against
    # monster-spawns.json). Used for the Boss tier below.
    spawn_loc_count = {}
    for cl in spawns["clusters"]:
        spawn_loc_count[norm(cl["n"])] = spawn_loc_count.get(norm(cl["n"]), 0) + 1

    def eff_tier(name, base):
        # Top difficulty bucket (4) splits into "Very Hard" (4) and "Boss" (5):
        # a Boss is a unique monster with at most one spawn point - either a
        # single lair (1) or a raid/event boss with no fixed spawn at all (0).
        if base != 4:
            return base
        return 5 if spawn_loc_count.get(norm(name), 0) <= 1 else 4

    monsters = []
    loot_matched_total = loot_total_total = 0
    for m in lib["monsters"]:
        loot = []
        matched = 0
        for l in m.get("loot") or []:
            unit = sell_price.get(norm(l["name"]), 0)
            avg = (l["min"] + l["max"]) / 2
            value = l["probability"] * avg * unit
            if unit > 0:
                matched += 1
            loot.append({
                "name": l["name"], "probability": l["probability"],
                "min": l["min"], "max": l["max"],
                "unitPrice": unit, "value": value,
            })
        gpk = round(sum(x["value"] for x in loot), 2)
        exp = m.get("experience") or 0
        monsters.append({
            "name": m["name"],
            "health": m.get("health", 0),
            "experience": exp,
            "speed": m.get("speed", 0),
            "armor": m.get("armor", 0),
            "tier": eff_tier(m["name"], tier_for_exp(exp)),
            "attacks": [{"name": a.get("name"), "min": a.get("min", 0), "max": a.get("max", 0)}
                        for a in (m.get("attacks") or [])],
            "elements": [{"key": k, "pct": v} for k, v in (m.get("elements") or {}).items()],
            "immunities": [k for k, v in (m.get("immunities") or {}).items() if v],
            "loot": loot,
            "lootMatched": matched,
            "lootTotal": len(loot),
            "goldPerKill": gpk,
            "goldPerExp": round(gpk / exp, 3) if exp else None,
        })
        loot_matched_total += matched
        loot_total_total += len(loot)

    tier_by_name = {norm(m["name"]): m["tier"] for m in monsters}

    out_items = []
    for it in items:
        out_items.append({
            "cid": it.get("cid"), "sid": it.get("sid"), "name": it["name"],
            "weight": it.get("weight", 0),
            "attack": it.get("attack", 0), "defense": it.get("defense", 0),
            "armor": it.get("armor", 0), "range": it.get("range", 0),
            "weaponType": it.get("weaponType"), "slotType": it.get("slotType"),
            "category": it.get("category", "other"),
            "levelRequired": it.get("levelRequired", 0),
            "vocations": it.get("vocations"),
            "wandElement": it.get("wandElement"),
            "wandMinDamage": it.get("wandMinDamage", 0),
            "wandMaxDamage": it.get("wandMaxDamage", 0),
            "bonuses": it.get("bonuses") or [],
            "resists": it.get("resists") or [],
            "droppedBy": it.get("droppedBy") or [],
            "sellTo": it.get("sellTo") or [],
        })

    npcs = [{
        "name": n["name"], "position": n.get("position"),
        "keywords": n.get("keywords") or [],
        "sells": n.get("sells") or [], "buys": n.get("buys") or [],
    } for n in lib["npcs"]]

    # spawn map: group monster-spawns clusters by name
    by_name = {}
    for c in spawns["clusters"]:
        by_name.setdefault(c["n"], []).append([c["x"], c["y"], c["c"]])
    spawn_monsters = []
    xs, ys = [], []
    for name in sorted(by_name):
        pts = sorted(by_name[name], key=lambda p: (p[0], p[1]))
        spawn_monsters.append({
            "name": name,
            "tier": tier_by_name.get(norm(name), 0),
            "points": pts,
        })
        for x, y, _ in pts:
            xs.append(x); ys.append(y)
    bounds = {"xMin": min(xs), "xMax": max(xs), "yMin": min(ys), "yMax": max(ys)} if xs else {}

    return {
        "generatedAt": datetime.date.today().isoformat(),
        "summary": {
            "monsters": len(monsters), "items": len(out_items), "npcs": len(npcs),
            "spells": len(lib["spells"]), "runes": len(lib["runes"]),
            "achievements": len(lib["achievements"]),
        },
        "lootCoverage": {
            "matched": loot_matched_total, "total": loot_total_total,
            "pct": round(loot_matched_total / loot_total_total * 100, 1) if loot_total_total else 0,
        },
        "monsters": monsters,
        "items": out_items,
        "npcs": npcs,
        "spells": lib["spells"],
        "runes": lib["runes"],
        "achievements": lib["achievements"],
        "spawnMap": {"bounds": bounds, "monsters": spawn_monsters},
        "minimapMeta": minimap_meta,
    }


# ==========================================================================
#  merchant.json
# ==========================================================================
MERCHANT_CATEGORIES = [
    ("weapon-sword", "Swords"), ("weapon-axe", "Axes"), ("weapon-club", "Clubs & Maces"),
    ("weapon-distance", "Distance"), ("weapon-wand", "Wands & Rods"), ("shield", "Shields"),
    ("armor-helmet", "Helmets"), ("armor-body", "Armor"), ("armor-legs", "Legs"),
    ("armor-feet", "Boots"), ("jewelry", "Rings & Amulets"), ("food", "Food & Drink"),
    ("tools", "Tools"), ("valuables", "Valuables"), ("other", "Other"),
]
_CAT_ORDER = {k: i for i, (k, _) in enumerate(MERCHANT_CATEGORIES)}

_VALUABLES = {"gold coin", "platinum coin", "crystal coin", "small diamond", "small ruby",
              "small emerald", "small sapphire", "small amethyst", "small topaz",
              "talon", "gold nugget", "gold ingot", "green gem", "blue gem", "red gem",
              "yellow gem", "violet gem"}
_TOOLS = {"rope", "shovel", "pick", "machete", "scythe", "crowbar", "fishing rod",
          "closed trap", "wooden hammer", "sickle", "backpack", "bag", "torch"}


def merchant_category(item):
    """Fine-grained bucket for the ledger's category grouping."""
    name = norm(item.get("name"))
    wt = norm(item.get("weaponType"))
    st = norm(item.get("slotType"))
    if name in _VALUABLES:
        return "valuables"
    if wt in ("sword",):
        return "weapon-sword"
    if wt in ("axe",):
        return "weapon-axe"
    if wt in ("club", "mace"):
        return "weapon-club"
    if wt in ("distance", "bow", "crossbow", "throwing", "ammunition", "spear"):
        return "weapon-distance"
    if wt in ("wand", "rod"):
        return "weapon-wand"
    if st in ("shield",) or wt == "shield":
        return "shield"
    if st in ("head", "helmet"):
        return "armor-helmet"
    if st in ("body",):
        return "armor-body"
    if st in ("legs",):
        return "armor-legs"
    if st in ("feet",):
        return "armor-feet"
    if st in ("necklace", "amulet", "ring"):
        return "jewelry"
    if name in _TOOLS:
        return "tools"
    if item.get("category") == "food" or name in ("meat", "ham", "cheese", "bread", "roll"):
        return "food"
    return "other"


def build_merchant(lib, npc_trades, defs):
    items_by_sid = {it.get("sid"): it for it in lib["items"] if it.get("sid") is not None}
    items_by_name = {norm(it["name"]): it for it in lib["items"]}

    def item_name(sid):
        it = items_by_sid.get(sid)
        if it:
            return it["name"]
        d = defs.get(str(sid)) or {}
        return (d.get("properties") or {}).get("name") or ("sid " + str(sid))

    def item_cat(sid, name):
        it = items_by_sid.get(sid) or items_by_name.get(norm(name)) or {"name": name}
        return merchant_category(it)

    # --- buyers: npc-trades is sid -> [{name, price, region}] ---------------
    items = {}   # sid -> record
    npc_offers = {}  # npc name -> list of offers
    npc_regions = {}
    for sid_s, buyers in npc_trades.items():
        sid = int(sid_s)
        name = item_name(sid)
        blist = sorted(
            [{"npc": b["name"], "price": b["price"], "region": b.get("region", "unknown")} for b in buyers],
            key=lambda b: (-b["price"], b["npc"]),
        )
        items[sid] = {
            "sid": sid, "name": name, "buyers": blist,
            "maxPrice": blist[0]["price"] if blist else 0,
            "buyerCount": len(blist),
            "purchaseFrom": [], "sellers": [],
            "category": item_cat(sid, name),
        }
        for b in blist:
            npc_offers.setdefault(b["npc"], []).append(
                {"sid": sid, "name": norm(name), "price": b["price"], "region": b["region"]})
            npc_regions.setdefault(b["npc"], set()).add(b["region"])

    # --- sellers: library npcs[].sells is [{name(Title), price}] ------------
    npc_region_of = {}
    for rec in items.values():
        for b in rec["buyers"]:
            npc_region_of.setdefault(b["npc"], b["region"])

    npc_sells = {}
    for n in lib["npcs"]:
        sells = n.get("sells") or []
        npc_sells[n["name"]] = sells
        region = npc_region_of.get(n["name"], "unknown")
        for s in sells:
            it = items_by_name.get(norm(s["name"]))
            if not it or it.get("sid") is None:
                continue
            sid = it["sid"]
            rec = items.get(sid)
            if rec is None:
                rec = items[sid] = {
                    "sid": sid, "name": it["name"], "buyers": [], "maxPrice": 0,
                    "buyerCount": 0, "purchaseFrom": [], "sellers": [],
                    "category": merchant_category(it),
                }
            rec["sellers"].append({"npc": n["name"], "price": s["price"], "region": region})
            rec["purchaseFrom"].append({"npc": n["name"], "price": s["price"]})

    for rec in items.values():
        rec["sellers"].sort(key=lambda s: (s["price"], s["npc"]))
        rec["purchaseFrom"].sort(key=lambda s: (s["price"], s["npc"]))

    item_list = [r for r in items.values() if r["buyers"] or r["sellers"]]
    item_list.sort(key=lambda r: (_CAT_ORDER.get(r["category"], 99), r["name"].lower()))

    # --- npcs that buy something ------------------------------------------
    npc_list = []
    for name, offers in npc_offers.items():
        offers.sort(key=lambda o: (-o["price"], o["name"]))
        npc_list.append({
            "name": name,
            "regions": sorted(npc_regions.get(name, {"unknown"})),
            "offers": offers,
            "sells": npc_sells.get(name, []),
        })
    npc_list.sort(key=lambda n: n["name"].lower())

    # --- arbitrage: buy from one NPC, sell to another --------------------
    rows = []
    for r in items.values():
        if not r["buyers"] or not r["sellers"]:
            continue
        buy = min(r["sellers"], key=lambda s: s["price"])       # cheapest to buy
        sell = max(r["buyers"], key=lambda b: b["price"])       # best payout
        if buy["npc"] == sell["npc"]:
            continue
        rows.append({
            "name": r["name"].lower(),
            "buyPrice": buy["price"], "buyFrom": buy["npc"],
            "sellPrice": sell["price"], "sellTo": sell["npc"],
            "profit": sell["price"] - buy["price"],
        })
    rows.sort(key=lambda x: (-x["profit"], x["name"]))

    total_sell_listings = sum(len(v) for v in npc_sells.values())
    return {
        "generatedAt": datetime.date.today().isoformat(),
        "summary": {
            "totalItems": sum(1 for r in item_list if r["buyers"]),
            "totalNpcs": len(npc_list),
            "totalOffers": sum(r["buyerCount"] for r in item_list),
            "totalSellListings": total_sell_listings,
            "sellOnlyItems": sum(1 for r in item_list if r["sellers"] and not r["buyers"]),
        },
        "items": item_list,
        "npcs": npc_list,
        "arbitrage": {
            "checkedCount": len(rows),
            "profitableCount": sum(1 for r in rows if r["profit"] > 0),
            "breakEvenCount": sum(1 for r in rows if r["profit"] == 0),
            "rows": rows,
        },
        "categories": [{"key": k, "label": lbl} for k, lbl in MERCHANT_CATEGORIES],
    }


# ==========================================================================
#  CHANGELOG.md  - what moved since the previous build
# ==========================================================================
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
_HEAD = "# Changelog\n\nWhat each `refresh.bat` run changed, newest first. Generated by `scripts/build-data.py`.\n"


def _nameset(lst):
    return {x.get("name") for x in lst if x.get("name")}


def _fmt(names, cap=30):
    names = sorted(n for n in names if n)
    if not names:
        return "(none)"
    if len(names) <= cap:
        return ", ".join(names)
    return ", ".join(names[:cap]) + " ... (+%d more)" % (len(names) - cap)


def _max_sell(item):
    st = item.get("sellTo") or []
    return max((s["price"] for s in st), default=0)


def _changelog_section(prev_c, c, prev_m, m):
    L = ["## " + c["generatedAt"], ""]
    if not prev_c:
        L += ["Initial build.", "",
              "- Compendium: %(monsters)d monsters, %(items)d items, %(npcs)d NPCs, "
              "%(spells)d spells, %(runes)d runes, %(achievements)d achievements" % c["summary"],
              "- Merchant ledger: %(totalItems)d tradeable items, %(totalNpcs)d merchants, "
              "%(totalOffers)d buy offers" % m["summary"],
              "- Spawn map: %d monsters with spawn points" % len(c["spawnMap"]["monsters"]), ""]
        return "\n".join(L)

    changed = False

    def line(s):
        nonlocal changed
        changed = True
        L.append(s)

    # --- compendium collections -------------------------------------------
    for key, label in [("monsters", "Monsters"), ("items", "Items"), ("npcs", "NPCs"),
                       ("spells", "Spells"), ("runes", "Runes"), ("achievements", "Achievements")]:
        old, new = _nameset(prev_c[key]), _nameset(c[key])
        add, rem = new - old, old - new
        if add or rem:
            line("- **%s** %+d  (%d → %d)" % (label, len(new) - len(old), len(old), len(new)))
            if add:
                line("  - added: " + _fmt(add))
            if rem:
                line("  - removed: " + _fmt(rem))

    # --- monster stat / value moves -------------------------------------
    pm = {x["name"]: x for x in prev_c["monsters"]}
    tier_moves, gpk_moves, hp_moves, exp_moves = [], [], [], []
    for x in c["monsters"]:
        o = pm.get(x["name"])
        if not o:
            continue
        if o.get("tier") != x.get("tier"):
            tier_moves.append("%s %s→%s" % (x["name"], o.get("tier"), x.get("tier")))
        og, ng = o.get("goldPerKill", 0), x.get("goldPerKill", 0)
        if abs(ng - og) >= 1 and (og == 0 or abs(ng - og) / max(og, 1) >= 0.1):
            gpk_moves.append("%s %g→%g" % (x["name"], og, ng))
        if o.get("health") != x.get("health"):
            hp_moves.append("%s %s→%s" % (x["name"], o.get("health"), x.get("health")))
        if o.get("experience") != x.get("experience"):
            exp_moves.append("%s %s→%s" % (x["name"], o.get("experience"), x.get("experience")))
    if tier_moves:
        line("- Monster difficulty tier changed: " + _fmt(tier_moves, 20))
    if hp_moves:
        line("- Monster health changed: " + _fmt(hp_moves, 20))
    if exp_moves:
        line("- Monster experience changed: " + _fmt(exp_moves, 20))
    if gpk_moves:
        line("- Monster gold/kill changed: " + _fmt(gpk_moves, 20))

    # --- item sell-price moves ----------------------------------------
    pi = {x["name"]: x for x in prev_c["items"]}
    price_moves = []
    for x in c["items"]:
        o = pi.get(x["name"])
        if not o:
            continue
        op, np_ = _max_sell(o), _max_sell(x)
        if op != np_:
            price_moves.append("%s %d→%d" % (x["name"], op, np_))
    if price_moves:
        line("- Item best NPC sell price changed: " + _fmt(price_moves, 25))

    # --- spawn map ---------------------------------------------------
    po = sum(len(x["points"]) for x in prev_c["spawnMap"]["monsters"])
    no = sum(len(x["points"]) for x in c["spawnMap"]["monsters"])
    if (len(prev_c["spawnMap"]["monsters"]), po) != (len(c["spawnMap"]["monsters"]), no):
        line("- Spawn map: %d → %d monsters, %d → %d spawn points"
             % (len(prev_c["spawnMap"]["monsters"]), len(c["spawnMap"]["monsters"]), po, no))

    lc0, lc1 = prev_c["lootCoverage"]["pct"], c["lootCoverage"]["pct"]
    if lc0 != lc1:
        line("- Loot price coverage: %.1f%% → %.1f%%" % (lc0, lc1))

    # --- merchant ledger ------------------------------------------
    ms_lines = []
    for k, lbl in [("totalItems", "tradeable items"), ("totalNpcs", "merchants"),
                   ("totalOffers", "buy offers"), ("totalSellListings", "sell listings")]:
        if prev_m["summary"].get(k) != m["summary"].get(k):
            ms_lines.append("%s %s→%s" % (lbl, prev_m["summary"].get(k), m["summary"].get(k)))
    a0, a1 = prev_m["arbitrage"], m["arbitrage"]
    if (a0["checkedCount"], a0["profitableCount"], a0["breakEvenCount"]) != \
       (a1["checkedCount"], a1["profitableCount"], a1["breakEvenCount"]):
        ms_lines.append("arbitrage checked %d→%d, profitable %d→%d, break-even %d→%d"
                        % (a0["checkedCount"], a1["checkedCount"], a0["profitableCount"],
                           a1["profitableCount"], a0["breakEvenCount"], a1["breakEvenCount"]))
    if ms_lines:
        line("- **Merchant ledger**: " + "; ".join(ms_lines))
    old_prof = {r["name"] for r in a0["rows"] if r["profit"] > 0}
    new_prof = [r for r in a1["rows"] if r["profit"] > 0 and r["name"] not in old_prof]
    if new_prof:
        line("  - new profitable arbitrage: " + _fmt(
            ["%s (buy %d %s / sell %d %s, +%d)" % (r["name"], r["buyPrice"], r["buyFrom"],
                                                  r["sellPrice"], r["sellTo"], r["profit"])
             for r in new_prof], 15))

    if not changed:
        L.append("No changes.")
    L.append("")
    return "\n".join(L)


def write_changelog(prev_c, c, prev_m, m):
    section = _changelog_section(prev_c, c, prev_m, m)
    old = ""
    if os.path.exists(CHANGELOG):
        with open(CHANGELOG, encoding="utf-8") as f:
            old = f.read()
    body = old[len(_HEAD):] if old.startswith(_HEAD) else old
    # drop a section already written for the same date (re-run same day)
    marker = "## " + c["generatedAt"] + "\n"
    if body.lstrip().startswith(marker):
        rest = body.lstrip()[len(marker):]
        nxt = rest.find("\n## ")
        body = rest[nxt + 1:] if nxt != -1 else ""
    with open(CHANGELOG, "w", encoding="utf-8") as f:
        f.write(_HEAD + "\n" + section + "\n" + body.lstrip())


def main():
    os.makedirs(DERIVED, exist_ok=True)
    missing = [f for f in ("library.json", "monster-spawns.json", "npc-trades.json", "definitions.json")
               if not os.path.exists(os.path.join(RAW, f))]
    if missing:
        print("missing raw inputs: " + ", ".join(missing), file=sys.stderr)
        print("run scripts/fetch-live.py and capture data/raw/library.json first.", file=sys.stderr)
        sys.exit(1)

    lib = load("library.json")
    spawns = load("monster-spawns.json")
    npc_trades = load("npc-trades.json")
    defs = load("definitions.json")
    try:
        minimap_meta = load("minimap.meta.json", DERIVED)
    except FileNotFoundError:
        minimap_meta = {}
        print("  note: data/derived/minimap.meta.json missing — run gen-minimap.py; map will lack terrain")

    # previous build, for the changelog diff (read before we overwrite)
    try:
        prev_comp = load("compendium.json", DERIVED)
    except (FileNotFoundError, ValueError):
        prev_comp = None
    try:
        prev_merch = load("merchant.json", DERIVED)
    except (FileNotFoundError, ValueError):
        prev_merch = None

    comp = build_compendium(lib, spawns, minimap_meta)
    merch = build_merchant(lib, npc_trades, defs)

    write_changelog(prev_comp, comp, prev_merch, merch)

    def dump(obj, stem, global_name):
        blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(DERIVED, stem + ".json"), "w", encoding="utf-8") as f:
            f.write(blob)
        # .js twin: the pages <script src> this so they work over file:// (no server)
        with open(os.path.join(DERIVED, stem + ".js"), "w", encoding="utf-8") as f:
            f.write("window.%s=%s;\n" % (global_name, blob))

    dump(comp, "compendium", "__MINIBIA_COMPENDIUM__")
    dump(merch, "merchant", "__MINIBIA_MERCHANT__")
    with open(os.path.join(DERIVED, "meta.js"), "w", encoding="utf-8") as f:
        f.write("window.__MINIBIA_META__=%s;\n" % json.dumps(
            {"generatedAt": comp["generatedAt"]}, ensure_ascii=False))

    print("compendium.json:", comp["summary"],
          "| loot coverage %.1f%%" % comp["lootCoverage"]["pct"],
          "| spawn monsters", len(comp["spawnMap"]["monsters"]))
    print("merchant.json:  ", merch["summary"],
          "| arbitrage rows", merch["arbitrage"]["checkedCount"],
          "profitable", merch["arbitrage"]["profitableCount"])


if __name__ == "__main__":
    main()
