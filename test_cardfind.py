#!/usr/bin/env python3
"""
Card detection accuracy, scored against fixtures with known card corners.

Run:  python3 test_cardfind.py
Needs: pip install -r requirements-dev.txt && python3 -m playwright install chromium

Scored, not pass/fail-on-everything, because "find every card in any photo" is
not achievable and pretending otherwise produces a test that is either always
red or quietly weakened until it means nothing. Each fixture carries its OWN
expectation, and the hard ones are honest about being hard:

  * fanned -- eight cards each covering the last. dHash needs a whole card face,
    so the occluded ones are not a segmentation failure that better code fixes.
    The bar is deliberately low, and the manual box editor is the real answer.
  * listing -- the thumbnails are cards; the app bar, title and buttons are not.
    Precision matters more here than recall.

A per-fixture floor also means a regression shows up as the specific case that
broke, rather than one aggregate number drifting.
"""
import os
import re
import sys
import json
import time
import http.server
import threading
import functools

from playwright.sync_api import sync_playwright

import lotfixtures

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8809
FIXDIR = os.path.join(ROOT, ".lotfix")
IOU_HIT = 0.55          # a detection counts as "that card" above this

# fixture -> (min recall, max false positives). Set from measured behaviour, and
# tightened deliberately -- never widened to make a run go green.
BAR = {
    "rough_rows": (0.85, 2),
    "scattered":  (0.75, 2),
    "binder":     (0.85, 2),
    "listing":    (0.60, 3),
    "fanned":     (0.10, 4),
    # The three that model Mason's real photos. Every sample he sent was a
    # sleeved binder page -- angled, partly out of frame, or under glare -- so
    # these carry the highest bars in the file. If the detector is good at
    # exactly one thing, it has to be this.
    "binder_angled":  (0.85, 2),
    "binder_partial": (0.80, 3),
    "binder_glare":   (0.70, 3),
}

passed = True
notes = []


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    passed &= bool(cond)


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


def poly_iou(a, b):
    """IoU of two convex quads, via shoelace on the Sutherland-Hodgman clip.
    Axis-aligned boxes would flatter a rotated detection that is barely on the
    card, so the real polygons are used."""
    def area(p):
        s = 0.0
        for i in range(len(p)):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % len(p)]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2

    def clip(subject, cx1, cy1, cx2, cy2):
        out = []
        n = len(subject)
        for i in range(n):
            cur = subject[i]
            prv = subject[(i - 1) % n]
            side = lambda p: (cx2 - cx1) * (p[1] - cy1) - (cy2 - cy1) * (p[0] - cx1)
            sc, sp = side(cur), side(prv)
            if sc >= 0:
                if sp < 0:
                    t = sp / (sp - sc)
                    out.append([prv[0] + t * (cur[0] - prv[0]),
                                prv[1] + t * (cur[1] - prv[1])])
                out.append(cur)
            elif sp >= 0:
                t = sp / (sp - sc)
                out.append([prv[0] + t * (cur[0] - prv[0]),
                            prv[1] + t * (cur[1] - prv[1])])
        return out

    # Orient both CCW so the clip half-planes point the same way.
    def ccw(p):
        s = 0.0
        for i in range(len(p)):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % len(p)]
            s += x1 * y2 - x2 * y1
        return p if s > 0 else p[::-1]

    A, B = ccw([list(p) for p in a]), ccw([list(p) for p in b])
    poly = A
    for i in range(len(B)):
        if not poly:
            return 0.0
        x1, y1 = B[i]
        x2, y2 = B[(i + 1) % len(B)]
        poly = clip(poly, x1, y1, x2, y2)
    inter = area(poly) if poly else 0.0
    union = area(A) + area(B) - inter
    return inter / union if union > 0 else 0.0


print("0. fixtures")
lotfixtures.build(FIXDIR)
truth = json.load(open(os.path.join(FIXDIR, "truth.json")))

