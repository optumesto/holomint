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

    print("\n7. a closed overlay is inert, not merely off-screen")
    # The sheet was parked with transform:translateY(105%) and nothing else, so
    # it stayed rendered, hit-testable and focusable: Cancel and Save sat in the
    # tab order and the accessibility tree while the app looked closed. Asserted
    # by actually trying to focus them, because "can I focus it" is the thing
    # that matters and a computed style is only evidence for it.
    def focusable_count(sel):
        return page.evaluate("""(sel)=>{const r=document.querySelector(sel);
            if(!r)return -1;
            let n=0;
            r.querySelectorAll('button,a[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')
             .forEach(el=>{ try{ el.focus(); if(document.activeElement===el) n++; }catch(e){} });
            try{document.activeElement.blur();}catch(e){}
            return n;}""", sel)

    set_overlay(page, "#sheet", False)
    page.wait_for_timeout(420)   # visibility is delayed by the slide duration
    st = page.evaluate("""()=>{const e=document.querySelector('#sheet');
        const cs=getComputedStyle(e);return{v:cs.visibility,pe:cs.pointerEvents};}""")
    check(f"closed sheet is visibility:hidden (got {st['v']})", st["v"] == "hidden")
    check(f"closed sheet ignores pointers (got {st['pe']})", st["pe"] == "none")
    check("nothing inside a closed sheet can take focus", focusable_count("#sheet") == 0)

    set_overlay(page, "#sheet", True)
    page.wait_for_timeout(200)
    st = page.evaluate("""()=>{const e=document.querySelector('#sheet');
        const cs=getComputedStyle(e);return{v:cs.visibility,pe:cs.pointerEvents};}""")
    check("an OPEN sheet is visible again", st["v"] == "visible")
    check("an OPEN sheet takes pointers again", st["pe"] == "auto")
    # The negative case: if this is 0 the test above proves nothing, because a
    # sheet whose buttons are never focusable would pass it trivially.
    check("...and its buttons CAN take focus (guard proven live)",
          focusable_count("#sheet") > 0)
    set_overlay(page, "#sheet", False)
    page.wait_for_timeout(420)

    tst = page.evaluate("""()=>{const e=document.querySelector('#toast');
        const cs=getComputedStyle(e);return{v:cs.visibility,pe:cs.pointerEvents};}""")
    check(f"hidden toast is visibility:hidden (got {tst['v']})", tst["v"] == "hidden")
    check(f"hidden toast ignores pointers (got {tst['pe']})", tst["pe"] == "none")

    print("\n5. an open overlay keeps the keyboard inside it")
    # Making the closed overlays inert (above) fixed only half the problem: a
    # keyboard user could still Tab straight OUT of an open modal and into the
    # page behind it, which they cannot see. Measured before the fix: one Tab
    # off the sheet's button reached <body>, and the next eight walked through
    # #proBtn, #search and the scan buttons.
    def where(steps):
        """Tab n times, reporting whether focus is still inside the sheet."""
        out = []
        for _ in range(steps):
            page.keyboard.press("Tab")
            out.append(page.evaluate("""()=>{const a=document.activeElement;
                const s=document.querySelector('#sheet');
                return {inside: !!(s && s.contains(a)),
                        el: a.tagName + (a.id ? '#' + a.id : '')};}"""))
        return out

    # Wait for the previous section's sheet to be fully gone before touching
    # focus. It closes over ~420ms and the background stays inert until it is,
    # so focusing too early silently does nothing -- and this section then
    # reported "closing did not restore focus" when the truth was that focus was
    # never placed. Roughly 1 run in 4. A flaky test is worse than no test: it
    # teaches you to skip past red.
    # #scanBtn lives on the Trade panel, and a panel that is not .on is display:
    # none -- focus() on it silently does nothing. So put the tab back first,
    # then wait for the button to be genuinely focusable: no overlay up, not
    # inert, and actually rendered. Checking inertness alone was not enough and
    # left this failing about 1 run in 3.
    page.evaluate("()=>{try{switchTab('block')}catch(e){}}")
    for _ in range(60):
        if page.evaluate("""()=>{const s=document.querySelector('#sheet');
              const open=s&&(s.classList.contains('show')||s.classList.contains('on'));
              const b=document.querySelector('#scanBtn');
              return !open && !!b && !b.closest('[inert]')
                     && b.getBoundingClientRect().height>0;}"""):
            break
        page.wait_for_timeout(50)
    opener = page.evaluate("""()=>{const b=document.querySelector('#scanBtn');
        if(b){b.focus();return document.activeElement.id;}return null;}""")
    # Assert the precondition rather than letting it poison the checks below.
    check(f"the opener could be focused before opening the sheet (got {opener!r})",
          opener == "scanBtn")
    page.evaluate("""()=>{Sheet.open('Focus test',
        [{type:'static',html:'<div class="sub">trap</div>'}],'Close',function(){});}""")
    page.wait_for_timeout(450)

    # Job 1: opening moves focus into the dialog -- onto the CONTAINER, and that
    # is the intended behaviour, not a near miss. firstFocusable() returns the
    # element itself on purpose: the first descendant in the sheet's DOM order
    # is the licence key input on the Pro sheet, which throws the mobile
    # keyboard over the offer and invites autofill, and elsewhere it is Cancel,
    # where a stray Enter dismisses the dialog. Pinned here so that a future
    # trap does not "helpfully" walk to the first control again.
    landed = page.evaluate("""()=>{const s=document.querySelector('#sheet');
        const a=document.activeElement;
        return {inside: !!(s && s.contains(a)), onContainer: a===s,
                dialog: s.getAttribute('role'), modal: s.getAttribute('aria-modal'),
                el: a.tagName + (a.id ? '#' + a.id : '')};}""")
    check(f"opening the sheet moves focus into it (on {landed['el']})",
          landed["inside"])
    check(f"...onto the container by design, not the first control "
          f"(on {landed['el']})", landed["onContainer"])
    check(f"...and it announces as a modal dialog "
          f"(role={landed['dialog']} aria-modal={landed['modal']})",
          landed["dialog"] == "dialog" and landed["modal"] == "true")

    # Job 2: Tab cannot leave. 12 presses is more than the sheet holds, so a
    # leak shows up as a False rather than as a lucky wrap.
    trail = where(12)
    escaped = [t for t in trail if not t["inside"]]
    check("12 Tabs cannot leave the open sheet"
          + (f" (leaked to {', '.join(t['el'] for t in escaped[:4])})" if escaped else ""),
          not escaped)

    # The background really is unreachable, not merely skipped by luck.
    bg = page.evaluate("""()=>{const b=document.querySelector('#scanBtn');
        if(!b) return 'missing';
        b.focus();
        return document.activeElement===b ? 'took focus' : 'refused';}""")
    check(f"a control behind the open sheet cannot take focus (got {bg})",
          bg == "refused")

    # Job 3: closing gives the caret back to whatever opened it, instead of
    # dropping it on <body> so the next Tab restarts at the top of the page.
    #
    # Honest limit: this asserts the BEHAVIOUR, not our implementation of it.
    # Deleting releaseFocus's restore leaves this check green, because Chromium
    # also restores focus by itself when an element stops being inert. Our
    # restore stays anyway -- that recovery is not specified, and relying on one
    # engine's courtesy for keyboard access is how the safe-area rules ended up
    # dead for months. So: a real guard against the behaviour regressing, not
    # evidence that our code is what provides it.
    set_overlay(page, "#sheet", False)
    page.wait_for_timeout(450)
    back = page.evaluate("()=>document.activeElement.id||document.activeElement.tagName")
    check(f"closing restores focus to the opener (#{opener} -> {back})",
          opener is not None and back == opener)

    # And the negative case: with the sheet shut, the page behind must be
    # reachable again. Without this, "cannot take focus" above would pass on a
    # page where nothing is ever focusable.
    again = page.evaluate("""()=>{const b=document.querySelector('#scanBtn');
        b.focus();return document.activeElement===b;}""")
    check("...and the background is focusable again once it closes", again)

    print("\n6. the confirm dialog gets the same protections as the rest")
    # Sheet.confirm's #cfmModal is built on first use, and BOTH overlay
    # observers registered by querySelector at load -- so the one dialog that
    # guards irreversible actions was skipped by both, even though it is listed
    # in OVERLAYS. Measured before the fix: no role=dialog, no aria-modal, no
    # scroll lock, focus never entered it, and one Tab reached #proBtn behind.
    page.evaluate("""()=>Sheet.confirm('Delete?','<div>gone for good</div>',
        'Delete',function(){})""")
    page.wait_for_timeout(450)
    cfm = page.evaluate("""()=>{const w=document.getElementById('cfmModal');
        if(!w) return null;
        return {role:w.getAttribute('role'), modal:w.getAttribute('aria-modal'),
                bodyPos:getComputedStyle(document.body).position,
                navInert:!!document.querySelector('#botnav').inert,
                inside:w.contains(document.activeElement),
                active:document.activeElement.id||document.activeElement.tagName};}""")
    if cfm is None:
        check("Sheet.confirm built its dialog", False)
    else:
        check(f"confirm announces as a modal dialog "
              f"(role={cfm['role']} aria-modal={cfm['modal']})",
              cfm["role"] == "dialog" and cfm["modal"] == "true")
        check(f"confirm locks the page behind it (body position {cfm['bodyPos']})",
              cfm["bodyPos"] == "fixed")
        check("confirm inerts the page behind it", cfm["navInert"])
        check(f"confirm takes focus (on {cfm['active']})", cfm["inside"])

        trail = []
        for _ in range(8):
            page.keyboard.press("Tab")
            trail.append(page.evaluate("""()=>{const w=document.getElementById('cfmModal');
                const a=document.activeElement;
                return {inside:w.contains(a), el:a.id||a.tagName};}"""))
        out = [t for t in trail if not t["inside"]]
        check("8 Tabs cannot leave the confirm dialog"
              + (f" (leaked to {', '.join(t['el'] for t in out[:4])})" if out else ""),
              not out)

        # Escape must reach it too: it is the one dialog where the wrong answer
        # is unrecoverable, so cancelling has to be the easy path.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        closed = page.evaluate("""()=>{const w=document.getElementById('cfmModal');
            return !w.classList.contains('show');}""")
        check("Escape cancels the confirm", closed)
        # ...and the lock comes back off, or the app is stuck unscrollable.
        page.wait_for_timeout(200)
        after = page.evaluate("""()=>({pos:getComputedStyle(document.body).position,
            navInert:!!document.querySelector('#botnav').inert})""")
        check(f"closing it releases the scroll lock (position {after['pos']})",
              after["pos"] != "fixed")
        check("closing it releases the inert background", not after["navInert"])

        # Back must cancel it rather than leaving the app. In an installed PWA
        # that is the difference between "no, wait" and being thrown out to the
        # home screen with the delete unconfirmed.
        page.evaluate("""()=>Sheet.confirm('Delete?','<div>gone</div>',
            'Delete',function(){window.__cfmFired=true;})""")
        page.wait_for_timeout(450)
        page.go_back()
        page.wait_for_timeout(450)
        state = page.evaluate("""()=>({open:document.getElementById('cfmModal')
                .classList.contains('show'),
            fired:!!window.__cfmFired,
            stillApp:!!document.getElementById('botnav')})""")
        check("back cancels the confirm instead of leaving the app",
              not state["open"] and state["stillApp"])
        # Cancelling must not run the destructive callback.
        check("...and back does NOT fire the destructive action",
              not state["fired"])

    browser.close()

httpd.shutdown()
print("\nPASS" if passed else "\nFAIL")
sys.exit(0 if passed else 1)
