#!/usr/bin/env python3
"""Holomint under WebKit -- the closest thing to iOS Safari without an iPhone.

WHY THIS FILE EXISTS
Every other suite runs on Chromium. Mason has no iPhone, and roughly half the
people who walk up to a card show booth do. Chromium passing says nothing about
whether the scanner opens on the device that person is holding.

WebKit is Safari's engine. It is NOT iOS Safari -- different memory ceilings, no
real camera, no Home Screen install, and Apple ships engine changes on its own
schedule -- so a pass here is evidence, not proof. What it DOES catch is the
whole class of failure that actually bites: an API that only Chromium has, a
syntax feature Safari lags on, a silent throw on load.

The specific Safari traps this checks, each of which has broken a real PWA:

  * ImageCapture does not exist in Safari. Code that news it up without a guard
    throws on the first shutter tap.
  * Video without `playsinline` opens fullscreen on iOS and the viewfinder is
    gone.
  * PushManager / Notification are unavailable in a Safari TAB. Web Push on iOS
    requires Add to Home Screen, so an app that just says "alerts off" leaves an
    iPhone user with no path to the core product.
  * OffscreenCanvas, createImageBitmap and Workers arrived late; the detector
    deliberately uses none of them.

Run:  python3 test_webkit.py
Needs: python3 -m playwright install webkit
"""
import functools
import http.server
import os
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8829
passed = True


def check(label, cond):
    global passed
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        passed = False
    return cond


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=HERE)

    class Q(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = Q(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


httpd = serve()
with sync_playwright() as p:
    try:
        wk = p.webkit.launch()
    except Exception as e:
        # SKIPPED must not read like PASS. If WebKit is not installed this file
        # has verified nothing, and must say so rather than exiting 0 quietly.
        print("\nWEBKIT NOT AVAILABLE -- this suite verified NOTHING.")
        print("  install with: python3 -m playwright install webkit")
        print(f"  ({str(e)[:120]})")
        httpd.shutdown()
        sys.exit(2)

    ctx = wk.new_context(**p.devices["iPhone 13"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    console_errs = []
    page.on("console",
            lambda m: console_errs.append(m.text) if m.type == "error" else None)

    page.goto(f"http://127.0.0.1:{PORT}/", wait_until="load")
    page.wait_for_timeout(2500)

    print("1. the app loads at all on Safari's engine")
    check(f"no uncaught page errors ({errors[:1] or 'none'})", not errors)
    check(f"no console errors ({console_errs[:1] or 'none'})", not console_errs)

    feat = page.evaluate("""()=>({
        ImageCapture:'ImageCapture' in window,
        getUserMedia:!!(navigator.mediaDevices&&navigator.mediaDevices.getUserMedia),
        push:'PushManager' in window,
        notif:'Notification' in window,
        inert:'inert' in HTMLElement.prototype,
        playsinline:!!document.querySelector('video[playsinline]'),
        CardFind:typeof CardFind!=='undefined',
        LotScanner:typeof LotScanner!=='undefined',
        ShowMode:typeof ShowMode!=='undefined',
        parseMoney:typeof parseMoney==='function'})""")

    print("\n2. the modules the product depends on are defined")
    for k in ("CardFind", "LotScanner", "ShowMode", "parseMoney"):
        check(f"{k} is available", feat[k] is True)

    print("\n3. the Safari traps")
    # This is the environment assertion. If a future WebKit ships ImageCapture
    # the guard is still correct, so this is informational rather than a
    # requirement -- but the GUARD itself is not optional.
    print(f"  [note] ImageCapture present in this WebKit: {feat['ImageCapture']}")
    src = open(os.path.join(HERE, "index.html")).read()
    check("ImageCapture is feature-detected before use",
          "window.ImageCapture" in src or "'ImageCapture' in window" in src)
    check("the viewfinder video carries playsinline "
          "(without it iOS goes fullscreen and the preview is gone)",
          feat["playsinline"] is True)
    check("getUserMedia exists on this engine", feat["getUserMedia"] is True)

    print("\n4. an iPhone in a TAB cannot receive push -- say so, do not just fail")
    check("push is genuinely unavailable in a tab here", feat["push"] is False)
    guide = page.evaluate("""()=>{const e=document.querySelector('#alertState')
        ||document.querySelector('#alertCard');
        return (e?e.innerText:'').replace(/\\s+/g,' ');}""")
    check("the app tells an iPhone user to Add to Home Screen",
          "home screen" in guide.lower())
    check("...and gives the actual steps, not just the requirement",
          "share" in guide.lower())

    print("\n5. the card detector RUNS on this engine")
    # The whole scanner is canvas + plain JS on purpose. This proves it, rather
    # than inferring it from the absence of exotic API calls.
    res = page.evaluate("""()=>{
        const c=document.createElement('canvas');c.width=900;c.height=700;
        const x=c.getContext('2d');
        x.fillStyle='#20304a';x.fillRect(0,0,900,700);
        for(const [px,py] of [[60,60],[340,60],[620,60]]){
          x.fillStyle='#e8d24a';x.fillRect(px,py,220,308);
          x.fillStyle='#2a6ad8';x.fillRect(px+16,py+40,188,150);
          x.fillStyle='#f4f4f4';x.fillRect(px+16,py+210,188,70);
        }
        const t0=performance.now();
        const found=CardFind.detect(c);
        const ms=Math.round(performance.now()-t0);
        let cropped=0;
        for(const f of found){
          const cc=CardFind.crop(c,f.quad,220,308,false); if(cc)cropped++; }
        return {found:found.length,cropped:cropped,ms:ms};}""")
    check(f"finds all three cards ({res['found']}) in {res['ms']}ms",
          res["found"] == 3)
    check(f"and rectifies every one of them ({res['cropped']})",
          res["cropped"] == 3)
    check(f"in a time a person would wait for ({res['ms']}ms < 3000)",
          res["ms"] < 3000)
    check("still no page errors after running the detector", not errors)

    print("\n6. the tab bar and scan button are reachable on an iPhone viewport")
    nav = page.evaluate("""()=>{
        const b=[...document.querySelectorAll('.navb,#scanBtn,.scanfab')]
                 .filter(e=>e.offsetParent!==null);
        return b.map(e=>{const r=e.getBoundingClientRect();
          return {id:e.id||e.className,w:Math.round(r.width),h:Math.round(r.height)};});}""")
    check(f"the bottom nav renders ({len(nav)} controls)", len(nav) >= 4)
    small = [n for n in nav if n["h"] < 30 or n["w"] < 30]
    check(f"every one is thumb-sized ({small or 'all >= 30px'})", not small)

    ctx.close()
    wk.close()

httpd.shutdown()
print("\n" + ("ALL TESTS PASSED" if passed else "SOME TESTS FAILED"))
sys.exit(0 if passed else 1)
