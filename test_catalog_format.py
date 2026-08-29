#!/usr/bin/env python3
"""The columnar products.json, and every reader that has to agree with it.

WHY THIS EXISTS
products.json is fetched BEFORE the load event, so its bytes are splash-screen
time on a booth visitor's phone. Columnar + interned + no derivable `img` takes
it from 10.7 MB to 2.2 MB raw, 805 KB to 435 KB gzipped.

The risk is not the encoding, it is the SEAM. Four things read this file:

    generate-prices.mjs   writes it (and its shrink guard reads the old one)
    index.html            decodeCatalog()
    make_hashes.py        builds the dHash database, on a schedule
    test_scan_accuracy.py the scanner's accuracy fixture

make_hashes.py is the dangerous one: it filters rows for `type == "single"` and
an `img`, then commits hashes.json back to this repo from a GitHub Action. Fed
an object instead of a list it would match nothing, write a hash database built
from zero cards, push it, and report success. The generator's shrink guard has
the same shape -- it was `Array.isArray(prev)`, which goes quietly false on the
new format and turns the guard into a no-op that passes every run.

So this file asserts the ROUND TRIP on the real committed catalogue, that both
shapes decode, and that a decoder fed the wrong thing raises instead of
returning an empty list that looks like a quiet day.

Run:  python3 test_catalog_format.py
"""
import gzip
import json
import os
import re
import sys

import catalog

HERE = os.path.dirname(os.path.abspath(__file__))
passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        passed = False
    return cond


raw = json.load(open(os.path.join(HERE, "products.json")))
rows = catalog.decode(raw)

print("1. the committed catalogue is in the compact form and decodes")
check(f"products.json is columnar (f={raw.get('f') if isinstance(raw, dict) else 'array'})",
      isinstance(raw, dict) and raw.get("f") == 2)
check(f"it decodes to a plausible number of rows ({len(rows)})", len(rows) > 50000)
check("every row has the six fields the app expects",
      all({"id", "name", "set", "type", "status", "img"} <= set(r) for r in rows[:2000]))

print("\n2. img is rebuilt exactly, not approximately")
# The whole saving rests on this being derivable with zero exceptions. If even
# one row needed a different URL, dropping the field would break that card's
# image silently -- a blank thumbnail nobody reports.
bad = [r["id"] for r in rows
       if r["img"] != f"https://tcgplayer-cdn.tcgplayer.com/product/{r['id']}_200w.jpg"]
check(f"all {len(rows)} rebuilt image URLs match the pattern ({len(bad)} bad)", not bad)

print("\n3. both wire shapes decode (a rollout has both live at once)")
# A GitHub Action rewrites this file daily and a Service Worker can serve a
# cached copy for as long as a tab stays open, so the old shape must keep working.
legacy = [{"id": "1", "name": "A", "set": "S", "type": "single",
           "status": "raw", "img": "http://x/1_200w.jpg"}]
check("a bare row array is passed through untouched",
      catalog.decode(legacy) == legacy)
check("the columnar form decodes to the same shape",
      set(catalog.decode(raw)[0].keys()) == set(legacy[0].keys()))

print("\n4. the decoder refuses rather than returning nothing")
# An empty list is the failure this codebase keeps shipping: it reads exactly
# like a working catalogue that happens to be empty.
for label, bad_input in [("a string", "nope"), ("a number", 7),
                         ("an object with no id column", {"sets": [], "name": []})]:
    try:
        catalog.decode(bad_input)
        check(f"{label} raises instead of decoding to []", False)
    except ValueError:
        check(f"{label} raises instead of decoding to []", True)
    except Exception as e:
        check(f"{label} raises ValueError (got {type(e).__name__})", False)

print("\n5. the readers that are not the app")
mh = open(os.path.join(HERE, "make_hashes.py")).read()
check("make_hashes.py decodes through catalog, not json.load",
      "catalog.decode" in mh)
sa = open(os.path.join(HERE, "test_scan_accuracy.py")).read()
check("test_scan_accuracy.py does too", "catalog.decode" in sa)
# And prove it in behaviour, not just in text: the singles filter must still
# find cards. This is the exact expression make_hashes.py runs.
singles = [p for p in rows if p.get("type") == "single" and p.get("img")]
check(f"the singles filter still finds cards ({len(singles)})", len(singles) > 10000)

print("\n6. the generator's shrink guard survived the format change")
gen = open(os.path.join(HERE, "generate-prices.mjs")).read()
check("generate-prices.mjs writes the encoded form",
      "encodeCatalog(products)" in gen)
# Array.isArray(prev) would be silently false forever on the new shape, so the
# guard would 'pass' every run while checking nothing.
check("...and its shrink guard no longer relies on Array.isArray",
      "catalogLength(prev)" in gen)
m = re.search(r"function catalogLength\(v\) \{[\s\S]*?\n\}", gen)
check("catalogLength exists to count either shape", bool(m))

print("\n7. the size claim is real")
p = os.path.join(HERE, "products.json")
gz = len(gzip.compress(open(p, "rb").read(), 9))
check(f"gzipped products.json is under 500 KB ({gz/1024:.0f} KB)", gz < 500 * 1024)

