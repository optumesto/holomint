#!/usr/bin/env python3
"""
Tap-target tests: every control big enough to hit, and nothing stealing a
neighbour's taps.

Run:  python3 test_tap_targets.py
Needs: pip install -r requirements-dev.txt && python3 -m playwright install chromium

Measuring this needs care, because the painted box is NOT the hit target. A
transparent ::after with a negative inset makes a 17px circle a 35px target
without moving a pixel, so reading getBoundingClientRect alone reports controls
as failing when they pass. It also cuts the other way, which is the expensive
half: an expanded ::after that reaches past its own row silently takes the
taps meant for whatever it overlaps. That is invisible in a screenshot and
invisible in a diff -- the control still looks right and still highlights on
hover, it just does the wrong thing under a thumb.

So this file asserts two different things:

  * SIZE, from the painted box, for controls that grow honestly. Deterministic,
    no scrolling, no hit-testing.
  * OWNERSHIP, by hit-testing, for the two controls that are expanded rather
    than grown -- .hint and the .seg.sm chips. Both are capped BELOW 44px on
    purpose, by a measured neighbour rather than by taste, and the exception
    list below records which neighbour, so that a later "fix" to 44 fails here
    with the reason instead of quietly breaking the field underneath.
"""
import http.server
import threading
import functools
import sys
import os

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shots  # noqa: E402  (reused for its tour dismissal, which waits properly)

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8807
TAP = 44

passed = True
ran = 0


def check(label, cond):
    global passed, ran
    ran += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    passed &= bool(cond)


def skip(label, why):
    """Never let a check that did not run read like one that passed."""
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


# Controls that are deliberately smaller than TAP, and what caps them.
# The painted height is NOT pinned -- .seg.sm chips render 22px in one row and
# 24px in another, so an exact number here would be a false failure. What is
# asserted is the pair of properties that actually matter: the ::after
# expansion exists at all (hit > painted), and it stays under TAP (because
# reaching TAP was measured taking the neighbour's taps).
CAPPED = [
    (".hint",
     "sits on the label line directly above a field; at 44 it reaches 13px "
     "into the field and a tap there opens the tooltip instead"),
    (".seg.sm button",
     "6px of clearance to the control above and 2px between chips; at 44 it "
     "ate the bottom of the holdings search field"),
]

# Families that must grow honestly to TAP.
GROWN = ["button.ghost", "a.ghost", ".probtn", ".swbtn", ".scanbtn",
         "input:not([type=checkbox]):not([type=radio])", "select"]

MEASURE = r"""
(sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    let p = el, hidden = false;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      if (cs.display === 'none' || cs.visibility === 'hidden' ||
          cs.pointerEvents === 'none' || p.hasAttribute('inert')) { hidden = true; break; }
      p = p.parentElement;
    }
    if (hidden) continue;
    out.push({id: el.id || el.className || el.tagName,
              h: Math.round(r.height), w: Math.round(r.width)});
  }
  return out;
}
"""

# Walk out from a control's centre until elementFromPoint stops resolving to it.
# This is what a thumb actually gets, ::after included.
HIT = r"""
(sel) => {
  // Every match, not just the first: the first .hint on a screen is often
  // inside a collapsed card, and returning null for it turned the two
  // assertions that matter most into permanent SKIPs.
  const all = Array.from(document.querySelectorAll(sel));
  if (!all.length) return null;
  let blocked = 0;
  for (const el of all) {
    const r0 = el.getBoundingClientRect();
    if (!r0.width && !r0.height) { blocked++; continue; }
    if (r0.top < 0 || r0.bottom > innerHeight) {
      try { el.scrollIntoView({block: 'center'}); } catch (e) {}
    }
    const b = el.getBoundingClientRect();
    const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
    if (cx < 0 || cy < 0 || cx >= innerWidth || cy >= innerHeight) { blocked++; continue; }
    const owns = (t) => !!t && (t === el || el.contains(t));
    if (!owns(document.elementFromPoint(cx, cy))) { blocked++; continue; }
    const reach = (dy) => {
      let d = 0;
      for (let s = 1; s <= 40; s++) {
        const y = cy + dy * s;
        if (y < 0 || y >= innerHeight) break;
        if (!owns(document.elementFromPoint(cx, y))) break;
        d = s;
      }
      return d;
    };
    return {covered: false, h: reach(-1) + reach(1) + 1,
            painted: Math.round(b.height), tried: blocked + 1, of: all.length};
  }
  return {covered: true, of: all.length};
}
"""