httpd = serve()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page.goto(f"http://127.0.0.1:{PORT}/.lotfix/", wait_until="domcontentloaded")
    # Cache-buster: without it Chromium serves a previously fetched cardfind.js
    # and the whole run silently scores the OLD detector. Two runs printing
    # identical numbers across a real code change is the tell.
    page.add_script_tag(url=f"http://127.0.0.1:{PORT}/cardfind.js?v={time.time()}")
    check("CardFind loaded", page.evaluate("()=>typeof CardFind==='object'"))
    # Pin that the build under test is the current one, by a symbol that only
    # exists in it. A stale script would pass every check above this line.
    check("...and it is the current build (byCardScale present)",
          page.evaluate("()=>typeof CardFind._byCardScale==='function'"))

    print("\n1. geometry primitives")
    # A square hull's minimum-area rectangle is that square. If this is wrong,
    # every accuracy number below is measuring a broken primitive.
    sq = page.evaluate("""()=>{const r=CardFind._minAreaRect(
        [[0,0],[100,0],[100,100],[0,100]]);return r?{w:Math.round(r.w),h:Math.round(r.h),
        area:Math.round(r.area)}:null;}""")
    check(f"minAreaRect of a square is that square (got {sq})",
          sq and sq["w"] == 100 and sq["h"] == 100)
    # Rotated 45 degrees, the tight box is the diamond's own side, not its AABB.
    dia = page.evaluate("""()=>{const r=CardFind._minAreaRect(
        [[50,0],[100,50],[50,100],[0,50]]);
        return r?{w:+r.w.toFixed(1),h:+r.h.toFixed(1)}:null;}""")
    check(f"...and of a 45-degree diamond is its side, ~70.7 (got {dia})",
          dia and abs(dia["w"] - 70.7) < 1.5 and abs(dia["h"] - 70.7) < 1.5)
    iou_self = page.evaluate("""()=>CardFind._iou([[0,0],[10,0],[10,10],[0,10]],
                                                  [[0,0],[10,0],[10,10],[0,10]])""")
    check(f"iou of a box with itself is 1 (got {iou_self})", abs(iou_self - 1) < 1e-6)
    iou_off = page.evaluate("""()=>CardFind._iou([[0,0],[10,0],[10,10],[0,10]],
                                                 [[50,50],[60,50],[60,60],[50,60]])""")
    check(f"iou of disjoint boxes is 0 (got {iou_off})", iou_off == 0)

    print("\n2. detection against known corners")
    print(f"  {'fixture':12s} {'cards':>5} {'found':>6} {'hit':>4} {'recall':>7} "
          f"{'extra':>6} {'medIoU':>7}")
    print("  " + "-" * 56)
    for name, meta in truth.items():
        got = page.evaluate("""async (f)=>{
            const img=new Image();img.src=f;await img.decode();
            const c=document.createElement('canvas');
            c.width=img.naturalWidth;c.height=img.naturalHeight;
            c.getContext('2d').drawImage(img,0,0);
            return CardFind.detect(c).map(d=>d.quad);
        }""", meta["file"])
        cards = meta["cards"]
        used, ious = set(), []
        for gi, g in enumerate(got):
            best, bi = 0.0, -1
            for ci, c in enumerate(cards):
                if ci in used:
                    continue
                v = poly_iou(g, c)
                if v > best:
                    best, bi = v, ci
            if best >= IOU_HIT:
                used.add(bi)
                ious.append(best)
        hit = len(used)
        recall = hit / len(cards) if cards else 0
        extra = len(got) - hit
        med = sorted(ious)[len(ious) // 2] if ious else 0.0
        print(f"  {name:12s} {len(cards):5d} {len(got):6d} {hit:4d} {recall:7.0%} "
              f"{extra:6d} {med:7.2f}")
        notes.append((name, recall, extra, med))

    print()
    for name, recall, extra, med in notes:
        floor, maxfp = BAR[name]
        check(f"{name}: recall {recall:.0%} >= {floor:.0%}", recall >= floor)
        check(f"{name}: {extra} false positive(s) <= {maxfp}", extra <= maxfp)

    print("\n3. the crop is square and upright")
    # The point of all of this: what CardHash receives. A correct crop of a
    # rotated card must come back as an upright card face.
    res = page.evaluate("""async ()=>{
        const img=new Image();img.src='scattered.png';await img.decode();
        const c=document.createElement('canvas');
        c.width=img.naturalWidth;c.height=img.naturalHeight;
        c.getContext('2d').drawImage(img,0,0);
        const d=CardFind.detect(c);
        if(!d.length) return null;
        const out=CardFind.crop(c,d[0].quad,68,96,false);
        if(!out) return null;
        // A card face has a light border and a busy middle. Compare the mean
        // luma of the outer frame against the art box: a correct, upright crop
        // has a clearly lighter frame. A crop that is mostly tablecloth does not.
        const x=out.getContext('2d').getImageData(0,0,68,96).data;
        const L=i=>0.299*x[i]+0.587*x[i+1]+0.114*x[i+2];
        let edge=0,ne=0,mid=0,nm=0;
        for(let y=0;y<96;y++)for(let xx=0;xx<68;xx++){
          const i=(y*68+xx)*4;
          const isEdge=(xx<3||xx>64||y<3||y>92);
          if(isEdge){edge+=L(i);ne++;} else if(y>12&&y<58){mid+=L(i);nm++;}
        }
        return {w:out.width,h:out.height,edge:edge/ne,mid:mid/nm};
    }""")
    if res is None:
        check("crop produced a card image", False)
    else:
        check(f"crop is the requested size (got {res['w']}x{res['h']})",
              res["w"] == 68 and res["h"] == 96)
        check(f"crop looks like a card face, light border vs busy art "
              f"(border {res['edge']:.0f} vs art {res['mid']:.0f})",
              res["edge"] > res["mid"] + 8)

    print("\n4. proving the scorer can fail")
    # A detector that returned garbage must not score well. Without this, every
    # recall number above could be produced by an IoU function that says yes.
    bogus = poly_iou([[0, 0], [10, 0], [10, 10], [0, 10]],
                     [[900, 900], [910, 900], [910, 910], [900, 910]])
    check(f"a box nowhere near a card scores 0 IoU (got {bogus:.2f})", bogus == 0)
    half = poly_iou([[0, 0], [10, 0], [10, 10], [0, 10]],
                    [[5, 0], [15, 0], [15, 10], [5, 10]])
    check(f"a half-overlapping box scores ~0.33, not a hit (got {half:.2f})",
          0.30 < half < 0.36 and half < IOU_HIT)

    browser.close()

# ---------------------------------------------------------------------------
print("\n4. the app actually loads this file")
# Everything above runs against a synthetic fixture page with cardfind.js
# injected by add_script_tag. That proves the ALGORITHM works and says nothing
# about whether the product uses it -- and for a while it did not: index.html
# never referenced cardfind.js, so every assertion above was green while the lot
# scanner still used only the grid splitter. A suite that cannot tell "correct"
# from "disconnected" is the expensive kind of green.
_root = os.path.dirname(os.path.abspath(__file__))
_html = open(os.path.join(_root, "index.html")).read()
check("index.html loads cardfind.js",
      bool(re.search(r'<script[^>]+src=["\']\.?/?cardfind\.js', _html)))
check("the lot scan path calls the detector",
      "scoreDetect(" in _html and "CardFind.detect" in _html)
check("...and still falls back to the grid layouts", "LOT_LAYOUTS" in _html)
_sw = open(os.path.join(_root, "sw.js")).read()
check("the service worker precaches cardfind.js", "cardfind.js" in _sw)

# ---------------------------------------------------------------------------
print("\n5. a wrong row can be removed from the total")
# The results table is the one screen whose number gets said out loud to a
# seller across a table. Fix could correct a MISREAD card; nothing could delete
# a thing that was never a card, so a false positive stayed in the market total.
import http.server, threading, functools, socketserver
_PORT2 = PORT + 7
_h = functools.partial(http.server.SimpleHTTPRequestHandler,
                       directory=os.path.dirname(os.path.abspath(__file__)))
class _Q(socketserver.TCPServer): allow_reuse_address = True
_srv = _Q(("127.0.0.1", _PORT2), _h)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
try:
    with sync_playwright() as _pw:
        _b = _pw.chromium.launch()
        _pg = _b.new_page(viewport={"width": 390, "height": 844})
        _pg.goto(f"http://127.0.0.1:{_PORT2}/", wait_until="load")
        for _ in range(14):
            if not _pg.evaluate("()=>{const e=document.querySelector('#tourWrap');"
                                "return !!e&&e.classList.contains('on');}"):
                break
            _pg.evaluate("""()=>{const s=document.querySelector('#tourSkip');
                const n=document.querySelector('#tourNext');
                if(s&&s.offsetParent!==null){s.click();return;}
                if(n)n.click();}""")
            _pg.wait_for_timeout(150)
        _pg.evaluate("()=>LotScanner.open()")
        _pg.wait_for_timeout(300)
        _pg.evaluate("""()=>LotScanner._render([
            {found:true,name:'Charizard ex',price:100,c:'nm',id:'a',line:'charizard ex'},
            {found:true,name:'Pikachu V',price:20,c:'nm',id:'b',line:'pikachu v'},
            {found:false,line:'blurry edge of the table'}],'')""")
        _pg.wait_for_timeout(300)

        def _st():
            return _pg.evaluate("""()=>{const b=document.querySelector('#lotResults');
              const tot=[...b.querySelectorAll('.lot-tot .tr')]
                          .map(x=>x.innerText.replace(/\s+/g,' ')).join(' | ');
              return {rows:b.querySelectorAll('.lot-row').length,
                      drops:b.querySelectorAll('[data-drop]').length, tot:tot};}""")

        a = _st()
        check(f"every row gets a remove control ({a['drops']} of {a['rows']})",
              a["drops"] == a["rows"] == 3)
        check(f"the starting total is $120 ({a['tot'][:44]})", "$120" in a["tot"])

        # A remove control smaller than a thumb is a remove control that gets
        # mis-tapped on the row above it.
        box = _pg.evaluate("""()=>{const e=document.querySelector('[data-drop]');
            const r=e.getBoundingClientRect();
            return {w:Math.round(r.width),h:Math.round(r.height)};}""")
        check(f"...and is tappable ({box['w']}x{box['h']})",
              box["h"] >= 30 and box["w"] >= 30)

        _pg.evaluate("()=>document.querySelector('[data-drop=\"1\"]').click()")
        _pg.wait_for_timeout(300)
        c = _st()
        check(f"removing the $20 row drops the total to $100 ({c['tot'][:40]})",
              "$100" in c["tot"] and "$120" not in c["tot"])
        check("...and the matched count corrects with it", "1 of 2" in c["tot"])
        check("...and the underlying rows actually shrank",
              _pg.evaluate("()=>LotScanner._rows().length") == 2)

        # NEGATIVE CASE: removing must not empty the table wholesale.
        check("the remaining rows survive",
              _pg.evaluate("()=>document.querySelectorAll('#lotResults .lot-row').length") == 2)
        _b.close()
finally:
    _srv.shutdown()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
