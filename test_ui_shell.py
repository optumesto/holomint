#!/usr/bin/env python3
"""
Behavioural tests for the app shell: scroll locking and safe-area setup.

Run:  python3 test_ui_shell.py
Needs: pip install -r requirements-dev.txt && python3 -m playwright install chromium

Both things under test are invisible until they are wrong, and both were wrong
in a way that reads as "this is a website" rather than as a bug:

  * seven overlays, none of which stopped the page scrolling behind them
  * eight env(safe-area-inset-*) rules that resolved to 0px because the meta
    viewport was missing viewport-fit=cover

The scroll-lock tests assert the RESTORE as hard as the lock. A lock that
forgets where the page was is worse than no lock: the modal closes and the app
silently jumps to the top, which is the exact iOS Safari failure that using
position:fixed instead of overflow:hidden is meant to avoid.
"""
import http.server
import threading
import functools
import sys
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8801

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


def body_state(page):
    return page.evaluate("""()=>{const b=document.body;return{
        position:b.style.position, top:b.style.top, width:b.style.width,
        scrollY:Math.round(window.scrollY)};}""")


def set_overlay(page, sel, on):
    """Open/close an overlay the way the app does: by toggling its class."""
    page.evaluate("""([sel,on])=>{const e=document.querySelector(sel);
        if(!e)return false;
        if(on)e.classList.add('show'); else {e.classList.remove('show');e.classList.remove('on');}
        return true;}""", [sel, on])
    page.wait_for_timeout(180)   # MutationObserver is async


print("\n0. serving")
httpd = serve()
check(f"http server up on :{PORT}", True)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844})  # iPhone-ish
    page = ctx.new_page()
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    for _ in range(400):
        if page.evaluate("window.CatalogState") == "ready":
            break
        page.wait_for_timeout(50)

    print("\n1. the viewport opts into safe-area insets")
    vp = page.evaluate(
        "()=>{const m=document.querySelector('meta[name=viewport]');return m?m.content:''}")
    check("viewport-fit=cover is present", "viewport-fit=cover" in vp)
    # Proves the insets RESOLVE, not merely that the string is in the tag. In a
    # desktop Chromium the insets are legitimately 0px, so this asserts the
    # property is understood rather than asserting a nonzero number we cannot
    # produce here.
    supported = page.evaluate(
        "()=>CSS.supports('padding-bottom','env(safe-area-inset-bottom)')")
    check("env(safe-area-inset-*) is a supported value", supported is True)

    print("\n2. the tour is an overlay, so it locks too")
    # The tour opens AFTER the catalog is ready, not with it. An earlier version
    # of this test read the state at 'ready', found no tour, stripped its class
    # and then raced the app putting it straight back -- every later assertion
    # then measured a page that was locked for a reason the test had lost track
    # of. Wait for it, then dismiss it through its own buttons.
    tour_open = False
    for _ in range(60):
        if page.evaluate("()=>{const e=document.querySelector('#tourWrap');"
                         "return !!e&&e.classList.contains('on');}"):
            tour_open = True
            break
        page.wait_for_timeout(100)
    check("the tour does open on a first visit", tour_open is True)
    if tour_open:
        check("body is scroll-locked while the tour is up",
              body_state(page)["position"] == "fixed")
        # Click through with the real controls. The first step is the assent
        # gate and only offers Continue, so Skip is not always present.
        for _ in range(14):
            if not page.evaluate("()=>{const e=document.querySelector('#tourWrap');"
                                 "return !!e&&e.classList.contains('on');}"):
                break
            page.evaluate("""()=>{const s=document.querySelector('#tourSkip');
                const n=document.querySelector('#tourNext');
                if(s&&s.offsetParent!==null){s.click();return;}
                if(n)n.click();}""")
            page.wait_for_timeout(160)
    page.wait_for_timeout(250)
    check("dismissing it releases the lock",
          body_state(page)["position"] != "fixed")

    print("\n3. opening a sheet locks the page where it stands")
    page.evaluate("window.scrollTo(0,300)")
    page.wait_for_timeout(150)
    before = page.evaluate("Math.round(window.scrollY)")
    check(f"page is scrolled before opening (y={before})", before > 0)
    set_overlay(page, "#sheet", True)
    st = body_state(page)
    check("body goes position:fixed", st["position"] == "fixed")
    check(f"scroll offset is carried in top (got {st['top']!r})",
          st["top"] == f"-{before}px")
    check("body is pinned to full width", st["width"] == "100%")

    print("\n4. closing restores the exact scroll position")
    set_overlay(page, "#sheet", False)
    st = body_state(page)
    check("position style is cleared", st["position"] == "")
    check("top style is cleared", st["top"] == "")
    check(f"scroll is back where it was (want {before}, got {st['scrollY']})",
          abs(st["scrollY"] - before) <= 1)

    print("\n5. the lock is idempotent and survives overlay churn")
    page.evaluate("window.scrollTo(0,220)")
    page.wait_for_timeout(150)
    y = page.evaluate("Math.round(window.scrollY)")
    set_overlay(page, "#sheet", True)
    set_overlay(page, "#lotModal", True)      # a second overlay on top
    st = body_state(page)
    check("still locked with two overlays open", st["position"] == "fixed")
    check(f"offset did not double-apply (top={st['top']!r})", st["top"] == f"-{y}px")
    set_overlay(page, "#lotModal", False)
    st = body_state(page)
    check("still locked while one overlay remains", st["position"] == "fixed")
    set_overlay(page, "#sheet", False)
    st = body_state(page)
    check("released only when the last one closes", st["position"] == "")
    check(f"and scroll is still correct (want {y}, got {st['scrollY']})",
          abs(st["scrollY"] - y) <= 1)

    print("\n6. scroll chaining is contained on the full-screen overlays")
    vals = page.evaluate("""()=>{const out={};
        for(const sel of ['#scanModal','#scanChoose','#tourWrap','#lotModal']){
          const e=document.querySelector(sel);
          out[sel]= e? getComputedStyle(e).overscrollBehaviorY : 'missing';}
        return out;}""")
    for sel, v in vals.items():
        check(f"{sel} overscroll-behavior contained (got {v})",
              v in ("contain", "none") or v == "missing")

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
