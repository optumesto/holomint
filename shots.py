#!/usr/bin/env python3
"""
Visual regression harness: capture the app's screens, then compare two captures.

    python3 shots.py capture .shots/before
    ...make changes...
    python3 shots.py capture .shots/after
    python3 shots.py compare .shots/before .shots/after

Exists because the remaining UI work -- collapsing 20 font sizes to a scale,
62 paddings to a rhythm, and unpicking 264 inline styles -- is mechanical,
touches every screen, and cannot be verified by reading a diff. A spacing token
that quietly breaks one panel's layout looks exactly like one that worked.

Deliberately NOT a pass/fail gate. Every one of these changes is *supposed* to
move pixels, so a threshold would either be so loose it catches nothing or so
tight it screams on every commit. It reports how much moved and where, and a
person looks at the ones that moved more than they expected. The diff images
make that a glance rather than a hunt.

Determinism is the hard part of a harness like this, and most of the code below
is about removing sources of noise: the tour, animations, the caret, live data,
and anything that reads the clock.
"""
import sys
import os
import http.server
import threading
import functools

PORT = 8805
ROOT = os.path.dirname(os.path.abspath(__file__))

# width, height, label. Both a phone and a wide viewport, because the type and
# spacing work can easily fix one and break the other.
VIEWPORTS = [(390, 844, "phone"), (1280, 900, "desktop")]

# Freeze everything that would otherwise differ run to run. Injected before any
# page script so it also covers the splash and the tour.
FREEZE_CSS = """
*,*::before,*::after{
  animation-duration:0s !important; animation-delay:0s !important;
  transition-duration:0s !important; transition-delay:0s !important;
  caret-color:transparent !important;
}
#splash{display:none !important}
"""

FREEZE_JS = """
try{localStorage.setItem('holomint:tourSeen','1');}catch(e){}
// The clock reaches the UI through relative times ("2m ago") and the queue
// salt. Pinning it makes those stable without stubbing each call site.
const _FIXED = new Date('2026-08-27T12:00:00Z').getTime();
const _RD = Date;
window.Date = class extends _RD {
  constructor(...a){ return a.length ? new _RD(...a) : new _RD(_FIXED); }
  static now(){ return _FIXED; }
};
Math.random = () => 0.42;
"""


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


def dismiss_tour(page):
    """Click the tour away through its own controls, if it appears."""
    for _ in range(60):
        if page.evaluate("()=>{const e=document.querySelector('#tourWrap');"
                         "return !!e&&e.classList.contains('on');}"):
            break
        page.wait_for_timeout(100)
    for _ in range(14):
        if not page.evaluate("()=>{const e=document.querySelector('#tourWrap');"
                             "return !!e&&e.classList.contains('on');}"):
            return
        page.evaluate("""()=>{const s=document.querySelector('#tourSkip');
            const n=document.querySelector('#tourNext');
            if(s&&s.offsetParent!==null){s.click();return;}
            if(n)n.click();}""")
        page.wait_for_timeout(150)


def capture(outdir):
    from playwright.sync_api import sync_playwright
    os.makedirs(outdir, exist_ok=True)
    httpd = serve()
    made = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for w, h, vlabel in VIEWPORTS:
            ctx = browser.new_context(service_workers="block",
                                      viewport={"width": w, "height": h},
                                      device_scale_factor=1,
                                      reduced_motion="reduce")
            page = ctx.new_page()
            page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
            page.add_init_script(FREEZE_JS)
            page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
            for _ in range(400):
                if page.evaluate("window.CatalogState") == "ready":
                    break
                page.wait_for_timeout(50)
            page.add_style_tag(content=FREEZE_CSS)
            dismiss_tour(page)
            page.wait_for_timeout(400)

            def shot(name):
                path = os.path.join(outdir, f"{vlabel}--{name}.png")
                page.screenshot(path=path, full_page=True)
                made.append(path)
                print(f"  {os.path.basename(path)}")

            for tab in ["block", "port", "slab", "settings"]:
                page.evaluate("(t)=>{try{switchTab(t)}catch(e){"
                              "const b=document.querySelector('[data-tab=\"'+t+'\"]');"
                              "if(b)b.click();}}", tab)
                page.wait_for_timeout(450)
                shot(f"tab-{tab}")

            # Search results: the densest, most token-heavy surface in the app.
            page.evaluate("()=>{try{switchTab('block')}catch(e){}}")
            page.wait_for_timeout(300)
            page.evaluate("""()=>{const i=document.getElementById('search');
                if(i){i.value='charizard';i.dispatchEvent(new Event('input',{bubbles:true}));}}""")
            page.wait_for_timeout(500)
            shot("search-results")

            # A sheet, for overlay chrome.
            page.evaluate("""()=>{try{Sheet.open('Preview',[{type:'static',
                html:'<div class=\\"sub\\">Visual regression sample.</div>'}],'Close',function(){});
                }catch(e){}}""")
            page.wait_for_timeout(450)
            shot("sheet-open")
            ctx.close()
        browser.close()
    httpd.shutdown()
    print(f"\n{len(made)} screenshots -> {outdir}")


def compare(a_dir, b_dir):
    from PIL import Image
    import numpy as np
    names = sorted(set(os.listdir(a_dir)) & set(os.listdir(b_dir)))
    names = [n for n in names if n.endswith(".png")]
    only_a = sorted(set(os.listdir(a_dir)) - set(os.listdir(b_dir)))
    only_b = sorted(set(os.listdir(b_dir)) - set(os.listdir(a_dir)))
    diffdir = os.path.join(b_dir, "_diff")
    os.makedirs(diffdir, exist_ok=True)
    print(f"{'screen':34s} {'changed':>9} {'size':>16}")
    print("-" * 64)
    rows = []
    for n in names:
        ia = Image.open(os.path.join(a_dir, n)).convert("RGB")
        ib = Image.open(os.path.join(b_dir, n)).convert("RGB")
        if ia.size != ib.size:
            print(f"{n[:33]:34s} {'RESIZED':>9} {ia.size}->{ib.size}")
            rows.append((n, 100.0))
            continue
        na, nb = np.asarray(ia, dtype=np.int16), np.asarray(ib, dtype=np.int16)
        # Per-pixel max channel delta; >8 counts as a real change, which ignores
        # antialiasing jitter without hiding a colour or position shift.
        delta = np.abs(na - nb).max(axis=2)
        changed = float((delta > 8).mean() * 100)
        rows.append((n, changed))
        print(f"{n[:33]:34s} {changed:8.2f}% {str(ia.size):>16}")
        if changed > 0:
            mask = (delta > 8).astype(np.uint8) * 255
            out = nb.copy().astype(np.uint8)
            out[..., 0] = np.maximum(out[..., 0], mask)   # tint changes red
            Image.fromarray(out).save(os.path.join(diffdir, n))
    print("-" * 64)
    if rows:
        worst = max(rows, key=lambda r: r[1])
        print(f"most changed: {worst[0]} at {worst[1]:.2f}%")
        print(f"mean change:  {sum(r[1] for r in rows)/len(rows):.2f}%")
    for n in only_a:
        print(f"  only in {a_dir}: {n}")
    for n in only_b:
        print(f"  only in {b_dir}: {n}")
    print(f"\ndiff images (changes tinted red): {diffdir}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        raise SystemExit(2)
