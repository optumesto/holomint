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

print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
