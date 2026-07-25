#!/usr/bin/env python3
"""
SSA Weekly AquaSwap Post
• Fetches live inventory from superiorshrimpaquatics.com (Shopify API)
• Skips sold-out and archived products
• Builds a formatted pricing list
• Opens a browser preview with copy buttons so you can review and submit manually
"""

import math
import os, sys, json, logging, re, webbrowser, urllib.request, html, subprocess
import threading, http.server, time
from datetime import datetime

_HERE      = os.path.dirname(os.path.abspath(__file__))
LOG_DIR    = os.path.join(_HERE, "ssa_monitor_logs")
LOG_FILE   = os.path.join(LOG_DIR, "weekly_post.log")
IMAGES_DIR       = os.path.join(_HERE, "ssa_post_images")
PRODUCT_IMG_DIR   = os.path.join(IMAGES_DIR, "products")
COLLAGE_PREFIX    = "collage_"
TILE_SIZE         = 600       # px per tile
COLLAGE_COLS      = 3
COLLAGE_ROWS      = 3
TILES_PER_COLLAGE = 9         # max images per collage

CATEGORY_ORDER = ["neocaridina", "caridina", "fish", "plants", "snails", "crabs",
                  "botanicals", "food", "dry_goods", "other"]
CATEGORY_LABELS = {
    "neocaridina": "Neocaridina Shrimp",
    "caridina":    "Caridina Shrimp",
    "fish":        "Fish",
    "plants":      "Plants",
    "snails":      "Snails",
    "crabs":       "Crabs & Crayfish",
    "botanicals":  "Botanicals",
    "food":        "Food",
    "dry_goods":   "Dry Goods",
    "other":       "Other",
}

POST_TITLE = "[FS] - Duluth, MN - $0.50+ - Neocaridina, Caridina, Fish, Plants, Snails, Crabs & More"
SHOP_URL   = "https://superiorshrimpaquatics.com/products.json"
REDDIT_URL     = "https://www.reddit.com/r/AquaSwap/submit"
UA             = "ssa-monitor/1.0 by djester808"


# ── Availability helpers ─────────────────────────────────────────────────────

def _available(p):
    return any(v.get("available") for v in p.get("variants", []))

def _variant_price(p, starts_with):
    for v in p.get("variants", []):
        if v.get("available") and v["title"].startswith(starts_with):
            return v["price"]
    return None

def _first_available(p):
    for v in p.get("variants", []):
        if v.get("available"):
            return v["price"]
    return None


# ── Classification helpers ───────────────────────────────────────────────────

_CARIDINA_KW = {"amano", "king kong", "tiger", "bolt", "crystal"}

def _is_caridina(title):
    t = title.lower()
    return any(k in t for k in _CARIDINA_KW)

def _is_amano(title):
    return "amano" in title.lower()

def _is_food(p):
    t = p["title"].lower()
    return (p.get("product_type") == "Food"
            or any(w in t for w in ["food", "pellet", "lollie", "wafer"]))

_PLANT_VARIANT_PRIORITY = [
    "Rhizome", "Bunch", "Golf Ball", "2 x 2",
    "2 Tablespoons", "6 - 8", "20-25", "1 1/2",
]

def _plant_price(p):
    for label in _PLANT_VARIANT_PRIORITY:
        for v in p.get("variants", []):
            if v.get("available") and v["title"].startswith(label):
                return v["price"]
    return _first_available(p)

def _categorize_plant(p):
    t = p["title"].lower()
    if "anubias"       in t: return "anubias"
    if "bucephalandra" in t: return "buce"
    if "cryptocoryne"  in t: return "crypto"
    if "echinodorus"   in t or "sword" in t: return "sword"
    if any(w in t for w in ["azolla","duckweed","frogbit","water lettuce",
                             "water spangles","red root"]):
        return "floater"
    if any(w in t for w in ["moss","fern","bolbitis","subwassertang",
                             "dwarf baby tears","monte carlo","staurogyne","glosso"]):
        return "moss"
    return "stem"

def _excluded(p):
    t = p["title"].lower()
    return any(k in t for k in ["ice pack", "heat pack", "skittles", "azolla", "brazos"])

