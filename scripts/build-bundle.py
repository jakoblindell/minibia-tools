"""
Build minibia-tools.html - a single self-contained file holding all four tool
pages (home / merchant ledger / compendium / account ledger) plus the 16 spawn-map
terrain PNGs, so it can be passed around as one attachment with nothing to unzip.

Each tool page is embedded verbatim and shown in a same-origin <iframe srcdoc>,
so its CSS/JS stay fully isolated - no merging, no collisions. A persistent top
bar switches tools. compendium.html's external minimap-z*.png references are
rewritten to inline data: URIs.

compendium.html / merchant-ledger.html normally fetch data/derived/*.json at
runtime; a srcdoc iframe can't do that, so this bundles the current derived JSON
straight into each page. Run scripts/build-data.py first.

Run:  python scripts/build-bundle.py   ->   dist/minibia-tools.html
"""
import base64, json, re, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")               # the four tool pages + minimap-z*.png live here
DERIVED = os.path.join(ROOT, "data", "derived")  # build-data.py output
OUT  = os.path.join(ROOT, "dist", "minibia-tools.html")

def read(name):
    with open(os.path.join(SITE, name), encoding="utf-8") as f:
        return f.read()

def inline_data(html, stem):
    """Replace the page's <script src="../data/derived/<stem>.js"> with the file's
    contents inline, so the bundled copy needs no sibling files."""
    path = os.path.join(DERIVED, stem + ".js")
    if not os.path.exists(path):
        sys.exit("missing %s - run scripts/build-data.py first" % path)
    with open(path, encoding="utf-8") as f:
        payload = f.read().strip()
    tag = '<script src="../data/derived/%s.js"></script>' % stem
    if tag not in html:
        sys.exit("could not find %s to inline" % tag)
    return html.replace(tag, "<script>" + payload + "</script>", 1)

# --- compendium: inline the per-floor terrain PNGs -------------------------------
comp = inline_data(read("compendium.html"), "compendium")
png_map = {}
for z in range(16):
    with open(os.path.join(SITE, f"minimap-z{z}.png"), "rb") as f:
        png_map[z] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")

pngs_js = "const MAP_FLOOR_PNG = " + json.dumps(png_map) + ";\n"
# drop it in right after the MAP_FLOOR_META object literal
comp, n = re.subn(r"(const MAP_FLOOR_META = \{.*?\n\};\n)", r"\1" + pngs_js.replace("\\", "\\\\"), comp, count=1, flags=re.S)
assert n == 1, "MAP_FLOOR_META anchor not found"
comp, n = re.subn(r'entry\.img\.src = "minimap-z" \+ z \+ "\.png";',
                  'entry.img.src = MAP_FLOOR_PNG[z] || ("minimap-z" + z + ".png");', comp, count=1)
assert n == 1, "image src line not found"

# --- rewrite cross-page navigation for the embedded copies ---------------------
def fix_topnav(html):
    return html.replace(
        '<div class="topnav"><a href="index.html">&larr; Tools</a><span>Minibia reference tools</span></div>',
        '<div class="topnav"><a href="#" onclick="try{parent.__nav(\'home\')}catch(e){}return false">&larr; Tools</a>'
        '<span>Minibia reference tools</span></div>')

home = read("index.html")
for key, page in [("merchant", "merchant-ledger.html"), ("compendium", "compendium.html"), ("accounts", "accounts.html")]:
    home = home.replace('href="%s"' % page,
                        'href="#" onclick="try{parent.__nav(\'%s\')}catch(e){}return false"' % key)

TOOLS = {
    "home": home,
    "merchant": fix_topnav(inline_data(read("merchant-ledger.html"), "merchant")),
    "compendium": fix_topnav(comp),
    "accounts": fix_topnav(read("accounts.html")),
}

# Embed as a JSON blob inside a <script>. The only sequence that can break out of
# the script element is "</...", so escape the slash; JSON turns it back into "/".
blob = json.dumps(TOOLS).replace("</", "<\\/")

shell = """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Minibia Tools</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>&#127993;</text></svg>">
<style>
  :root { color-scheme: light dark; --bar-bg:#181d24; --bar-fg:#ece6d8; --bar-muted:#9aa1b0; --bar-accent:#d9ad4f; --bar-border:#2c3441; }
  * { box-sizing:border-box; }
  html,body { margin:0; padding:0; height:100%; }
  body { display:flex; flex-direction:column; background:#12151a; font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
  #bar { flex:0 0 auto; display:flex; align-items:center; gap:4px; flex-wrap:wrap;
         background:var(--bar-bg); color:var(--bar-fg); border-bottom:1px solid var(--bar-border); padding:8px 14px; }
  #bar .brand { font-weight:700; letter-spacing:.02em; margin-right:12px; font-size:14px; }
  #bar button { font:inherit; font-size:13px; font-weight:600; color:var(--bar-muted); background:transparent;
                border:1px solid transparent; border-radius:7px; padding:6px 12px; cursor:pointer; }
  #bar button:hover { color:var(--bar-fg); }
  #bar button.active { color:#1a1508; background:var(--bar-accent); }
  #view { flex:1 1 auto; width:100%; border:0; background:#12151a; }
</style>
</head>
<body>
  <div id="bar">
    <span class="brand">&#127993; Minibia Tools</span>
    <button data-k="home">Home</button>
    <button data-k="merchant">Merchant Ledger</button>
    <button data-k="compendium">World Compendium</button>
    <button data-k="accounts">Account Ledger</button>
  </div>
  <iframe id="view" title="tool"></iframe>
<script>
const TOOLS = JSON.parse(__BLOB__);
const view = document.getElementById("view");
const bar = document.getElementById("bar");
function nav(k) {
  if (!TOOLS[k]) k = "home";
  view.srcdoc = TOOLS[k];
  bar.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.k === k));
  if (location.hash.slice(1) !== k) history.replaceState(null, "", "#" + k);
}
window.__nav = nav;
bar.addEventListener("click", e => { const b = e.target.closest("button"); if (b) nav(b.dataset.k); });
addEventListener("message", e => { if (typeof e.data === "string" && e.data.slice(0,4) === "nav:") nav(e.data.slice(4)); });
addEventListener("hashchange", () => nav(location.hash.slice(1)));
nav(location.hash.slice(1) || "home");
</script>
</body>
</html>
"""

out = shell.replace("__BLOB__", json.dumps(blob))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out)

mb = os.path.getsize(OUT) / 1024 / 1024
print(f"wrote {OUT}  ({mb:.1f} MB)")
for k, v in TOOLS.items():
    print(f"  {k:11} {len(v)/1024:8.0f} KB")
