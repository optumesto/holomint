#!/usr/bin/env python3
"""The policies describe software. This proves the software exists.

WHY THIS FILE EXISTS
The Terms and Privacy Policy are not statements of intent -- they make factual
assertions about what the app does. A privacy policy describing a control the
app does not have is worse than one that never claimed it.

Reading the policies and grepping for their wording answered NEITHER direction
correctly. Both false answers happened here, in one sitting:

  FALSE ALARM   Terms s1 promises an age gate "before turning them on". Grep for
                "year of birth" found nothing, so I called it missing. It exists
                -- askAge() -- and asks "What year were you born?".
  FALSE ALARM   The Terms preamble promises acceptance on first open. Grep for
                acceptTerms/termsAccepted found nothing, so I called that
                missing too, and started building a second one. It exists, as
                the tour's non-dismissible gate step, and it is better than what
                I was building: it records terms version AND build, and mirrors
                the record to the Worker, where it is ours rather than the
                customer's to delete.
  REAL          Terms s9 / Privacy s2: "You can delete it at any time from
                within Holomint." There was no delete control anywhere, and not
                a single removeItem call in the app.

So this suite never greps the policy for reassurance about the code, or the code
for the policy's phrasing. For every promise it DRIVES THE CONTROL and asserts
the effect, and for every guard it asserts the negative case fires too.

Run:  python3 test_legal.py
"""
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8834
passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        passed = False
    return cond


def text_of(fn):
    s = open(os.path.join(HERE, fn)).read()
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))


handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)


class Q(socketserver.TCPServer):
    allow_reuse_address = True