def _product_category(p):
    pt    = (p.get("product_type") or "").strip()
    title = p["title"].lower()
    if pt == "Shrimp":
        return "caridina" if _is_caridina(title) else "neocaridina"
    if pt == "Fish":
        return "fish"
    if pt in ("Plant", "Other"):
        return "plants"
    if pt == "Snails":
        return "snails"
    if pt in ("Crab", "Crayfish"):
        return "crabs"
    if pt == "Botanical":
        return "botanicals"
    if pt == "Food" or _is_food(p):
        return "food"
    if pt == "Dry Good":
        return "dry_goods"
    return "other"

def _shrimp_name(title):
    return title.replace(" Shrimp","").replace(" shrimp","").strip()

def _botanical_entry(p):
    for v in p.get("variants", []):
        if not v.get("available"):
            continue
        t, price = v["title"], v["price"]
        if t == "Default Title" or t.startswith("1"):
            return f"- {p['title']} — ${price} each"
        if "Pieces" in t:
            n = t.split()[0]
            return f"- {p['title']} — ${price}/{n}"
        return f"- {p['title']} — ${price}"
    return None


# ── Shopify product fetch ────────────────────────────────────────────────────

def fetch_products():
    products, page = [], 1
    while True:
        url = f"{SHOP_URL}?limit=250&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            batch = json.loads(r.read().decode())["products"]
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products


# ── Listing builder ──────────────────────────────────────────────────────────

_HEADER = """\
5 years on AquaSwap, 5,000+ orders, and a shrimp operation built from the ground up in the \
northern Midwest — I've put in the work so you don't have to wonder if your animals will \
arrive alive and healthy. Every order ships with care, and my track record speaks for itself.

📍 Duluth, MN | Local pickup available
📋 100% Live Guarantee | Free 2-day shipping on orders $120+ | Heat/ice packs available | Buy 2 Get 1 Free on all plants

---

## 📦 PACK SIZE GUIDE

- **5-pack** — 5 shrimp, standard mix
- **10-pack** — 10 shrimp, standard mix
- **20-pack** — 20 shrimp, standard mix
- **Breeder Pack** — 10 shrimp, sexed (8F / 2M)
- **Ultimate Breeder Pack** — 10 shrimp, sexed (8F / 2M) + 3 oz shrimp food, 1 cholla wood & 5 almond leaves

---"""

_FOOTER = """\
Shipping: Free 2-day shipping on orders $120+. Ships Monday only. \
Heat/ice packs available. 100% Live Guarantee on all livestock.

Payment: PayPal Goods & Services

🌐 Full inventory & website in my profile

Comment below or DM to order! 🦐"""


