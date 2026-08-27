#!/usr/bin/env python3
"""
Behavioural tests for the install offer.

Run:  python3 test_install_offer.py
Needs: pip install -r requirements-dev.txt && python3 -m playwright install chromium

Timing is the whole feature here, so every test is about WHEN the offer appears
rather than whether the code runs. The offer must be silent on a first visit,
appear on a second, and never come back once someone has said no or has already
installed. Those are four different silences and three of them are correct --
which is exactly the case where a test that only checks "did it show" would pass
while the feature is obnoxious.

beforeinstallprompt does not fire in headless Chromium, so it is synthesised.
That is honest here: the code under test only ever treats the event as an opaque
object with prompt() and userChoice, and the capture listener is real.
"""
import http.server
import threading
import functools
import sys
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8799

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


FIRE_BIP = """() => {
  const e = new Event('beforeinstallprompt');
  e.prompt = () => { window.__promptCalled = true; };
  e.userChoice = Promise.resolve({outcome: window.__outcome || 'accepted'});
  window.dispatchEvent(e);
}"""


def visit(ctx, *, install_supported=True, standalone=False, outcome="accepted"):
    """One page load. Returns the page, ready and past the tour."""
    page = ctx.new_page()
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
    if standalone:
        # The app tests display-mode: standalone to detect being installed.
        page.add_init_script(
            "const mm=window.matchMedia.bind(window);"
            "window.matchMedia=q=>q.includes('standalone')?"
            "{matches:true,media:q,addListener(){},removeListener(){},"
            "addEventListener(){},removeEventListener(){}}:mm(q);")
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    for _ in range(400):
        if page.evaluate("window.CatalogState") == "ready":
            break
        page.wait_for_timeout(50)
    page.evaluate(f"window.__outcome={outcome!r}")
    if install_supported:
        page.evaluate(FIRE_BIP)
    return page


def search(page, q="charizard"):
    page.evaluate("""(q)=>{const i=document.getElementById('search');
        i.value=q;i.dispatchEvent(new Event('input',{bubbles:true}));}""", q)
    page.wait_for_timeout(400)


def offer_visible(page):
    return page.evaluate("""()=>{const t=document.getElementById('toast');
        return !!t && t.classList.contains('show')
               && /home screen/i.test(t.textContent||'');}""")


print("\n0. serving")
httpd = serve()
check(f"http server up on :{PORT}", True)

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    print("\n1. a first-time visitor is not asked to install anything")
    ctx = browser.new_context(service_workers="block")
    p = visit(ctx)
    search(p)
    check("no offer after the FIRST useful search", offer_visible(p) is False)
    check("the search itself was counted",
          p.evaluate("JSON.parse(localStorage.getItem('holomint:goodSearches'))") == 1)
    search(p, "umbreon")
    search(p, "booster box")
    check("more searches in the SAME visit still do not offer",
          offer_visible(p) is False)
    check("...and do not inflate the count (once per load)",
          p.evaluate("JSON.parse(localStorage.getItem('holomint:goodSearches'))") == 1)
    p.close()

    print("\n2. the second visit is when it asks")
    p = visit(ctx)
    search(p)
    check("offer appears on the second visit's useful search", offer_visible(p) is True)
    check("the action button is labelled for installing",
          p.evaluate("""()=>{const b=document.querySelector('#toast .tu');
              return !!b && /add|how/i.test(b.textContent||'');}""") is True)
    p.close()
    ctx.close()

    print("\n3. a search that finds nothing is not a 'useful search'")
    ctx = browser.new_context(service_workers="block")
    p = visit(ctx)
    search(p, "zzzzzznotathing")
    check("no count for a query with no hits",
          p.evaluate("localStorage.getItem('holomint:goodSearches')") is None)
    p.close(); ctx.close()

    print("\n4. already installed: never ask")
    ctx = browser.new_context(service_workers="block")
    for _ in range(2):
        p = visit(ctx, standalone=True); search(p); p.close()
    p = visit(ctx, standalone=True)
    search(p)
    check("standalone display-mode suppresses the offer entirely",
          offer_visible(p) is False)
    p.close(); ctx.close()

    print("\n5. saying no in the browser sheet ends it for good")
    ctx = browser.new_context(service_workers="block")
    p = visit(ctx); search(p); p.close()
    p = visit(ctx, outcome="dismissed")
    search(p)
    check("offer shown on visit two", offer_visible(p) is True)
    p.evaluate("document.querySelector('#toast .tu').click()")
    p.wait_for_timeout(500)
    check("prompt() was actually called", p.evaluate("window.__promptCalled") is True)
    check("a dismissal is recorded",
          p.evaluate("JSON.parse(localStorage.getItem('holomint:installNo'))") == 1)
    p.close()
    p = visit(ctx)
    search(p)
    check("and it never asks again", offer_visible(p) is False)
    p.close(); ctx.close()

    print("\n6. accepting records the install and stops asking")
    ctx = browser.new_context(service_workers="block")
    p = visit(ctx); search(p); p.close()
    p = visit(ctx, outcome="accepted")
    search(p)
    p.evaluate("document.querySelector('#toast .tu').click()")
    p.wait_for_timeout(500)
    check("install is recorded",
          p.evaluate("JSON.parse(localStorage.getItem('holomint:installed'))") == 1)
    p.close()
    p = visit(ctx)
    search(p)
    check("no further offers once installed", offer_visible(p) is False)
    p.close(); ctx.close()

    print("\n7. it gives up after three asks rather than nagging forever")
    ctx = browser.new_context(service_workers="block")
    seen = []
    for _ in range(6):
        p = visit(ctx); search(p); seen.append(offer_visible(p)); p.close()
    check(f"asked at most 3 times over 6 visits (asked {sum(seen)})",
          sum(seen) <= 3)
    check("and asked at least once", sum(seen) >= 1)
    p = visit(ctx); search(p)
    check("silent afterwards", offer_visible(p) is False)
    p.close(); ctx.close()

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