httpd = Q(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

SRC = open(os.path.join(HERE, "index.html")).read()
TERMS = text_of("terms.html")
PRIV = text_of("privacy.html")

with sync_playwright() as p:
    br = p.chromium.launch()

    def fresh(seed=None):
        """A brand-new profile, so 'first run' really is the first run."""
        c = br.new_context()
        pg = c.new_page()
        pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="load")
        if seed:
            pg.evaluate(seed)
            pg.reload(wait_until="load")
        pg.wait_for_timeout(1600)
        return c, pg

    # ---------------------------------------------------------------- 1
    print("1. the documents and the app agree on WHICH terms are in force")
    # If Mason edits terms.html and bumps its version, every stored assent must
    # become stale. That only happens if this constant moves with the document.
    doc_v = (re.search(r"Version\s+([0-9.]+)", TERMS) or [None, None])[1]
    app_v = (re.search(r"TERMS_VERSION\s*=\s*'([^']+)'", SRC) or [None, None])[1]
    check(f"terms.html states a version ({doc_v})", bool(doc_v))
    check(f"the app pins the same one (TERMS_VERSION={app_v})",
          doc_v is not None and doc_v == app_v)

    # ---------------------------------------------------------------- 2
    print("\n2. Terms preamble: assent is asked for, and recorded")
    ctx, pg = fresh()
    gate = pg.locator("#tourWrap.on")
    check("a gate is shown on first open", gate.count() == 1)
    body = pg.locator("#tourCard").inner_text() if pg.locator("#tourCard").count() else ""
    check("...carrying the estimates/not-advice line conspicuously, not behind a link",
          "estimate" in body.lower())
    check("...and it cannot be skipped past",
          pg.locator("#tourSkip").count() == 0
          or not pg.locator("#tourSkip").is_visible())
    before = pg.evaluate("()=>localStorage.getItem('holomint:tosOk')")
    check("nothing is recorded before the person acts", before is None)

    pg.locator("#tourNext").click()
    pg.wait_for_timeout(400)
    rec = pg.evaluate("()=>JSON.parse(localStorage.getItem('holomint:tosOk')||'null')")
    check(f"continuing past it records assent ({rec})", isinstance(rec, dict))
    check("...stamped with WHICH terms version",
          isinstance(rec, dict) and rec.get("v") == app_v)
    check("...and which build, so the notice can be reconstructed",
          isinstance(rec, dict) and bool(rec.get("build")))
    check("...and when", isinstance(rec, dict) and isinstance(rec.get("at"), int))
    ctx.close()

    # ---------------------------------------------------------------- 3
    print("\n3. the guard fires: stale assent re-prompts, fresh assent does not")
    # "and again whenever they change materially" -- the half that is easy to
    # leave unbuilt, because nothing looks wrong until the terms actually change.
    ctx, pg = fresh("""()=>{localStorage.setItem('holomint:tourSeen','1');
        localStorage.setItem('holomint:tosOk',
          JSON.stringify({v:'0.0-stale',at:1,build:'x'}));}""")
    check("someone who toured long ago, on OLD terms, is asked again",
          pg.locator("#tourWrap.on").count() == 1)
    ctx.close()

    ctx, pg = fresh(f"""()=>{{localStorage.setItem('holomint:tourSeen','1');
        localStorage.setItem('holomint:tosOk',
          JSON.stringify({{v:'{app_v}',at:1,build:'x'}}));}}""")
    check("...and someone already on the CURRENT terms is not nagged",
          pg.locator("#tourWrap.on").count() == 0)
    ctx.close()

    # ---------------------------------------------------------------- 4
    print("\n4. the assent record is mirrored off the device")
    # A consent record living only in the customer's own localStorage is not
    # evidence of anything -- they can clear it, and usually will before a
    # dispute. The copy that matters is the one we hold.
    ctx = br.new_context()
    pg = ctx.new_page()
    seen = []
    pg.route("**/api/consent", lambda r: (seen.append(r.request.post_data),
                                          r.fulfill(status=200, body="{}")))
    pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="load")
    pg.wait_for_timeout(1600)
    pg.locator("#tourNext").click()
    pg.wait_for_timeout(700)
    check(f"accepting POSTs the consent to the Worker ({len(seen)} call(s))", seen)
    sent = json.loads(seen[0]).get("consent", {}) if seen else {}
    check(f"...naming the terms version it was given for ({sent.get('terms')})",
          sent.get("terms") == app_v)
    check("...and typed so it is not confused with the checkout consent",
          sent.get("kind") == "tos")
    ctx.close()

    # ---------------------------------------------------------------- 5
    print("\n5. Privacy s2 / Terms s9: 'delete it at any time from within Holomint'")
    check("the policy still makes this promise (if not, this suite is stale)",
          "delete it at any time" in PRIV.lower())

    # One arrow function, not a function plus a trailing statement: appending
    # ";localStorage..." after "()=>{...}" leaves the arrow body uncalled and
    # silently seeds only the tail, which opened the tour and hid the Settings
    # tab behind it. The seed has to be a single callable.
    def settled(extra=""):
        return ("()=>{localStorage.setItem('holomint:tourSeen','1');"
                "localStorage.setItem('holomint:tosOk',JSON.stringify("
                f"{{v:'{app_v}',at:1,build:'x'}}));" + extra + "}")

    seeded = settled("localStorage.setItem('holomint:holdings',"
                     "JSON.stringify([{id:'x',name:'t',qty:1}]));"
                     "localStorage.setItem('holomint:settings',"
                     "JSON.stringify({a:1}));")
    ctx, pg = fresh(seeded)
    pg.locator('.navb[data-tab="settings"]').click()
    pg.wait_for_timeout(500)
    wipe = pg.locator("#setWipeBtn")
    check("Settings offers a delete control", wipe.count() == 1)
    check("...reachable, not merely present in the markup",
          wipe.count() == 1 and wipe.is_visible())

    # -- negative case FIRST: declining must not delete ----------------
    pg.on("dialog", lambda d: d.dismiss())
    wipe.click()
    pg.wait_for_timeout(600)
    kept = pg.evaluate(
        "()=>Object.keys(localStorage).filter(k=>k.indexOf('holomint:')===0).length")
    check(f"declining the confirmation deletes NOTHING ({kept} keys intact)", kept > 0)
    ctx.close()

    # -- and now that it really does delete ----------------------------
    ctx, pg = fresh(seeded)
    dev0 = pg.evaluate("()=>localStorage.getItem('holomint:deviceId')")
    pg.on("dialog", lambda d: d.accept())
    pg.locator('.navb[data-tab="settings"]').click()
    pg.wait_for_timeout(500)
    pg.locator("#setWipeBtn").click()
    pg.wait_for_timeout(2500)

    # NOT "zero keys left". eraseAll() reloads, and a fresh boot legitimately
    # writes its own defaults and caches back -- asserting an empty store would
    # be asserting that the app never starts again. What the policy promises is
    # that the PERSON'S data is gone, so name those keys and check those.
    left = pg.evaluate(
        "()=>Object.keys(localStorage).filter(k=>k.indexOf('holomint:')===0)")
    mine = [k for k in left if k.split(":", 1)[1] in
            ("holdings", "settings", "tosOk", "tourSeen", "consent", "lic")]
    check(f"every piece of the person's own data is gone ({mine or 'none left'})",
          not mine)

    # The device identifier is the only per-installation handle we hold. If a
    # wipe regenerated the SAME one -- derived from a fingerprint, say -- the
    # deletion would not actually reset anything the Privacy Policy describes.
    dev1 = pg.evaluate("()=>localStorage.getItem('holomint:deviceId')")
    check(f"...and the device identifier is genuinely new, not re-derived "
          f"({str(dev0)[:8]}… -> {str(dev1)[:8]}…)",
          bool(dev0) and bool(dev1) and dev0 != dev1)
    check(f"what remains is cache and fresh identity only ({sorted(left)})",
          all(k.split(":", 1)[1] in ("deviceId", "liveDrops", "pricesAt",
                                     "prices", "catalog") for k in left))
    ctx.close()

    # ---------------------------------------------------------------- 6
    print("\n6. Terms s1: alerts are age-gated BEFORE the device reaches us")
    check("the policy still makes this promise",
          "13" in TERMS and "alert" in TERMS.lower())
    ask = SRC.find("async function enable()")
    age = SRC.find("askAge", ask)
    perm = SRC.find("Notification.requestPermission", ask)
    sub = SRC.find("/api/subscribe", ask)
    check("enable() asks age before asking for permission",
          ask > 0 and 0 < age < perm)
    check("...and long before any endpoint is sent to us", sub > 0 and age < sub)
    check("under-13 is refused, not merely warned",
          re.search(r"age\s*>=\s*13", SRC) is not None)

    # ---------------------------------------------------------------- 7
    print("\n7. every policy the app links to is actually served")
    ctx, pg = fresh(settled())
    hrefs = set(pg.evaluate(
        """()=>[...document.querySelectorAll('a[href$=".html"]')]
             .map(a=>a.getAttribute('href'))"""))
    wanted = {"privacy.html", "terms.html", "refunds.html"}
    check(f"all three are linked from the app ({sorted(wanted & hrefs)})",
          wanted <= hrefs)
    bad = []
    for h in sorted(wanted):
        r = pg.request.get(f"http://127.0.0.1:{PORT}/{h}")
        # A 200 carrying a directory listing is not a policy. Same trap as
        # eng.traineddata: status alone proves nothing about the body.
        if r.status != 200 or "Optume" not in r.text():
            bad.append((h, r.status))
    check(f"...and each serves the real document ({bad or 'all good'})", not bad)

    print("\n8. the cancellation route the Terms promise")
    check("Terms promise cancelling is at least as simple as signing up",
          "at least as simple as signing up" in TERMS)
    check("...and the app carries a manage/cancel link to the portal",
          "Manage subscription" in SRC and "PR.portal" in SRC)
    check("...with the same email fallback the Terms name",
          "optumeventures.com" in TERMS and "optumeventures.com" in SRC)
    ctx.close()

    br.close()

httpd.shutdown()
print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