def build_listing(products):
    by_type = {}
    for p in products:
        pt = (p.get("product_type") or "Other").strip()
        by_type.setdefault(pt, []).append(p)

    parts = [_HEADER]

    # ── Neocaridina ──────────────────────────────────────────────────────────
    shrimp_avail = [p for p in by_type.get("Shrimp", []) if _available(p) and not _excluded(p)]
    neo = sorted(
        [p for p in shrimp_avail
         if not _is_caridina(p["title"])
         and "culls"    not in p["title"].lower()
         and "skittles" not in p["title"].lower()],
        key=lambda p: float(_variant_price(p, "5") or 999),
    )
    if neo:
        rows = ["\n## 🦐 NEOCARIDINA SHRIMP\n",
                "*Prices listed per 5-pack. Also available in 10, 20, Breeder Pack & Ultimate Breeder Pack.*\n"]
        for p in neo:
            p5  = _variant_price(p, "5")
            bp  = _variant_price(p, "Breeder Pack")
            ubp = _variant_price(p, "Ultimate Breeder Pack")
            if not p5:
                continue
            line = f"- {_shrimp_name(p['title'])} — ${p5}/5"
            if bp:
                line += f" | ${bp} BP"
            if ubp:
                line += f" | ${ubp} UBP"
            rows.append(line)
        culls = next((p for p in shrimp_avail if "culls" in p["title"].lower()), None)
        if culls:
            price = _variant_price(culls, "5")
            if price:
                rows += ["\n**Specials:**", f"- Culls — ${price}/5"]
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Caridina ─────────────────────────────────────────────────────────────
    caridina  = [p for p in shrimp_avail if _is_caridina(p["title"])]
    amanos    = sorted([p for p in caridina if _is_amano(p["title"])],
                       key=lambda p: p["title"])
    bee_tiger = sorted([p for p in caridina if not _is_amano(p["title"])],
                       key=lambda p: float(_variant_price(p, "5") or 999))
    if caridina:
        rows = ["\n## 🦐 CARIDINA SHRIMP\n"]
        if amanos:
            rows.append("**Amano Variants** *(sold individually)*\n")
            for p in amanos:
                price = _variant_price(p, "1") or _first_available(p)
                if price:
                    rows.append(f"- {_shrimp_name(p['title'])} — ${price} each")
        if bee_tiger:
            rows.append("\n**Bee & Tiger Shrimp** *(prices listed per 5-pack, also available in 10 & 20)*\n")
            for p in bee_tiger:
                price = _variant_price(p, "5")
                if price:
                    rows.append(f"- {_shrimp_name(p['title'])} — ${price}/5")
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Plants ───────────────────────────────────────────────────────────────
    plant_items = [p for p in (by_type.get("Plant", []) + by_type.get("Other", []))
                   if _available(p)]
    cats = {"anubias":[], "buce":[], "crypto":[], "sword":[],
            "stem":[], "moss":[], "floater":[]}
    for p in plant_items:
        cats[_categorize_plant(p)].append(p)

    plant_sections = [
        ("Anubias",                "per rhizome", "anubias"),
        ("Bucephalandra",          "per rhizome", "buce"),
        ("Cryptocoryne",           "per rhizome", "crypto"),
        ("Swords / Echinodorus",   "per rhizome", "sword"),
        ("Stem & Background Plants","per bunch",  "stem"),
        ("Moss, Carpet & Ferns",   None,          "moss"),
        ("Floaters",               None,          "floater"),
    ]
    _plant_notes = {
        "per rhizome": "Rhizome plants are sold attached to their horizontal root structure — just tie or wedge onto driftwood or rock, no burying needed.",
        "per bunch":   "Stem plants are sold as a bundle of multiple stems (~5-8 stems) held together, ready to plant in substrate.",
    }
    if any(cats[k] for _, _, k in plant_sections):
        rows = ["\n## 🌿 AQUATIC PLANTS\n", "Buy 2 Get 1 Free on all plants!"]
        for header, note, key in plant_sections:
            items = sorted(cats[key], key=lambda p: p["title"])
            if not items:
                continue
            note_str = f" ({note})" if note else ""
            rows.append(f"\n{header}{note_str}")
            if note and note in _plant_notes:
                rows.append(f"{_plant_notes[note]}\n")
            for p in items:
                price = _plant_price(p)
                if price:
                    rows.append(f"- {p['title']} - ${price}")
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Snails ───────────────────────────────────────────────────────────────
    snails = sorted([p for p in by_type.get("Snails", []) if _available(p) and not _excluded(p)],
                    key=lambda p: float(_variant_price(p, "1") or _first_available(p) or 999))
    if snails:
        rows = ["\n## 🐌 FRESHWATER SNAILS *(sold individually)*\n"]
        for p in snails:
            price = _variant_price(p, "1") or _first_available(p)
            if price:
                rows.append(f"- {p['title']} — ${price} each")
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Crabs & Crayfish ─────────────────────────────────────────────────────
    crabs    = [p for p in by_type.get("Crab",     []) if _available(p)]
    crayfish = [p for p in by_type.get("Crayfish", []) if _available(p)]
    if crabs or crayfish:
        rows = ["\n## 🦀 CRABS & CRAYFISH\n"]
        for p in sorted(crabs + crayfish, key=lambda p: p["title"]):
            price = _first_available(p)
            if price:
                rows.append(f"- {p['title']} — ${price} each")
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Botanicals ───────────────────────────────────────────────────────────
    botanicals = sorted([p for p in by_type.get("Botanical", []) if _available(p)],
                        key=lambda p: p["title"])
    if botanicals:
        rows = ["\n## 🍂 BOTANICALS\n"]
        for p in botanicals:
            entry = _botanical_entry(p)
            if entry:
                rows.append(entry)
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Food & Supplements ───────────────────────────────────────────────────
    food_items = sorted(
        [p for p in (by_type.get("Food", []) + by_type.get("Dry Good", []))
         if _available(p) and _is_food(p)],
        key=lambda p: p["title"],
    )
    if food_items:
        rows = ["\n## 🍽️ FOOD & SUPPLEMENTS\n"]
        for p in food_items:
            price = _first_available(p)
            v     = p["variants"][0]
            size  = v["title"] if v["title"] != "Default Title" else ""
            suffix = f" ({size})" if size else ""
            if price:
                rows.append(f"- {p['title']} — ${price}{suffix}")
        rows.append("\n---")
        parts.append("\n".join(rows))

    # ── Dry Goods & Accessories ───────────────────────────────────────────────
    dry_items = sorted(
        [p for p in by_type.get("Dry Good", [])
         if _available(p) and not _is_food(p) and not _excluded(p) and "gift card" not in p["title"].lower()],
        key=lambda p: p["title"],
    )
    if dry_items:
        rows = ["\n## 🛠️ DRY GOODS & ACCESSORIES\n"]
        for p in dry_items:
            price = _first_available(p)
            if price:
                rows.append(f"- {p['title']} — ${price}")
        rows.append("\n---")
        parts.append("\n".join(rows))

    parts.append("\n" + _FOOTER)
    listing = "\n".join(parts)
    listing = listing.replace("—", "-").replace("–", "-").replace("*", "")
    return listing


