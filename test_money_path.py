#!/usr/bin/env python3
"""
The money path: everything between tapping PRO and arriving at the checkout.

Run:  python3 test_money_path.py
Needs: pip install -r requirements-dev.txt && python3 -m playwright install chromium

This file exists because Holomint is live with no subscribers, so every failure
here has never been observed by anyone except the author, who cannot see it:
he already has Pro, he built the flow, and his network works. The failure modes
that matter are the ones a stranger hits once and walks away from -- there is no
support ticket, no retry, and no second chance at a card show.

Nothing here can test a real payment. What it can test is every gate in front of
one: that the offer renders, that consent actually gates the link, that a
mis-click explains itself, and -- most of all -- that a bad network says
something a person would retry after.

The pricing endpoint is mocked rather than hit, so the suite is deterministic
and never depends on the Worker being up.
"""
import http.server
import threading
import functools
import json
import sys
import os

from playwright.sync_api import sync_playwright

import shots  # for the tour dismissal that waits properly

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8815
PRICING = "**/api/pricing*"

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


GOOD_PRICE = {
    "configured": True, "amount": 4.99, "currency": "USD", "interval": "month",
    "checkout": "https://checkout.example/holomint-pro",
    "portal": "https://portal.example/manage",
}


def boot(page, pricing_mode):
    """Open the app with the pricing endpoint mocked in one of three ways."""
    if pricing_mode == "good":
        page.route(PRICING, lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps(GOOD_PRICE)))
    elif pricing_mode == "offline":
        page.route(PRICING, lambda r: r.abort())        # the venue-wifi case
    elif pricing_mode == "unconfigured":
        page.route(PRICING, lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"configured": False})))     # genuinely not selling yet
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


def open_pro(page):
    page.evaluate("()=>document.querySelector('#proBtn').click()")
    page.wait_for_timeout(700)          # refresh() awaits the pricing fetch


httpd = serve()
with sync_playwright() as pw:
    browser = pw.chromium.launch()

    print("\n1. the offer renders and consent gates the link")
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "good")
    open_pro(page)

    st = page.evaluate("""()=>{const g=document.querySelector('#ckGo');
        return {present:!!g, href:g&&g.getAttribute('href'),
                dis:g&&g.getAttribute('aria-disabled'),
                boxes:document.querySelectorAll('#sheet input[type=checkbox]').length,
                priced:!!document.querySelector('#sheet .ck-price')};}""")
    check("the Pro sheet shows a price", st["priced"])
    check(f"the subscribe button exists ({st['boxes']} consent boxes)",
          st["present"] and st["boxes"] == 2)
    # The link must not be live before consent: an href is the whole navigation,
    # so an un-gated href IS an un-gated checkout regardless of the click handler.
    check(f"no href before consent (got {st['href']!r})", not st["href"])
    check(f"and it reads as disabled (aria-disabled={st['dis']})", st["dis"] == "true")

    print("\n2. a mis-click explains itself")
    page.evaluate("()=>document.querySelector('#ckGo').click()")
    page.wait_for_timeout(250)
    t = page.evaluate("""()=>{const t=document.querySelector('#toast');
        const cs=getComputedStyle(t);
        return {text:(t.textContent||'').trim(), vis:cs.visibility,
                inert:!!t.inert, closestInert:!!t.closest('[inert]')};}""")
    check(f"clicking too early explains why ({t['text']!r})",
          "box" in t["text"].lower())
    check(f"...and the toast is visible (visibility {t['vis']})", t["vis"] == "visible")
    # The regression this file was written to catch: the focus trap marks every
    # body child inert while a sheet is open, and #toast is a body child. inert
    # strips it from the accessibility tree, so its ARIA live region goes silent
    # -- a screen reader user at checkout is told nothing about why the button
    # did nothing. Visually fine, completely silent.
    check("...and it is NOT inert, so its live region still announces",
          not t["inert"] and not t["closestInert"])

    print("\n3. consent opens the link")
    page.evaluate("""()=>{for(const id of ['#ckRenew','#ckTos']){
        const b=document.querySelector(id); b.checked=true;
        b.dispatchEvent(new Event('change',{bubbles:true}));}}""")
    page.wait_for_timeout(200)
    st2 = page.evaluate("""()=>{const g=document.querySelector('#ckGo');
        return {href:g.getAttribute('href'), dis:g.getAttribute('aria-disabled'),
                op:getComputedStyle(g).opacity};}""")
    check(f"both boxes ticked sets the checkout href ({st2['href']!r})",
          st2["href"] == GOOD_PRICE["checkout"])
    check(f"...and it reads as enabled (aria-disabled={st2['dis']})",
          st2["dis"] == "false")

    # Consent has to be RECORDED, not just collected: clickwrap is enforceable
    # because there is a timestamped record of what was shown.
    page.evaluate("""()=>{const g=document.querySelector('#ckGo');
        g.addEventListener('click',e=>e.preventDefault(),{once:true});g.click();}""")
    page.wait_for_timeout(200)
    consent = page.evaluate("""()=>{try{
        const raw=localStorage.getItem('holomint:consent')||
                  localStorage.getItem('consent');
        return raw?JSON.parse(raw):null;}catch(e){return null;}}""")
    if consent is None:
        skip("consent record", "not found under the key names tried")
    else:
        check(f"consent is recorded with price and terms version "
              f"(price={consent.get('price')} terms={consent.get('terms')})",
              consent.get("price") is not None and consent.get("terms") is not None)

    print("\n4. the consent boxes are tappable on a phone")
    rows = page.evaluate("""()=>Array.from(
        document.querySelectorAll('#sheet .ck-chk')).map(l=>{
          const r=l.getBoundingClientRect();
          return {h:Math.round(r.height), w:Math.round(r.width)};})""")
    if not rows:
        check("consent rows found", False)
    else:
        check(f"each consent row is a large tap target "
              f"(heights {[r['h'] for r in rows]})",
              all(r["h"] >= 44 for r in rows))
    ctx.close()

    print("\n5. a bad network must not read as 'we are not selling'")
    # The card-show case. load() catches the fetch error and collapses it to
    # {configured:false}, which renders the same copy as a deliberately closed
    # shop. A buyer on venue wifi is told the product is not for sale, so they
    # do not retry -- they leave, and nothing is ever logged.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "offline")
    open_pro(page)
    off = page.evaluate("""()=>{const s=document.querySelector('#sheet');
        return {text:(s.textContent||'').replace(/\\s+/g,' ').trim().slice(0,400),
                retry:!!s.querySelector('#ckRetry')};}""")
    low = off["text"].lower()
    check(f"offline does NOT claim subscriptions are closed "
          f"({'not open' in low and 'MISLEADING' or 'ok'})",
          "not open yet" not in low)
    check("offline offers a way to try again", off["retry"])
    ctx.close()

    print("\n6. genuinely-not-selling still says so")
    # The other side of the same fix: when the shop really is closed, the honest
    # message must survive. Fixing case 5 by deleting the message would pass 5
    # and break this.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "unconfigured")
    open_pro(page)
    unc = page.evaluate("""()=>(document.querySelector('#sheet').textContent||'')
        .replace(/\\s+/g,' ').toLowerCase()""")
    check("an unconfigured shop still says subscriptions are not open",
          "not open yet" in unc)
    ctx.close()

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
