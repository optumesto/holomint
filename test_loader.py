#!/usr/bin/env python3
"""
Behavioural tests for the catalog loader in index.html.

Run:  python3 test_loader.py
Needs: pip install playwright && playwright install chromium

These drive a real browser against a real local copy of the site, because the
thing under test is *when* a fetch happens relative to the ready event, and
that is not observable by reading the source. Asserting on the source text
would pass just as happily if history.json were still awaited.

The load-bearing test is section 2: history.json is stalled for 6 seconds and
the app must still become usable. If someone puts history back into the
blocking Promise.allSettled, that test fails and nothing else does.
"""
import http.server
import socketserver
import threading
import functools
import sys
import time
import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8791
STALL_S = 6.0          # how long to hold history.json hostage
READY_BUDGET_MS = 4000  # ready must beat the stall by a clear margin

passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    passed &= bool(cond)


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static server with one extra trick: /__slow/<path> serves <path> late.

    The delay MUST live here rather than in the Playwright route handler. The
    sync API runs the route callback on the same thread as the driver, so a
    time.sleep() there freezes page.evaluate() too -- the test then cannot
    observe the very thing it is trying to measure, and section 2 times out
    while the app is in fact ready. Server-side, the browser waits and the
    driver stays free to poll.
    """
    def translate_path(self, path):
        if path.startswith("/__slow/"):
            time.sleep(STALL_S)
            path = path[len("/__slow"):]
        return super().translate_path(path)

    def log_message(self, *a):
        pass  # the transcript is the assertions, not 40 lines of GET


def serve():
    handler = functools.partial(Handler, directory=ROOT)
    # Threading matters: a stalled /__slow request must not block the parallel
    # fetches of products.json and prices.json, which are the ones under test.
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def wait_state(page, expr, want, timeout_ms):
    """Poll `expr` until it equals `want`. Returns ms elapsed, or None on timeout."""
    t0 = time.time()
    while (time.time() - t0) * 1000 < timeout_ms:
        try:
            if page.evaluate(expr) == want:
                return (time.time() - t0) * 1000
        except Exception:
            pass
        page.wait_for_timeout(50)
    return None


def new_page(browser, history_mode):
    """history_mode: 'ok' | 'fail' | 'stall'. Returns (context, page).

    A FRESH context per scenario, with service workers blocked. Both matter:
    sw.js precaches products.json and hashes.json, and once it is installed in a
    context it will serve those from cache on the next page, so a route that is
    supposed to abort a request silently never sees it. The first draft of this
    file shared one context and section 3 failed for exactly that reason -- the
    loader was correct and the test was lying. Isolation is not optional here.
    """
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()

    # Keep the test off the internet. The page calls api.pokemontcg.io on some
    # paths; a test that depends on a third party is a test that fails for
    # reasons that have nothing to do with the loader.
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())

    def history_route(route):
        if history_mode == "fail":
            route.abort()
        elif history_mode == "stall":
            route.continue_(url=f"http://127.0.0.1:{PORT}/__slow/history.json")
        else:
            route.continue_()

    page.route("**/history.json", history_route)
    return ctx, page


print("\n0. serving the site locally")
httpd = serve()
check(f"http server up on :{PORT}", True)

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    print("\n1. normal load: app becomes usable AND history arrives")
    tctx, page = new_page(browser, "ok")
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    ms = wait_state(page, "window.CatalogState", "ready", 30000)
    check("CatalogState reaches 'ready'", ms is not None)
    hms = wait_state(page, "window.HistoryState", "ready", 60000)
    check("HistoryState reaches 'ready'", hms is not None)
    got = page.evaluate(
        "(()=>{try{const k=Object.keys(PriceEngine?{}:{});}catch(e){}"
        "try{return typeof PriceEngine.getHistory==='function'}catch(e){return false}})()")
    check("PriceEngine.getHistory is still exposed", got is True)
    page.close(); tctx.close()

    print("\n2. THE REGRESSION GUARD: history stalled 6s, app must not wait")
    tctx, page = new_page(browser, "stall")
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    ms = wait_state(page, "window.CatalogState", "ready", READY_BUDGET_MS)
    check(f"CatalogState 'ready' within {READY_BUDGET_MS}ms while history stalls "
          f"{STALL_S}s ({'%.0f' % ms if ms else 'TIMEOUT'}ms)", ms is not None)
    state = page.evaluate("window.HistoryState")
    check(f"...and history is still in flight at that moment (got {state!r})",
          state in ("idle", "loading"))
    page.close(); tctx.close()

    print("\n3. history fails outright: app is still fully usable")
    tctx, page = new_page(browser, "fail")
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    ms = wait_state(page, "window.CatalogState", "ready", 30000)
    check("CatalogState reaches 'ready' with NO history at all", ms is not None)
    hs = wait_state(page, "window.HistoryState", "failed", 15000)
    check("HistoryState reports 'failed', not a silent 'idle'", hs is not None)
    check("getHistory degrades to [] rather than throwing",
          page.evaluate("(()=>{try{return Array.isArray(PriceEngine.getHistory('es-bb'))}"
                        "catch(e){return false}})()") is True)
    check("catalog is populated despite the history failure",
          page.evaluate("(()=>{try{return PriceEngine.list().length>0}catch(e){return false}})()") is True)
    page.close(); tctx.close()

    print("\n4. loadHistory is idempotent (loadData may run again on refresh)")
    tctx, page = new_page(browser, "ok")
    hits = []
    page.on("request", lambda r: hits.append(r.url) if "history.json" in r.url else None)
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    wait_state(page, "window.HistoryState", "ready", 60000)
    page.evaluate("PriceEngine.loadHistory();PriceEngine.loadHistory();")
    page.wait_for_timeout(600)
    check(f"history.json requested exactly once (got {len(hits)})", len(hits) == 1)
    page.close(); tctx.close()

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
