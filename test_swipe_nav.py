#!/usr/bin/env python3
"""
Sideways swipe between tabs -- and, mostly, the places it must NOT fire.

Run:  python3 test_swipe_nav.py

A tab swipe is easy to add and easy to get subtly wrong, and wrong here does not
read as a bug. It reads as the app fighting you: the page jumps to another tab
while you were dragging a slider, or scrolling a wide table sideways, or
dismissing a sheet. So most of this file is negative cases.

Touch is synthesised through CDP (Input.dispatchTouchEvent) rather than
page.tap(), because the handler reads clientX across a real touchstart/touchend
pair and a synthetic click carries neither.
"""
import os
import sys
import http.server
import threading
import functools

from playwright.sync_api import sync_playwright

import shots

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8819

passed = True


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


def swipe(cdp, x0, y0, x1, y1, steps=6):
    """A real touch drag. Intermediate moves matter: a start and an end with
    nothing between is not what a finger produces, and a handler that only
    works for that shape would pass here and fail on a phone."""
    cdp.send("Input.dispatchTouchEvent", {
        "type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [
            {"x": x0 + (x1 - x0) * i / steps, "y": y0 + (y1 - y0) * i / steps}]})
    cdp.send("Input.dispatchTouchEvent", {
        "type": "touchEnd", "touchPoints": []})


def tab(page):
    return page.evaluate("()=>document.querySelector('.navb.on')?.dataset.tab")


httpd = serve()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              has_touch=True, is_mobile=True,
                              reduced_motion="reduce")
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
    page.add_init_script(shots.FREEZE_JS)
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    for _ in range(400):
        if page.evaluate("window.CatalogState") == "ready":
            break
        page.wait_for_timeout(50)
    page.add_style_tag(content=shots.FREEZE_CSS)
    shots.dismiss_tour(page)
    page.wait_for_timeout(300)

    print("\n1. swiping moves between tabs")
    page.evaluate("()=>switchTab('block')")
    page.wait_for_timeout(200)
    check(f"start on block (got {tab(page)})", tab(page) == "block")

    swipe(cdp, 330, 400, 90, 405)          # swipe left -> move right
    page.wait_for_timeout(300)
    check(f"swipe left goes block -> port (got {tab(page)})", tab(page) == "port")

    swipe(cdp, 90, 400, 330, 405)          # swipe right -> move back
    page.wait_for_timeout(300)
    check(f"swipe right goes port -> block (got {tab(page)})", tab(page) == "block")

    print("\n2. 'scan' is skipped, because it is not a panel")
    # Left of slab is port, NOT scan: scan opens the camera, and swiping into it
    # would fire the scanner mid-gesture.
    page.evaluate("()=>switchTab('port')")
    page.wait_for_timeout(200)
    swipe(cdp, 330, 400, 90, 405)
    page.wait_for_timeout(300)
    check(f"port swipes to slab, not scan (got {tab(page)})", tab(page) == "slab")
    check("and the scanner did not open",
          page.evaluate("()=>{const m=document.querySelector('#scanModal');"
                        "return !m||!m.classList.contains('show');}"))

    print("\n3. the ends are ends, no wrap")
    page.evaluate("()=>switchTab('block')")
    page.wait_for_timeout(200)
    swipe(cdp, 90, 400, 330, 405)          # swipe right at the first tab
    page.wait_for_timeout(300)
    check(f"swiping right from block stays on block (got {tab(page)})",
          tab(page) == "block")
    page.evaluate("()=>switchTab('settings')")
    page.wait_for_timeout(200)
    swipe(cdp, 330, 400, 90, 405)          # swipe left at the last tab
    page.wait_for_timeout(300)
    check(f"swiping left from settings stays on settings (got {tab(page)})",
          tab(page) == "settings")

    print("\n4. gestures that belong to something else are not stolen")
    page.evaluate("()=>switchTab('block')")
    page.wait_for_timeout(250)

    # A near-vertical drag is a scroll. This is the one that would fire
    # constantly in ordinary use if the ratio test were missing.
    swipe(cdp, 200, 600, 150, 250)
    page.wait_for_timeout(250)
    check(f"a mostly-vertical drag does not change tab (got {tab(page)})",
          tab(page) == "block")

    # Too short to be intentional.
    swipe(cdp, 200, 400, 165, 402)
    page.wait_for_timeout(250)
    check(f"a short wobble does not change tab (got {tab(page)})",
          tab(page) == "block")

    # The range slider IS a horizontal drag. Stealing it would make the deal
    # calculator unusable, which is the screen this app is for.
    # Reveal the slider first: rateCard collapses by default now, and a hidden
    # control cannot demonstrate that its drag is left alone. The point of the
    # check is that a VISIBLE slider owns its own horizontal gesture.
    page.evaluate("""()=>{const h=document.querySelector('[data-col=rateCard]');
        const c=document.querySelector('#rateCard');
        if(h&&c&&c.classList.contains('collapsed'))h.click();}""")
    page.wait_for_timeout(350)
    rng = page.evaluate("""()=>{const e=document.getElementById('rate');
        if(!e) return null; e.scrollIntoView({block:'center'});
        const r=e.getBoundingClientRect();
        return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2),
                w:Math.round(r.width)};}""")
    if not rng:
        print("  [SKIP] slider gesture -- #rate not on this screen")
    else:
        before = tab(page)
        swipe(cdp, rng["x"] + 80, rng["y"], rng["x"] - 80, rng["y"])
        page.wait_for_timeout(250)
        check(f"dragging the rate slider does not change tab (got {tab(page)})",
              tab(page) == before)

    # An open sheet owns the screen and has its own swipe-to-dismiss.
    page.evaluate("""()=>{try{Sheet.open('Swipe test',
        [{type:'static',html:'<div class=\\"sub\\">x</div>'}],'Close',function(){});}catch(e){}}""")
    page.wait_for_timeout(450)
    before = tab(page)
    swipe(cdp, 330, 500, 90, 505)
    page.wait_for_timeout(250)
    check(f"swiping across an open sheet does not change tab (got {tab(page)})",
          tab(page) == before)
    page.evaluate("""()=>{const s=document.querySelector('#sheet');
        s.classList.remove('show');s.classList.remove('on');}""")
    page.wait_for_timeout(400)

    print("\n5. the buttons still work (swipe is an addition, not a replacement)")
    page.evaluate("()=>document.querySelector('.navb[data-tab=\"slab\"]').click()")
    page.wait_for_timeout(300)
    check(f"tapping the nav still switches tabs (got {tab(page)})", tab(page) == "slab")

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
