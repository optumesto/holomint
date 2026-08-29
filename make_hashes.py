#!/usr/bin/env python3
"""
Holomint card-hash generator
============================
Builds hashes.json: a perceptual-hash fingerprint for every single in your
catalog, so the in-app scanner can identify a cropped photo by image match
(robust to blur/lighting) instead of fragile text OCR.

WHAT IT DOES
  1. Reads products.json (local file, or downloads it from your repo).
  2. For every product with type == "single" and an "img" URL, downloads the
     TCGplayer card image and computes a 256-bit difference-hash (dHash).
  3. Writes hashes.json  ->  { "<productId>": "<64-char-hex dHash>", ... }

WHY dHash
  dHash compares left->right brightness gradients on a tiny 16x17 grid. It is
  insensitive to scale, brightness, and mild blur, which is exactly what we need
  to match a phone photo against the clean reference image. The IN-APP matcher
  computes this hash the EXACT same way (same grid, same grayscale formula, same
  bit order) — do not change one side without the other.

REQUIREMENTS
  pip install pillow

RUN  (from your holomint repo folder, where products.json lives)
  python3 make_hashes.py
  # then commit the produced hashes.json to the repo so the PWA can fetch it.

NOTES
  * Resumable: re-running skips productIds already in hashes.json. Safe to stop
    (Ctrl-C) and restart — it checkpoints every 500 cards.
  * ~60k images is a big one-time download (roughly an hour, less with more
    workers). You can also run a subset first to validate: see ONLY_SETS below.
"""

import json, os, sys, time, urllib.request, urllib.error, io
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required:  pip install pillow")

# ---------------------------------------------------------------- config
PRODUCTS_PATH   = "products.json"
PRODUCTS_URL    = "https://raw.githubusercontent.com/optumesto/holomint/main/products.json"
OUT_PATH        = "hashes.json"
WORKERS         = 16          # parallel downloads (raise cautiously)
TIMEOUT         = 15          # seconds per request
RETRIES         = 3
CHECKPOINT      = 500         # write hashes.json every N new cards
ONLY_SETS       = None        # e.g. {"SV09: Journey Together"} to test a subset; None = all
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------------------------------------------------------------- dHash (REFERENCE IMPLEMENTATION)
# Grid is 17 wide x 16 tall. For each of 16 rows, compare each of 16 adjacent
# horizontal pairs -> 16*16 = 256 bits, packed row-major, MSB-first per byte.
HASH_W, HASH_H = 17, 16

def _lum(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]

def dhash_hex(im: "Image.Image") -> str:
    # resize (color) -> float luminance -> horizontal-gradient bits.
    # Mirrors the in-app canvas path: drawImage(17x16) then 0.299/0.587/0.114.
    im = im.convert("RGB").resize((HASH_W, HASH_H), Image.BILINEAR)
    px = im.load()
    bits = bytearray(32)            # 256 bits
    i = 0
    for row in range(HASH_H):
        for col in range(HASH_H):   # 16 comparisons per row (cols 0..15 vs 1..16)
            if _lum(px[col, row]) < _lum(px[col + 1, row]):
                bits[i >> 3] |= (1 << (7 - (i & 7)))
            i += 1
    return bits.hex()

# ---------------------------------------------------------------- io helpers
def load_products():
    # products.json is columnar now; catalog.decode handles both that and the
    # older bare array. Without it this function returns a dict, the "single"
    # filter below matches nothing, and this script cheerfully writes a
    # hashes.json built from zero cards -- on a schedule, straight into the
    # repo, with a green run.
    import catalog
    if os.path.exists(PRODUCTS_PATH):
        with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
            return catalog.decode(json.load(f))
    print("products.json not found locally — downloading from repo...")
    req = urllib.request.Request(PRODUCTS_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return catalog.decode(json.loads(r.read().decode("utf-8")))

def fetch_image(url: str):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
            return Image.open(io.BytesIO(data))
        except Exception as e:                       # noqa
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last

# ---------------------------------------------------------------- main
def main():
    products = load_products()
    singles = [p for p in products
               if p.get("type") == "single" and p.get("img") and p.get("id")
               and (ONLY_SETS is None or p.get("set") in ONLY_SETS)]
    print(f"{len(singles)} singles with images.")

    done = {}
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                done = json.load(f)
            print(f"Resuming — {len(done)} already hashed.")
        except Exception:
            done = {}

    todo = [p for p in singles if p["id"] not in done]
    print(f"{len(todo)} to do.")
    if not todo:
        print("Nothing to do. hashes.json is complete.")
        return

    ok = fail = 0
    start = time.time()

    def work(p):
        try:
            im = fetch_image(p["img"])
            return p["id"], dhash_hex(im), None
        except Exception as e:                       # noqa
            return p["id"], None, str(e)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(work, p) for p in todo]
        since_ckpt = 0
        for fut in as_completed(futures):
            pid, h, err = fut.result()
            if h:
                done[pid] = h
                ok += 1
                since_ckpt += 1
            else:
                fail += 1
                if fail <= 25:
                    print(f"  fail {pid}: {err}")
            n = ok + fail
            if n % 200 == 0:
                rate = n / max(1e-6, time.time() - start)
                eta = (len(todo) - n) / max(1e-6, rate)
                print(f"  {n}/{len(todo)}  ok={ok} fail={fail}  "
                      f"{rate:.1f}/s  eta {eta/60:.1f} min")
            if since_ckpt >= CHECKPOINT:
                with open(OUT_PATH, "w", encoding="utf-8") as f:
                    json.dump(done, f, separators=(",", ":"))
                since_ckpt = 0

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(done, f, separators=(",", ":"))

    size_mb = os.path.getsize(OUT_PATH) / 1e6
    print(f"\nDone. {ok} hashed this run, {fail} failed. "
          f"Total in hashes.json: {len(done)}.  ({size_mb:.1f} MB)")
    print("Commit hashes.json to the repo so the PWA can fetch it.")

if __name__ == "__main__":
    main()