print("\n8. history.json: shared date axis, and the daily append cycle")
# 29,223 products x up to 47 daily points, each written as {"d":...,"p":...} --
# 1.2 million copies of two key names and of a date string shared file-wide.
# 35.25MB -> 7.11MB raw, 3.377MB -> 0.825MB gzipped.
#
# The round trip is the easy half. The DANGEROUS half is the append cycle: the
# daily Action reads history.json, adds today's prices, and writes it back. Get
# that wrong against the new shape and history degrades a little every night,
# invisibly, until a sparkline is a straight line and nobody can say when it
# started. So the cycle is simulated here, not just the encoding.
hraw = json.load(open(os.path.join(HERE, "history.json")))
check(f"history.json is columnar (f={hraw.get('f') if isinstance(hraw, dict) else '?'})",
      isinstance(hraw, dict) and hraw.get("f") == 2)
check(f"it carries a shared date axis ({len(hraw.get('d', []))} dates)",
      isinstance(hraw.get("d"), list) and len(hraw["d"]) > 5)
check(f"and one row per product ({len(hraw.get('p', {}))})",
      len(hraw.get("p", {})) > 10000)
check("every row is the same length as the date axis",
      all(len(v) == len(hraw["d"]) for v in list(hraw["p"].values())[:3000]))

# Exercise the GENERATOR'S OWN functions, so the test cannot drift from the job.
import subprocess, tempfile
_harness = r"""
import fs from 'fs';
const gen = fs.readFileSync(process.argv[2],'utf8');
const enc = gen.match(/function encodeHistory\(hist\) \{[\s\S]*?\n\}/)[0];
const dec = gen.match(/function decodeHistory\(raw\) \{[\s\S]*?\n\}/)[0];
const M = new Function(enc+'\n'+dec+'\nreturn {encodeHistory, decodeHistory};')();
const wire0 = JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const rows = M.decodeHistory(wire0);
const rt = JSON.stringify(M.decodeHistory(JSON.parse(JSON.stringify(M.encodeHistory(rows)))))
         === JSON.stringify(rows);
const ids = Object.keys(rows).slice(0, 500);
const prices = {}; ids.forEach((id,i)=>prices[id]=10+(i%40));
let wire = JSON.stringify(wire0);
for (const day of ['2099-01-01','2099-01-02']) {
  const h = M.decodeHistory(JSON.parse(wire));
  for (const [id,pr] of Object.entries(prices)) {
    if (!h[id]) h[id]=[];
    if (!h[id].some(p=>p.d===day)) h[id].push({d:day,p:pr});
  }
  wire = JSON.stringify(M.encodeHistory(h));
}
const after = M.decodeHistory(JSON.parse(wire));
const untouched = Object.keys(rows).find(k=>!(k in prices));
console.log(JSON.stringify({
  roundTrip: rt,
  grew: after[ids[0]].filter(p=>p.d.startsWith('2099')).length === 2,
  kept: JSON.stringify(after[untouched])===JSON.stringify(rows[untouched]),
  count: Object.keys(after).length === Object.keys(rows).length}));
"""
with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
    fh.write(_harness); _hp = fh.name
_out = subprocess.run(["node", _hp, os.path.join(HERE, "generate-prices.mjs"),
                       os.path.join(HERE, "history.json")],
                      capture_output=True, text=True, timeout=600)
os.unlink(_hp)
check(f"the node harness ran (rc={_out.returncode})", _out.returncode == 0)
_r = json.loads(_out.stdout) if _out.returncode == 0 and _out.stdout.strip() else {}
check("round trip through the generator's own encode/decode is lossless",
      _r.get("roundTrip") is True)
check("two simulated daily appends both land",
      _r.get("grew") is True)
check("a product absent from the day's prices keeps its history",
      _r.get("kept") is True)
check("no product is lost across the cycle", _r.get("count") is True)

hgz = len(gzip.compress(open(os.path.join(HERE, "history.json"), "rb").read(), 9))
check(f"gzipped history.json is under 1 MB ({hgz/1e6:.2f} MB)", hgz < 1_000_000)

print("\n9. price coverage")
# Sealed is the commercial surface: every drop, margin and flip number is a
# sealed product, so an unpriced one is a drop the app cannot value. It has been
# 100% and must stay there -- a silent slip would show as drops with no margin,
# which reads exactly like a quiet market.
_pr = json.load(open(os.path.join(HERE, "prices.json")))
_sealed = [r for r in rows if r["type"] == "sealed"]
_singles = [r for r in rows if r["type"] == "single"]
def _priced(rs):
    return [r for r in rs if isinstance(_pr.get(r["id"]), (int, float)) and _pr[r["id"]] > 0]
_sp, _gp = _priced(_sealed), _priced(_singles)
check(f"every sealed product has a price ({len(_sp)}/{len(_sealed)})",
      len(_sp) == len(_sealed))
# Singles will never be 100%: TCGcsv carries no price of any type for ~5k mostly
# promo cards, verified by sampling 124 of them against the upstream API and
# finding a price for zero. The floor guards against a pipeline regression, not
# against those.
_ratio = len(_gp) / max(1, len(_singles))
check(f"singles coverage has not regressed ({_ratio*100:.1f}%, floor 88%)",
      _ratio >= 0.88)
# And an unpriced card must read as unknown, never as free.
check("no product is priced at zero rather than absent",
      not [k for k, v in _pr.items() if isinstance(v, (int, float)) and v == 0])

print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