# ── Local server (serves the page + images + actions) ────────────────────────

def _make_handler(images_dir, get_html):
    class _Handler(http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            if self.path == "/":
                body = get_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/images/"):
                fname = os.path.basename(self.path)
                fpath = os.path.join(images_dir, fname)
                if os.path.exists(fpath):
                    with open(fpath, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404); self.end_headers()
            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):
            if self.path == "/select-all":
                folder_name = os.path.basename(images_dir)
                subprocess.Popen(["explorer", images_dir])
                time.sleep(1.4)
                ps = (
                    f"$sh = New-Object -ComObject WScript.Shell; "
                    f"$sh.AppActivate('{folder_name}') | Out-Null; "
                    f"Start-Sleep -Milliseconds 300; "
                    f"$sh.SendKeys('^a')"
                )
                subprocess.run(
                    ["powershell", "-NonInteractive", "-Command", ps],
                    capture_output=True,
                )
                self.send_response(200); self.end_headers()
            else:
                self.send_response(404); self.end_headers()

        def log_message(self, *args): pass
    return _Handler


def start_local_server(images_dir, get_html):
    """Serve the preview page and handle actions. Returns port."""
    handler = _make_handler(images_dir, get_html)
    server  = http.server.HTTPServer(("localhost", 0), handler)
    port    = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port


# ── Image helpers ────────────────────────────────────────────────────────────

def _is_placeholder(url, alt=""):
    u = (url or "").lower()
    a = (alt or "").lower()
    return any(k in u for k in ["coming-soon", "coming_soon", "placeholder", "no-image", "noimage"]) \
        or "coming" in a

def fetch_product_images(products):
    """Return {category: [(filename, url)]} — one real image per available product."""
    groups, seen = {}, set()
    for p in products:
        if not _available(p) or _excluded(p):
            continue
        cat = _product_category(p)
        for img in p.get("images", []):
            src = img.get("src", "")
            alt = img.get("alt") or ""
            if _is_placeholder(src, alt):
                continue
            clean = src.split("?")[0]
            if clean in seen:
                continue
            seen.add(clean)
            slug = re.sub(r'[^a-z0-9]+', '_', p["title"].lower()).strip('_')
            ext  = os.path.splitext(clean)[-1].lower() or ".jpg"
            groups.setdefault(cat, []).append((f"{slug}{ext}", clean))
            break
    return groups

def download_product_images(groups):
    """Download product images. Returns {category: [local_path]}."""
    os.makedirs(PRODUCT_IMG_DIR, exist_ok=True)
    result = {}
    for cat, infos in groups.items():
        paths = []
        for hint, url in infos:
            dest = os.path.join(PRODUCT_IMG_DIR, hint)
            if not os.path.exists(dest):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        data = r.read()
                    if len(data) < 5000:
                        logging.info(f"  Skipped {hint} ({len(data)} bytes)")
                        continue
                    with open(dest, "wb") as f:
                        f.write(data)
                    logging.info(f"  Downloaded {hint}")
                except Exception as e:
                    logging.warning(f"  Failed {url}: {e}")
                    continue
            if os.path.exists(dest):
                paths.append(dest)
        if paths:
            result[cat] = paths
    return result

