#!/usr/bin/env python3
"""
Scanner accuracy, and the invariant that makes the ambiguity UI a real safety net.

Run:      python3 test_scan_accuracy.py
Fixtures: python3 test_scan_accuracy.py --fetch     (downloads 60 card images)

The scanner is the feature you hand a stranger's phone to, so "does it work" had
never actually been measured -- only assumed. Measured on 60 random singles,
degraded to look like phone photos (0.55 scale, 2 degrees of rotation, brighter,
slightly blurred, JPEG 70):

    top-1 correct          51/60   85%
    correct within top-3   58/60   97%
    gap 1->2, top-1 RIGHT  median 14   (p25 6, p75 19)
    gap 1->2, top-1 WRONG  median  2   (p25 1, p75 3, MAX 3)

The last two lines are the whole point. The distance gap between the best and
second-best match is strongly bimodal: wide when the answer is right, nearly
zero when it is wrong. Wrong answers are wrong because the runner-up is the SAME
CARD in a different printing -- a stamped Energy, a Secret Rare, an alternate
art -- which a 17x16 dHash cannot separate and a human holding the card can.

AMBIG_BAND=10 sits in the gap between those two modes, which is why the app's
design works: inside the band it OCRs the collector-number strip and re-ranks,
then shows a list instead of committing. Every wrong top-1 in the sample landed
inside the band, so the tiebreak gets a shot at all of them.

THE INVARIANT, and the reason this file exists: a wrong top-1 must never fall
OUTSIDE the band. Outside the band the app commits silently and shows one
confident answer -- and since printings differ in price (a Secret Rare against
its regular is real money), a silent wrong printing is a wrong valuation with
nobody's hand on the wheel. Raw accuracy drifting down is a quality problem;
this invariant breaking is a correctness one.

Images are gitignored: they are ~60 fetches from the TCGplayer CDN, not repo
content. Without them this SKIPS loudly rather than passing on nothing.
"""
import json
import os
import sys
import random
import http.server
import threading
import functools
import statistics
import urllib.request
import concurrent.futures as cf

ROOT = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(ROOT, ".lotfix", "cards")
MANIFEST = os.path.join(CARDS, "manifest60.json")
PORT = 8817

HASH_OK = 84        # must match index.html
AMBIG_BAND = 10     # must match index.html

# Floors, set below measured behaviour so normal variation is not a failure.
MIN_TOP1 = 0.75
MIN_TOP3 = 0.90

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    passed &= bool(cond)