httpd = serve()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(service_workers="block",
                              viewport={"width": 390, "height": 844},
                              device_scale_factor=1, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**://api.pokemontcg.io/**", lambda r: r.abort())
    page.add_init_script(
        "try{localStorage.setItem('holomint:tourSeen','1');}catch(e){}")
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="commit")
    for _ in range(400):
        if page.evaluate("window.CatalogState") == "ready":
            break
        page.wait_for_timeout(50)
    page.add_style_tag(content="*,*::before,*::after{animation-duration:0s !important;"
                               "transition-duration:0s !important}#splash{display:none !important}")
    # shots.dismiss_tour, not a local reimplementation: it WAITS for the tour to
    # appear before clicking it away. Doing that inline raced -- the loop found
    # no tour, exited, and the tour opened immediately afterwards, so every hit
    # test below was really measuring the tour card.
    shots.dismiss_tour(page)
    page.wait_for_timeout(400)
    # The tour dimmer collapses to 0x0 once the tour is really gone. Waiting for
    # that rather than assuming it, because a dimmer still covering the page
    # would make every hit test below report the dimmer and look like chaos --
    # or worse, get quietly explained away as noise.
    dim = page.evaluate("""()=>{const d=document.querySelector('#tourDim');
        if(!d) return {gone:true,box:[0,0]};
        const r=d.getBoundingClientRect();
        return {gone:r.width===0&&r.height===0,
                box:[Math.round(r.width),Math.round(r.height)]};}""")
    check(f"tour dimmer is gone before hit-testing (box {dim['box']})", dim["gone"])

    print("\nControls that grow to the tap size:")
    seen_any = False
    for tab in ["block", "port", "slab", "settings"]:
        page.evaluate("(t)=>{try{switchTab(t)}catch(e){"
                      "const b=document.querySelector('[data-tab=\"'+t+'\"]');"
                      "if(b)b.click();}}", tab)
        page.wait_for_timeout(400)
        for sel in GROWN:
            els = page.evaluate(MEASURE, sel)
            if not els:
                continue
            seen_any = True
            short = [e for e in els if e["h"] < TAP]
            check(f"{tab}: {len(els):2d}x {sel[:44]:44s} all >= {TAP}px"
                  + (f" (worst {min(e['h'] for e in short)}px)" if short else ""),
                  not short)
    if not seen_any:
        skip("grown controls", "no controls matched -- selectors are stale")
        passed = False

    print("\nControls capped below the tap size by a neighbour, on purpose:")
    for sel, why in CAPPED:
        page.evaluate("()=>{try{switchTab('port')}catch(e){}}")
        page.wait_for_timeout(400)
        got = page.evaluate(MEASURE, sel)
        if not got:
            skip(f"{sel} painted box", "not present on this screen")
            continue
        check(f"{sel} paints small on purpose ({got[0]['h']}px)", got[0]["h"] < TAP)
        h = page.evaluate(HIT, sel)
        if h is None or h.get("covered"):
            skip(f"{sel} hit area", "off-screen or covered here")
            continue
        # Expansion present: catches someone deleting the ::after.
        check(f"{sel} is expanded past its box ({h['painted']}px painted -> "
              f"{h['h']}px hit)", h["h"] > h["painted"])
        # And still capped: catches someone "fixing" it to 44 and silently
        # taking the neighbour's taps. The reason travels with the assertion.
        check(f"...but stays under {TAP}px, because it {why[:60]}... "
              f"(got {h['h']}px)", h["h"] < TAP)

    print("\nExemptions and the slider hold:")
    # The checkboxes live behind collapsed cards and the checkout sheet, so
    # there is usually none on screen to measure. The exemption is a CSS
    # contract though -- min-height beats height, so without the carve-out the
    # 44px rule turns a 17px checkbox into a 44px box -- and resolved style
    # answers that whether or not the control is currently painted.
    cbs = page.evaluate("""()=>Array.from(document.querySelectorAll(
        'input[type=checkbox],input[type=radio]')).map(el=>{
          const cs=getComputedStyle(el);
          const r=el.getBoundingClientRect();
          return {mh:cs.minHeight, h:cs.height,
                  shown:!!(r.width||r.height), rh:Math.round(r.height)};})""")
    if not cbs:
        check("checkbox exemption is exercised (index.html ships six)", False)
    else:
        bad = [c for c in cbs if c["mh"] not in ("0px", "auto", "none")]
        check(f"{len(cbs)} checkboxes are exempt from the {TAP}px min-height "
              f"(min-heights: {sorted({c['mh'] for c in cbs})})", not bad)
        shown = [c for c in cbs if c["shown"]]
        if shown:
            check(f"...and the {len(shown)} on screen render small "
                  f"(tallest {max(c['rh'] for c in shown)}px)",
                  max(c["rh"] for c in shown) < 24)
        else:
            skip("rendered checkbox height", "none painted; CSS contract asserted above")

    page.evaluate("()=>{try{switchTab('block')}catch(e){}}")
    page.wait_for_timeout(400)
    # The track is painted by ::-webkit-slider-runnable-track, which lives in
    # the shadow tree -- getComputedStyle reports the host's height for it, not
    # the track's, so asserting on that number would be asserting on nothing.
    # What matters behaviourally is that the whole row grabs, not just a 6px
    # ribbon; the 6px LOOK is what shots.py covers.
    rng = page.evaluate("""()=>{const el=document.getElementById('rate');
        if(!el) return null;
        el.scrollIntoView({block:'center'});
        const r=el.getBoundingClientRect();
        const x=r.left+r.width/2;
        const own=(y)=>{const t=document.elementFromPoint(x,y);return t===el;};
        return {h:Math.round(r.height), top:own(r.top+3), mid:own(r.top+r.height/2),
                bot:own(r.bottom-3)};}""")
    if rng is None:
        skip("range slider", "#rate not present")
    else:
        check(f"slider grabs across {TAP}px (got {rng['h']}px)", rng["h"] >= TAP)
        check("...and the whole row grabs, not just the 6px track "
              f"(top={rng['top']} mid={rng['mid']} bottom={rng['bot']})",
              rng["top"] and rng["mid"] and rng["bot"])

    print("\nNobody steals a neighbour's taps:")
    # The bug this catches: .hint's expanded ::after reaching down into the
    # field below it, so tapping the field's top edge opened a tooltip.
    # Depth, not a single edge pixel: a glyph's line box overhanging an input by
    # a pixel is noise, while an expanded ::after eats 8-13px and is the bug.
    STEAL = r"""(limit)=>{
      const out=[];
      for (const el of document.querySelectorAll('input,select')) {
        const r=el.getBoundingClientRect();
        if(!r.width||!r.height) continue;
        if(r.top<0||r.bottom>innerHeight) continue;
        const x=r.left+r.width/2;
        if(x<0||x>=innerWidth) continue;
        let d=0, thief=null;
        for(let y=Math.ceil(r.top)+1; y<r.top+r.height/2 && y<innerHeight; y++){
          const t=document.elementFromPoint(x,y);
          if(t && t!==el && !el.contains(t)){ d=y-r.top; thief=t; } else break;
        }
        if(d>limit) out.push((el.id||el.tagName)+' loses '+Math.round(d)+'px to '+
          (thief.tagName+(thief.id?'#'+thief.id:'')+
           (typeof thief.className==='string'&&thief.className?'.'+thief.className.split(/\s+/)[0]:'')));
      }
      return out;}"""
    steal = page.evaluate(STEAL, 3)
    check("no field loses its top edge to another control"
          + (f" ({'; '.join(steal[:3])})" if steal else ""), not steal)

    # Prove the ownership probe can fail. Without this, a probe that silently
    # returned nothing would look identical to a clean app.
    print("\nProving the steal check fires:")
    page.add_style_tag(content="input,select{z-index:auto !important}"
                               ".hint::after{inset:-22px !important;z-index:9 !important}")
    page.wait_for_timeout(200)
    mutated = page.evaluate(STEAL, 3)
    check(f"a deliberately over-expanded .hint IS caught stealing "
          f"({len(mutated)} field(s)) -- so the clean result above means something",
          len(mutated) > 0)

    browser.close()

httpd.shutdown()
print(f"\n{ran} checks ran")
print("PASS" if passed else "FAIL")
sys.exit(0 if passed else 1)
