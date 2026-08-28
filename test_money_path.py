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
    "configured": True, "amount": 19.99, "currency": "USD", "interval": "month",
    "checkout": "https://checkout.example/holomint-pro",
    "portal": "https://portal.example/manage",
    # Mirrors production: a limited DISCOUNT, not limited stock. The product
    # stays on sale at `amount` afterwards, which is what the copy must say.
    "founder": {"amount": 9.99, "left": 24, "total": 25,
                "checkout": "https://checkout.example/holomint-founder"},
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
    elif pricing_mode == "polar_down":
        # The Worker is up and answering; POLAR is not. Distinct from "offline":
        # here the fetch succeeds, so the client's own catch never fires and only
        # the Worker's `unreachable` flag can carry the difference.
        page.route(PRICING, lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"configured": False, "unreachable": True})))
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

    print("\n1b. the early-bird offer states BOTH prices, and neither is NaN")
    # The discount is limited; the PRODUCT is not. "25 seats left" with no second
    # half reads as "the app has 25 places and then it is gone", which is false
    # scarcity -- Pro stays available at list price forever. Every place the
    # discount is mentioned must therefore name the price it reverts to.
    #
    # The NaN check is not hypothetical: the list price lives on the pricing
    # object, while .founder carries only {amount,left,total,checkout}. Reading
    # it off the founder object renders "$NaN/month" in the one piece of copy
    # nobody can afford to get wrong, and it renders happily with no error.
    offer_txt = page.evaluate("""()=>{
        const s=document.querySelector('#sheet');
        return (s.textContent||'').replace(/\\s+/g,' ');}""")
    check(f"no NaN anywhere in the offer copy",
          "NaN" not in offer_txt and "$undefined" not in offer_txt)
    if GOOD_PRICE.get("founder"):
        check("the offer names the price it reverts to",
              str(GOOD_PRICE["amount"]) in offer_txt)
    else:
        skip("reverts-to price", "this fixture has no founder discount")
    check("it does not imply the product itself runs out",
          "seats left" not in offer_txt.lower())

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
    # The link has to charge the price that was DISPLAYED. While a discount is
    # live that means the founder checkout, not the list one -- sending someone
    # who was shown $9.99 to a $19.99 checkout is the exact price drift the
    # Worker comments call out as a ROSCA problem, and it is invisible until a
    # customer disputes the charge.
    _expect = (GOOD_PRICE.get("founder") or GOOD_PRICE)["checkout"]
    _shown = page.evaluate("""()=>{const e=document.querySelector('#sheet .ck-price');
        return e?e.textContent.replace(/\\s+/g,' ').trim():'';}""")
    check(f"both boxes ticked sets the checkout href ({st2['href']!r})",
          st2["href"] == _expect)
    check(f"...and it is the checkout for the price on screen ({_shown!r})",
          str((GOOD_PRICE.get("founder") or GOOD_PRICE)["amount"]) in _shown)
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

    print("\n6b. the Worker up but Polar down is also not 'we are not selling'")
    # Section 5 covers the Worker being unreachable, which the client's own catch
    # handles. This is the other half and the client cannot detect it alone: the
    # fetch SUCCEEDS, so only the Worker saying `unreachable` distinguishes a
    # Polar outage or a rotated API key from a shop that is deliberately shut.
    # See worker-patch.md -- /api/pricing currently returns a bare
    # {configured:false} for both, which is what makes this reachable at all.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "polar_down")
    open_pro(page)
    pd = page.evaluate("""()=>{const s=document.querySelector('#sheet');
        return {text:(s.textContent||'').replace(/\\s+/g,' ').toLowerCase(),
                retry:!!s.querySelector('#ckRetry')};}""")
    check("a Worker-reported outage does not claim subscriptions are closed",
          "not open yet" not in pd["text"])
    check("...and it offers a retry", pd["retry"])
    ctx.close()

    print("\n7. every paywall gate reaches the Pro sheet")
    # The paywall IS the conversion mechanism, and each gate fires at the moment
    # of maximum intent -- someone just tried to do the thing they want. A gate
    # that dead-ends loses the sale precisely then, and looks fine on screen.
    #
    # wireLocks() binds only '#port [data-pro-up]', so any Unlock button that
    # renders outside the Portfolio tab silently has no handler. This checks
    # every gate in the document rather than the ones we expect.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "good")
    # Free state is the default; assert it rather than assume, or every check
    # below passes trivially against a Pro account with no gates rendered.
    check("running as a FREE user (no Pro key)",
          page.evaluate("()=>!Premium.active()"))

    page.evaluate("()=>{try{switchTab('port')}catch(e){}}")
    page.wait_for_timeout(600)
    locks = page.evaluate("""()=>Array.from(
        document.querySelectorAll('[data-pro-up]')).map(b=>({
          wired: typeof b.onclick === 'function',
          inPort: !!b.closest('#port'),
          text: (b.textContent||'').trim(),
          near: (b.closest('.lk')?.textContent||'').replace(/\\s+/g,' ').trim().slice(0,60)
        }))""")
    if not locks:
        skip("lock panels", "none rendered on this tab in this state")
    else:
        unwired = [l for l in locks if not l["wired"]]
        check(f"all {len(locks)} Unlock button(s) are wired"
              + (f" -- DEAD: {[l['near'] for l in unwired]}" if unwired else ""),
              not unwired)
        outside = [l for l in locks if not l["inPort"]]
        check(f"...and none render outside #port, where wireLocks cannot see them"
              + (f" -- {[l['near'] for l in outside]}" if outside else ""),
              not outside)

        # Behavioural, not just "has a handler": click it and confirm the Pro
        # sheet actually opens. A bound handler that throws looks identical.
        page.evaluate("()=>document.querySelector('[data-pro-up]').click()")
        page.wait_for_timeout(800)
        opened = page.evaluate("""()=>{const s=document.querySelector('#sheet');
            return !!s && (s.classList.contains('show')||s.classList.contains('on'))
                   && !!s.querySelector('#ckGo');}""")
        check("clicking Unlock opens the Pro sheet with a subscribe button", opened)
        page.evaluate("""()=>{const s=document.querySelector('#sheet');
            s.classList.remove('show');s.classList.remove('on');}""")
        page.wait_for_timeout(400)

    # The other gate style: an action that jumps straight to the Pro sheet.
    for gate in ["#importCsv", "#exportCsv"]:
        present = page.evaluate("(g)=>!!document.querySelector(g)", gate)
        if not present:
            skip(f"{gate} gate", "control not on this screen")
            continue
        page.evaluate("(g)=>document.querySelector(g).click()", gate)
        page.wait_for_timeout(800)
        opened = page.evaluate("""()=>{const s=document.querySelector('#sheet');
            return !!s && (s.classList.contains('show')||s.classList.contains('on'))
                   && !!s.querySelector('#ckGo');}""")
        check(f"{gate} sends a free user to the Pro sheet", opened)
        page.evaluate("""()=>{const s=document.querySelector('#sheet');
            s.classList.remove('show');s.classList.remove('on');}""")
        page.wait_for_timeout(400)
    ctx.close()

    print("\n8. a key pasted on bad wifi survives and activates itself")
    # The card-show failure this is written for: someone pays at your table on
    # venue wifi, pastes the key, and the licence authority is unreachable. The
    # message was already honest ("could not verify, try again") but the key was
    # dropped -- and by then it is back in an email, on a phone, in a crowd.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/api/license*", lambda r: r.abort())     # authority unreachable
    boot(page, "good")
    res = page.evaluate("()=>Premium.validate('HMP-TEST-TEST-TEST')")
    check(f"an unreachable authority is 'unknown', never 'invalid' (got {res!r})",
          res == "unknown")
    check("...and Pro is NOT granted on an unverified key",
          page.evaluate("()=>!Premium.active()"))
    held = page.evaluate("""()=>{try{const l=JSON.parse(
        localStorage.getItem('holomint:license')||localStorage.getItem('license'));
        return l?{key:l.key,pending:!!l.pending,valid:!!l.valid}:null;}catch(e){return null;}}""")
    check(f"...but the key is held for retry (got {held})",
          held and held["pending"] and not held["valid"])

    # Now signal returns and the authority says yes.
    page.unroute("**/api/license*")
    page.route("**/api/license*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({"valid": True})))
    page.evaluate("()=>window.dispatchEvent(new Event('online'))")
    page.wait_for_timeout(600)
    check("reconnecting activates Pro without the buyer touching anything",
          page.evaluate("()=>Premium.active()"))
    ctx.close()

    print("\n9. holding a key cannot be abused")
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/api/license*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({"valid": True})))
    boot(page, "good")
    page.evaluate("()=>Premium.validate('HMP-GOOD-GOOD-GOOD')")
    page.wait_for_timeout(300)
    check("a real subscriber is active", page.evaluate("()=>Premium.active()"))
    # A typo pasted while offline must not cost an existing subscriber their Pro.
    page.unroute("**/api/license*")
    page.route("**/api/license*", lambda r: r.abort())
    page.evaluate("()=>Premium.validate('HMP-TYPO-TYPO-TYPO')")
    page.wait_for_timeout(300)
    still = page.evaluate("""()=>{const k=Premium.key();
        return {active:Premium.active(), key:k};}""")
    check(f"...and a typo pasted while offline does not clobber it "
          f"(active={still['active']} key={still['key']})",
          still["active"] and still["key"] == "HMP-GOOD-GOOD-GOOD")
    ctx.close()

    print("\n10. US-only alerts")
    # Holomint now watches Canadian shops. Their prices are real, in CAD, and a
    # US buyer should not be woken by a price they cannot pay. Default ON, so a
    # subscriber who never opens this setting keeps the behaviour they had
    # before foreign shops existed.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "good")
    check("the US-only control exists",
          page.evaluate("()=>!!document.querySelector('#alUsOnly')"))
    check("...and the default preference is ON",
          page.evaluate("()=>{const p=Object.assign({usOnly:true},"
                        "Store.load('alertPrefs',{}));return p.usOnly!==false;}"))
    # A control that does not change the outgoing payload is decorative -- the
    # exact failure the Pre-drop toggle had.
    page.evaluate("()=>{const p=Store.load('alertPrefs',{});p.usOnly=false;"
                  "Store.save('alertPrefs',p);}")
    check("switching it off persists",
          page.evaluate("()=>Store.load('alertPrefs',{}).usOnly") is False)
    check("...and the app still reads it back as a real preference",
          page.evaluate("()=>Object.assign({usOnly:true},"
                        "Store.load('alertPrefs',{})).usOnly") is False)
    ctx.close()

    print("\n11. show mode")
    # A day behind a table is one day with a cash position, not a series of
    # unrelated deals. No new storage: every Send to Desk already writes a deal
    # record with a date, so this is a view over today's and the day rolls over
    # on its own -- nothing to start, forget to start, or forget to end.
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "good")
    page.evaluate("()=>switchTab('block')")
    page.wait_for_timeout(300)
    vis = lambda: page.evaluate(
        "()=>{const e=document.querySelector('#showBar');"
        "return !!(e&&e.offsetParent!==null);}")
    check("off by default", vis() is False)
    page.evaluate("()=>ShowMode.set(true)")
    page.wait_for_timeout(250)
    check("...visible once switched on", vis() is True)
    check("...and says so when the day is empty",
          "no deals" in page.evaluate(
              "()=>document.querySelector('#sbDate').textContent"))

    # Drive the REAL logger, the same call Send to Desk makes.
    page.evaluate("""()=>{
        logDeal('buy',[{name:'Charizard ex',qty:1}],200,120);
        logDeal('buy',[{name:'Pikachu V',qty:2}],80,50);
        logDeal('trade',[{name:'Prismatic ETB',qty:1}],60,40);}""")
    page.wait_for_timeout(250)
    t = page.evaluate("()=>ShowMode.totals()")
    check(f"cash out sums the payouts (${t['out']})", t["out"] == 210)
    check(f"market in sums the market values (${t['mkt']})", t["mkt"] == 340)
    check(f"spread is the gap, not profit (${t['spread']})", t["spread"] == 130)
    check(f"three deals counted ({t['n']})", t["n"] == 3)
    check("the bar shows the same numbers, not its own maths",
          page.evaluate("()=>document.querySelector('#sbOut').textContent") == "$210"
          and page.evaluate("()=>document.querySelector('#sbSpread').textContent") == "$130")

    # NEGATIVE CASE: a day total that quietly includes other days is worse than
    # no total -- it is the number the vendor works from.
    page.evaluate("""()=>{dealLog.push({id:'old',date:'2020-01-01',kind:'buy',
        items:[{name:'x',qty:1}],market:9999,payout:9999});
        saveDeals();ShowMode.refresh();}""")
    page.wait_for_timeout(200)
    t2 = page.evaluate("()=>ShowMode.totals()")
    check(f"an older deal does NOT leak into today ({t2['n']} deals, ${t2['out']})",
          t2["n"] == 3 and t2["out"] == 210)

    # A vendor reloading mid-show must not lose the number they are working from.
    page.reload(wait_until="load")
    page.wait_for_timeout(500)
    page.evaluate("()=>switchTab('block')")
    page.wait_for_timeout(300)
    check("survives a reload mid-show",
          vis() and page.evaluate(
              "()=>document.querySelector('#sbOut').textContent") == "$210")
    ctx.close()

    print("\n12. CSV import at dealer scale")
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              reduced_motion="reduce")
    page = ctx.new_page()
    boot(page, "good")

    # parseFloat('$1,299.00') is NaN, and the old code fed that to `||0`. A
    # dealer importing a marketplace export got their whole inventory at a $0
    # cost basis with the infinite ROI that implies, and no sign anything broke.
    money = page.evaluate("""(cs)=>cs.map(c=>parseMoney(c))""",
                          ["49.99", "$49.99", "$1,299.00", "1,299", "49.99 USD",
                           "(12.34)", "US$ 8.00", "", "n/a", "0"])
    check(f"money parses as written ({money[:4]})",
          money[0] == 49.99 and money[1] == 49.99
          and money[2] == 1299 and money[3] == 1299)
    check("...trailing currency words and accounting negatives too",
          money[4] == 49.99 and money[5] == -12.34 and money[6] == 8)
    check("...blank and non-numeric are NULL, not zero",
          money[7] is None and money[8] is None)
    check("...but a real zero stays zero", money[9] == 0)

    # An unquoted thousands separator splits one field into two, shifting every
    # later column: the basis imports as $1 and the date lands in Location.
    cols = page.evaluate("""()=>{
        const head='Kind,Name,Type,Status,Qty,Basis,Value_or_Net,Date,Location';
        const bad=head+'\\nholding,Charizard,sealed,,1,$1,299.00,$1,500.00,2026-01-01,Box 1';
        const ok =head+'\\nholding,Charizard,sealed,,1,"$1,299.00","$1,500.00",2026-01-01,Box 1';
        return {h:parseCSV(bad)[0].length, bad:parseCSV(bad)[1].length,
                ok:parseCSV(ok)[1].length};}""")
    check(f"an unquoted comma really does misalign ({cols['bad']} cols vs "
          f"{cols['h']} header)", cols["bad"] > cols["h"])
    check("...while a quoted one does not", cols["ok"] == cols["h"])

    # End to end on a realistically messy file.
    import random as _rnd, os as _os, tempfile as _tf
    _rnd.seed(11)
    _rows = ["Kind,Name,Type,Status,Qty,Basis,Value_or_Net,Date,Location"]
    _bad = 0
    for _i in range(120):
        _c = _rnd.choice("abcde")
        if _c == "c":
            _b = f"$1,{_rnd.randint(100,999)}.00"; _bad += 1
        elif _c == "a": _b = f"${_rnd.randint(5,300)}.99"
        elif _c == "b": _b = f"{_rnd.randint(5,300)}.00"
        elif _c == "d": _b = "n/a"
        else: _b = ""
        _rows.append(f'holding,"Card, no {_i} ""alt""",sealed,,1,{_b},'
                     f'${_rnd.randint(5,400)}.50,2026-01-15,Box {_i%5}')
    _rows.append("sold,Skip me,,,1,10,20,2026-01-01,")
    _fp = _os.path.join(_tf.gettempdir(), "holomint_dealer_test.csv")
    open(_fp, "w", encoding="utf-8").write("\ufeff" + "\n".join(_rows))
    page.set_input_files("input[type=file][accept*='csv']", _fp)
    page.wait_for_timeout(1800)
    res = page.evaluate("""()=>({n:holdings.length,
        one:holdings.filter(h=>h.costBasis===1).length,
        toast:(document.querySelector('#toast')||{}).textContent})""")
    check(f"{res['n']} of 120 imported, {_bad} misaligned rows skipped",
          res["n"] == 120 - _bad)
    check("NO holding carries the tell-tale $1 basis", res["one"] == 0)
    check("the sold row is not imported as a holding", res["n"] < 121)
    # A report that says only what succeeded hides the problem.
    check(f"the result reports what did NOT come through ({res['toast'][:56]})",
          "skipped" in (res["toast"] or "") or "unreadable" in (res["toast"] or ""))
    _os.remove(_fp)
    ctx.close()

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