def skip(label, why):
    print(f"  [SKIP] {label} -- {why}")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve():
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", PORT), functools.partial(Handler, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def fetch_fixtures(n=60, seed=42):
    """One-off: pull n random singles that have both a hash and an image."""
    os.makedirs(CARDS, exist_ok=True)
    hashes = set(json.load(open(os.path.join(ROOT, "hashes.json"))).keys())
    import catalog
    prods = catalog.decode(json.load(open(os.path.join(ROOT, "products.json"))))
    pool = [p for p in prods
            if p.get("type") == "single" and p.get("img") and str(p["id"]) in hashes]
    random.seed(seed)
    pick = random.sample(pool, n)

    def grab(p):
        dest = os.path.join(CARDS, f"{p['id']}.jpg")
        if os.path.exists(dest) and os.path.getsize(dest) > 2000:
            return p
        try:
            req = urllib.request.Request(p["img"], headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                open(dest, "wb").write(r.read())
            return p
        except Exception:
            return None

    with cf.ThreadPoolExecutor(8) as ex:
        got = [x for x in ex.map(grab, pick) if x]
    man = [{"id": str(p["id"]), "name": p.get("name", "")[:44]} for p in got]
    json.dump(man, open(MANIFEST, "w"))
    print(f"fetched {len(man)} card images -> {CARDS}")
    return man


# The same degradation for every card, so a run is comparable to the last one.
PROBE = r"""
async (cards) => {
  const load = s => new Promise((ok, no) => {
    const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = s;
  });
  const out = [];
  for (const c of cards) {
    let img;
    try { img = await load('.lotfix/cards/' + c.id + '.jpg'); } catch (e) { continue; }
    // Stand-in for a phone photo: smaller, slightly rotated, brighter, softer,
    // and re-encoded lossily. Not a substitute for real photographs, but it
    // exercises every step the pristine reference image would skip.
    const w = Math.round(img.naturalWidth * 0.55), h = Math.round(img.naturalHeight * 0.55);
    const d = document.createElement('canvas'); d.width = w; d.height = h;
    const dx = d.getContext('2d');
    dx.translate(w / 2, h / 2); dx.rotate(2 * Math.PI / 180); dx.translate(-w / 2, -h / 2);
    dx.filter = 'brightness(1.12) contrast(0.94) blur(0.4px)';
    dx.drawImage(img, 0, 0, w, h);
    const i2 = await load(d.toDataURL('image/jpeg', 0.7));
    const e = document.createElement('canvas');
    e.width = i2.naturalWidth; e.height = i2.naturalHeight;
    e.getContext('2d').drawImage(i2, 0, 0);
    out.push({ id: c.id, name: c.name,
               top: (CardHash.match(e, 12) || []).map(x => ({ id: String(x.id), dist: x.dist })) });
  }
  return out;
}
"""

if "--fetch" in sys.argv:
    fetch_fixtures()

if not os.path.exists(MANIFEST):
    print("\n0. fixtures")
    skip("scanner accuracy", f"no card images. Run: python3 {os.path.basename(__file__)} --fetch")
    print("\nSKIPPED (not a pass)")
    sys.exit(0)

cards = json.load(open(MANIFEST))
sys.path.insert(0, ROOT)
import shots  # noqa: E402  (tour dismissal that waits properly)
from playwright.sync_api import sync_playwright  # noqa: E402

print(f"\n0. {len(cards)} card fixtures")
httpd = serve()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
    page.add_init_script(shots.FREEZE_JS)
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    for _ in range(500):
        if page.evaluate("window.CatalogState") == "ready":
            break
        page.wait_for_timeout(50)
    shots.dismiss_tour(page)
    ready = page.evaluate("async ()=>{try{return await CardHash.ready();}catch(e){return false;}}")
    check("the hash database loads", ready is True)
    if ready is not True:
        browser.close(); httpd.shutdown()
        print("\nFAIL"); sys.exit(1)

    res = page.evaluate(PROBE, cards)
    ctx.close()
    browser.close()
httpd.shutdown()

scored = [r for r in res if r["top"] and r["top"][0]["dist"] <= HASH_OK]
n = len(scored)
print(f"\n1. accuracy on {n} scored / {len(res)} probed")
if not n:
    check("anything matched at all", False)
    print("\nFAIL"); sys.exit(1)

top1 = sum(1 for r in scored if r["top"][0]["id"] == r["id"])
top3 = sum(1 for r in scored if r["id"] in [x["id"] for x in r["top"][:3]])
check(f"top-1 correct {top1}/{n} ({top1/n:.0%}) >= {MIN_TOP1:.0%}", top1 / n >= MIN_TOP1)
check(f"correct within top-3 {top3}/{n} ({top3/n:.0%}) >= {MIN_TOP3:.0%}", top3 / n >= MIN_TOP3)

right, wrong = [], []
for r in scored:
    t = r["top"]
    gap = (t[1]["dist"] - t[0]["dist"]) if len(t) > 1 else 10 ** 6
    (right if t[0]["id"] == r["id"] else wrong).append((gap, r))

print("\n2. the gap between best and runner-up separates right from wrong")
for lbl, g in (("right", right), ("wrong", wrong)):
    vals = sorted(x[0] for x in g if x[0] < 10 ** 6)
    if vals:
        print(f"    top-1 {lbl:5s}: n={len(vals):3d} median={statistics.median(vals):5.0f} "
              f"min={vals[0]:3d} max={vals[-1]:3d}")
    else:
        print(f"    top-1 {lbl:5s}: none")

# THE INVARIANT. Inside the band the app OCRs the collector number and offers a
# list; outside it, one answer is committed silently. A wrong answer must never
# land outside, because printings differ in price and nobody would be asked.
escaped = [(g, r) for g, r in wrong if g > AMBIG_BAND]
print(f"\n3. every wrong answer stays inside AMBIG_BAND={AMBIG_BAND}")
check(f"no wrong top-1 escapes the ambiguity path ({len(escaped)} escaped of {len(wrong)} wrong)",
      not escaped)
for g, r in escaped[:6]:
    print(f"      gap={g:3d}  {r['name'][:44]}")

# Negative control: the invariant above is only meaningful if the band is not so
# wide that it swallows everything. A band covering every scan would pass check 3
# trivially while making the tiebreak fire on every single card.
noisy = [g for g, _ in right if g <= AMBIG_BAND]
print("\n4. ...and the band is not so wide it fires on everything")
check(f"most correct scans are decided outright "
      f"({len(right) - len(noisy)}/{len(right)} clear the band)",
      len(right) and (len(right) - len(noisy)) / len(right) >= 0.5)

print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