def _grid_dims(n):
    """Best-fit (cols, rows) for n images, max 3 cols."""
    cols = min(n, COLLAGE_COLS)
    rows = math.ceil(n / cols)
    return cols, rows

def build_collages(grouped_paths):
    """Create collages grouped by category with a layout that fits the image count."""
    from PIL import Image

    os.makedirs(IMAGES_DIR, exist_ok=True)
    for f in os.listdir(IMAGES_DIR):
        if f.startswith(COLLAGE_PREFIX) and f.endswith(".jpg"):
            os.remove(os.path.join(IMAGES_DIR, f))

    collages, num = [], 0
    for cat in CATEGORY_ORDER:
        paths = grouped_paths.get(cat, [])
        if not paths:
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        for chunk_start in range(0, len(paths), TILES_PER_COLLAGE):
            chunk = paths[chunk_start:chunk_start + TILES_PER_COLLAGE]
            tiles = []
            for path in chunk:
                try:
                    raw = Image.open(path)
                    if raw.mode in ("RGBA", "LA", "P"):
                        bg = Image.new("RGB", raw.size, (255, 255, 255))
                        bg.paste(raw.convert("RGBA"), mask=raw.convert("RGBA").split()[3])
                        img = bg
                    else:
                        img = raw.convert("RGB")
                    tiles.append(img.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS))
                except Exception as e:
                    logging.warning(f"  Skipped tile {path}: {e}")
            if not tiles:
                continue
            cols, rows = _grid_dims(len(tiles))
            canvas = Image.new("RGB", (cols * TILE_SIZE, rows * TILE_SIZE), (30, 30, 46))
            for j, tile in enumerate(tiles):
                canvas.paste(tile, ((j % cols) * TILE_SIZE, (j // cols) * TILE_SIZE))
            num += 1
            dest = os.path.join(IMAGES_DIR, f"{COLLAGE_PREFIX}{num:02d}_{cat}.jpg")
            canvas.save(dest, "JPEG", quality=85)
            logging.info(f"  Collage {num} [{label}]: {len(tiles)} images ({cols}×{rows})")
            collages.append(dest)
    if len(collages) > 20:
        logging.warning(f"  Capped at 20 collages (had {len(collages)})")
        collages = collages[:20]
    return collages


# ── Browser preview ──────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SSA Weekly Post Draft</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:#1e1e2e; color:#cdd6f4; font-family:'Segoe UI',sans-serif; padding:2rem; }}
  h1   {{ color:#cba6f7; margin-bottom:.25rem; }}
  .ts  {{ color:#6c7086; font-size:.85rem; margin-bottom:1.5rem; }}

  /* ── Launch banner ── */
  .launch {{
    display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem;
    background:#313244; border:1px solid #cba6f7; border-radius:10px;
    padding:1.25rem 1.5rem; margin-bottom:1.75rem;
  }}
  .launch-text {{ font-size:1rem; line-height:1.6; }}
  .launch-text strong {{ color:#cba6f7; }}
  .launch-text ol {{ margin:.4rem 0 0 1.2rem; color:#a6adc8; font-size:.9rem; }}
  .go-btn {{
    flex-shrink:0; background:#cba6f7; color:#1e1e2e; border:none;
    padding:.85rem 1.75rem; border-radius:8px; cursor:pointer;
    font-weight:800; font-size:1.05rem; white-space:nowrap; transition:background .15s;
  }}
  .go-btn:hover   {{ background:#d0bcff; }}
  .go-btn.done    {{ background:#a6e3a1; }}
  .go-btn.partial {{ background:#fab387; }}

  /* ── Fields ── */
  label {{ display:block; color:#a6e3a1; font-weight:600;
           font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; margin-bottom:.35rem; }}
  .field {{ margin-bottom:1.25rem; }}
  input[type=text] {{
    width:100%; background:#313244; color:#cdd6f4;
    border:1px solid #45475a; padding:.6rem .75rem; border-radius:6px; font-size:.95rem;
  }}
  textarea {{
    width:100%; background:#313244; color:#cdd6f4;
    border:1px solid #45475a; padding:.75rem; border-radius:6px;
    font-family:'Consolas',monospace; font-size:.82rem; line-height:1.55;
    height:500px; resize:vertical;
  }}
  .btn-row {{ display:flex; gap:.6rem; margin-top:.5rem; flex-wrap:wrap; }}
  button.copy-btn {{
    background:#45475a; color:#cdd6f4; border:none;
    padding:.45rem 1rem; border-radius:6px; cursor:pointer;
    font-weight:600; font-size:.85rem; transition:background .15s;
  }}
  button.copy-btn:hover {{ background:#585b70; }}
  button.copy-btn.copied {{ background:#a6e3a1; color:#1e1e2e; }}
  hr {{ border:none; border-top:1px solid #313244; margin:1.5rem 0; }}
  .status {{ margin-top:.5rem; font-size:.8rem; color:#6c7086; min-height:1.2em; }}
  .status.ok  {{ color:#a6e3a1; }}
  .status.err {{ color:#f38ba8; }}

  /* ── Images ── */
  .img-grid {{
    display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
    gap:.5rem; margin-top:.5rem;
  }}
  .img-grid img {{
    width:100%; aspect-ratio:1; object-fit:cover;
    border-radius:6px; border:2px solid #313244;
  }}
  .select-btn {{
    background:#89b4fa; color:#1e1e2e; border:none;
    padding:.6rem 1.25rem; border-radius:6px; cursor:pointer;
    font-weight:700; font-size:.95rem; transition:background .15s;
  }}
  .select-btn:hover {{ background:#9dc3fb; }}
  .select-btn.done  {{ background:#a6e3a1; }}
</style>
</head>
<body>
<h1>🦐 SSA Weekly AquaSwap Post</h1>
<p class="ts">Generated {date} — prices pulled live from superiorshrimpaquatics.com</p>

<div class="launch">
  <div class="launch-text">
    <strong>One click to get started.</strong> Copies your listing &amp; opens Reddit.<br>
    <ol>
      <li>Click the button → Reddit opens, listing is on your clipboard</li>
      <li>Paste the title, upload gallery photos</li>
      <li>Set flair: <strong>For Sale - Shipping Available</strong> · toggle <strong>Brand affiliate</strong></li>
      <li>Submit · come back here and copy the comment body</li>
    </ol>
  </div>
  <button class="go-btn" id="goBtn" onclick="launch()">Copy Listing &amp; Open Reddit →</button>
</div>

<div class="field">
  <label>Post Title</label>
  <input type="text" id="titleField" value="{title}" readonly>
  <div class="btn-row">
    <button class="copy-btn" onclick="copyEl('titleField', this)">Copy Title</button>
  </div>
</div>

<hr>

<div class="field">
  <label>Gallery Collages ({img_count} files — upload each to Reddit)</label>
  <div class="img-grid">{img_tags}</div>
  <div class="btn-row" style="margin-top:.75rem">
    <button class="select-btn" id="selBtn" onclick="selectAll()">
      Open &amp; Select All Photos →
    </button>
    <span style="color:#6c7086;font-size:.82rem;align-self:center">
      Then drag the selection straight into Reddit's uploader
    </span>
  </div>
  <p class="status" id="selStatus"></p>
</div>

<hr>

<div class="field">
  <label>Comment Body — paste as your first comment after submitting the gallery</label>
  <textarea id="bodyField" readonly>{body}</textarea>
  <div class="btn-row">
    <button class="copy-btn" onclick="copyEl('bodyField', this)">Copy Comment Body</button>
  </div>
  <p class="status" id="bodyStatus"></p>
</div>

<script>
const TITLE = document.getElementById('titleField').value;
const BODY  = document.getElementById('bodyField').value;
const REDDIT      = "{reddit_url}?title=" + encodeURIComponent(TITLE);
const LOCAL_PORT  = {local_port};

async function selectAll() {{
  const btn    = document.getElementById('selBtn');
  const status = document.getElementById('selStatus');
  btn.textContent = 'Opening…';
  try {{
    await fetch(`http://localhost:${{LOCAL_PORT}}/select-all`, {{method:'POST'}});
    btn.textContent = '✓ All photos selected — drag them to Reddit';
    btn.classList.add('done');
    status.textContent = "Explorer opened with all photos highlighted. Drag the selection into Reddit's gallery uploader.";
    status.className = 'status ok';
  }} catch(e) {{
    btn.textContent = 'Open & Select All Photos →';
    status.textContent = 'Could not open folder automatically — open it manually: {img_folder_url}';
    status.className = 'status err';
  }}
}}

function copyEl(id, btn) {{
  const el  = document.getElementById(id);
  const old = btn.textContent;
  el.select(); el.setSelectionRange(0, 99999);
  navigator.clipboard.writeText(el.value)
    .then(() => flash(btn, 'Copied!', old, true))
    .catch(() => {{ document.execCommand('copy'); flash(btn, 'Copied!', old, true); }});
}}

function flash(btn, msg, orig, ok) {{
  btn.textContent = msg;
  if (ok) btn.classList.add('copied');
  setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 2000);
}}

function launch() {{
  const btn = document.getElementById('goBtn');
  const status = document.getElementById('bodyStatus');
  // Copy body to clipboard (satisfies browser gesture requirement)
  navigator.clipboard.writeText(BODY)
    .then(() => {{
      status.textContent = '✓ Listing copied to clipboard';
      status.className = 'status ok';
      btn.textContent = '✓ Done — paste it as your comment';
      btn.classList.add('done');
    }})
    .catch(() => {{
      status.textContent = 'Auto-copy failed — use the Copy Comment Body button below';
      status.className = 'status err';
      btn.classList.add('partial');
      btn.textContent = 'Opening Reddit...';
    }});
  // Open Reddit with title pre-filled
  window.open(REDDIT, '_blank');
}}
</script>
</body>
</html>
"""


def build_preview_html(title, body_text, image_paths, local_port):
    escaped_title = html.escape(title, quote=True)
    escaped_body  = html.escape(body_text, quote=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    img_tags = "\n    ".join(
        f'<img src="/images/{os.path.basename(p)}" title="{os.path.basename(p)}">'
        for p in image_paths
    )

    return _HTML_TEMPLATE.format(
        date=now,
        title=escaped_title,
        body=escaped_body,
        reddit_url=REDDIT_URL,
        img_count=len(image_paths),
        img_tags=img_tags,
        img_folder_url=IMAGES_DIR.replace(os.sep, "/"),
        local_port=local_port,
    )


# ── Main ─────────────────────────────────────────────────────────────────────

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M",
    )
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))


def main():
    setup_logging()
    logging.info("=== SSA Weekly Post started ===")

    logging.info("Fetching products from superiorshrimpaquatics.com...")
    try:
        products = fetch_products()
        logging.info(f"  {len(products)} products fetched")
        listing = build_listing(products)
    except Exception as e:
        logging.error(f"Failed to build listing: {e}")
        sys.exit(1)

    if os.path.isdir(PRODUCT_IMG_DIR):
        for f in os.listdir(PRODUCT_IMG_DIR):
            try:
                os.remove(os.path.join(PRODUCT_IMG_DIR, f))
            except Exception:
                pass
        logging.info("Cleared cached product images")

    logging.info("Fetching product images from superiorshrimpaquatics.com...")
    try:
        image_infos         = fetch_product_images(products)
        total_imgs          = sum(len(v) for v in image_infos.values())
        logging.info(f"  {total_imgs} product images across {len(image_infos)} categories")
        product_image_paths = download_product_images(image_infos)
        total_dl            = sum(len(v) for v in product_image_paths.values())
        logging.info(f"  {total_dl} images downloaded")
        image_paths         = build_collages(product_image_paths)
        logging.info(f"  {len(image_paths)} collage(s) created")
    except Exception as e:
        logging.warning(f"Images unavailable ({e}) — continuing without them")
        image_paths = []

    # Build HTML once; server serves it fresh on every GET /
    html_cache = {"content": ""}
    def get_html():
        return html_cache["content"]

    local_port = start_local_server(IMAGES_DIR, get_html)
    logging.info(f"Local server running on port {local_port}")

    html_cache["content"] = build_preview_html(POST_TITLE, listing, image_paths, local_port)

    url = f"http://localhost:{local_port}/"
    webbrowser.open(url)
    logging.info(f"Preview opened: {url}")
    logging.info("Close this window when you're done posting.")

    # Keep the process alive so the local server stays up
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
