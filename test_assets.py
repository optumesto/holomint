#!/usr/bin/env python3
"""Every asset the app asks for is actually served.

WHY THIS EXISTS
eng.traineddata was uploaded through the GitHub web UI, which created a
DIRECTORY of that name containing a file of the same name. The only working URL
was /eng.traineddata/eng.traineddata. tesseract.js asks for /eng.traineddata,
got a 404, and the scanner sat on "Loading scanner…" forever with no error
shown. Ten green suites reported health throughout, because none of them ever
started the OCR worker.

The file was present on disk the whole time. `os.path.isfile` would have said
yes. Presence is not reachability, and this suite tests reachability.

TWO KINDS OF REFERENCE, and the second is the one that bit:

  STATIC   `src="cardfind.js"`, manifest icons, sw.js SHELL entries. Greppable.
  RUNTIME  paths a library builds itself from config -- tesseract.js turns
           langPath + lang into `${langPath}/${lang}.traineddata`. Invisible to
           any amount of source scanning, so those are listed by hand below and
           the list is the point of the file.

Run:  python3 test_assets.py
"""
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8831
passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        passed = False
    return cond


# Paths no static scan can find, because a library assembles them at runtime.
# ADD TO THIS LIST whenever a dependency is configured with a base path rather
# than a literal URL. It is short on purpose; if it grows past a handful,
# something is being configured too cleverly.
RUNTIME_ASSETS = [
    # tesseract.js: `${langPath}/${lang}.traineddata`, plus `.gz` unless
    # gzip:false. This exact path 404'd in production.
    "eng.traineddata",
]


def static_refs():
    refs = set()
    html = open(os.path.join(HERE, "index.html")).read()
    pats = [
        r'src=["\']\.?/?([A-Za-z0-9_\-./]+\.(?:js|png|jpg|svg|webp|json|wasm))["\']',
        r'href=["\']\.?/?([A-Za-z0-9_\-./]+\.(?:css|png|ico|json|webmanifest))["\']',
        r"['\"]\./([A-Za-z0-9_\-./]+\.(?:js|json|wasm|traineddata))['\"]",
        r"fetch\(['\"]\.?/?([A-Za-z0-9_\-./]+\.(?:json|traineddata))['\"]",
    ]
    for p in pats:
        refs |= set(re.findall(p, html))
    sw = open(os.path.join(HERE, "sw.js")).read()
    refs |= set(re.findall(
        r'["\']\.?/([A-Za-z0-9_\-./]+\.(?:png|json|js|traineddata))["\']', sw))
    man = json.load(open(os.path.join(HERE, "manifest.json")))
    for i in man.get("icons", []):
        refs.add(i["src"].lstrip("./"))
    for s in man.get("screenshots", []):
        refs.add(s["src"].lstrip("./"))
    return {r for r in refs if r and not r.startswith("http")}


handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)


class Q(socketserver.TCPServer):
    allow_reuse_address = True


httpd = Q(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()


# What a real asset should weigh, so a 200 carrying the wrong thing is caught.
MIN_BYTES = {"eng.traineddata": 1_000_000}


def fetch(path):
    """(status, bytes, content_type) over HTTP -- not from the filesystem.

    Deliberately reads the WHOLE body and looks at the type. Status alone is not
    proof: Python's dev server answers a directory request with a 200 and an
    HTML index, so the nested-directory layout that broke production passed this
    check until the body was inspected. GitHub Pages 404s the same request --
    which is exactly the kind of difference between a dev server and the real
    one that lets a bug through.
    """
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/{path}", timeout=60)
        body = r.read()
        return r.status, len(body), (r.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as e:
        return e.code, 0, ""
    except Exception as e:
        return str(e)[:40], 0, ""


def served_ok(path):
    """True only if the response is plausibly the asset itself."""
    st, n, ct = fetch(path)
    if st != 200 or n == 0:
        return False, f"{st}"
    # A directory listing comes back as HTML. No asset here is HTML.
    if not path.endswith((".html", ".htm")) and "text/html" in ct:
        return False, f"200 but text/html ({n}B) -- a directory listing?"
    floor = MIN_BYTES.get(path)
    if floor and n < floor:
        return False, f"200 but only {n}B, expected >{floor}B"
    return True, f"{st} {n}B"


try:
    refs = sorted(static_refs())
    print(f"1. static references ({len(refs)} found)")
    check("the scan finds a plausible number of assets", len(refs) >= 10)
    broken = []
    for r in refs:
        ok, why = served_ok(r)
        if not ok:
            broken.append((r, why))
    check(f"every statically-referenced asset is served ({broken or 'none broken'})",
          not broken)

    print("\n2. runtime-constructed paths")
    # The whole reason this file exists. A library builds these from a base
    # path, so no amount of grepping the source will reveal them.
    rt_broken = []
    for r in RUNTIME_ASSETS:
        ok, why = served_ok(r)
        if not ok:
            rt_broken.append((r, why))
    check(f"every runtime asset is served ({rt_broken or 'none broken'})",
          not rt_broken)

    for r in RUNTIME_ASSETS:
        p = os.path.join(HERE, r)
        # The exact failure: a DIRECTORY named like the file. os.path.exists()
        # says yes to both, which is why presence was never the right question.
        check(f"{r} is a file, not a directory named like one",
              os.path.isfile(p) and not os.path.isdir(p))

    print("\n3. the OCR config that decides which path is requested")
    html = open(os.path.join(HERE, "index.html")).read()
    workers = html.count("createWorker(")
    check(f"gzip:false on every createWorker ({workers} call(s)) — without it "
          "tesseract asks for .traineddata.gz, which we do not ship",
          workers > 0 and html.count("gzip:false") >= workers)

    print("\n4. the guard can fail")
    # A reachability check that cannot go red is just a slow no-op.
    ok, why = served_ok("definitely-not-a-real-asset-xyz.json")
    check(f"a missing asset is reported broken (got {why})", not ok)
finally:
    httpd.shutdown()

print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
