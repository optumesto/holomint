#!/usr/bin/env python3
"""Pins for the 2026-08-30 pre-launch review fixes (A2-A4, B1-B5).

Each check pins the SHAPE of a fix so it cannot silently regress. Structural
matches on the code, not prose, per the testing rules; the behavioural half is
carried by the existing Playwright suites, which load the fixed page for real.
"""
import re, sys

SRC = open('index.html', encoding='utf-8').read()
passed = failed = 0
def check(label, ok, detail=''):
    global passed, failed
    if ok: passed += 1; print(f'  [PASS] {label}')
    else:  failed += 1; print(f'  [FAIL] {label} {detail}')

def strip_comments(s):
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    return re.sub(r'(^|[^:])//[^\n]*', r'\1', s)

print('=== A2: back button cancels a sheet, never submits it ===')
# the OVER registry entry for #sheet, comments stripped so prose cannot satisfy it
over = re.search(r"\{sel:'#sheet',[^\n]*close:function\(\)\{([^}]*)\}", strip_comments(SRC))
check('the #sheet back-close exists', bool(over))
if over:
    body = over.group(1)
    check("...clicks #sheetCancel", "$('#sheetCancel')" in body, repr(body[:80]))
    check("...and never #sheetOk", "sheetOk" not in body, repr(body[:80]))

print('=== A3: booked holdings use the condition-adjusted price ===')
send = SRC[SRC.index("$('#sendDesk').onclick"):]
send = send[:send.index("const Receipt=")]
send_code = strip_comments(send)
check('sendDesk books via linePrice in both branches',
      send_code.count('pr=linePrice(p)') == 2, f"found {send_code.count('pr=linePrice(p)')}")
check('...and priceOf never prices a booked holding',
      'priceOf(' not in send_code)

print('=== A4: every tier survives a push-endpoint rotation ===')
resub = re.search(r"e\.data\.type==='push-resubscribe'([^\n]*)", strip_comments(SRC))
check('push-resubscribe handler exists', bool(resub))
if resub:
    check('...not gated on Premium', 'Premium' not in resub.group(1), repr(resub.group(1)[:60]))

print('=== B1: the reconnect handler calls a method that exists ===')
# comments stripped: the fix's own comment NAMES the dead method, and this
# check tripped on that prose the first time it ran -- the exact trap the
# testing rules describe. Code only.
check('PriceEngine.refresh is referenced nowhere in code', 'PriceEngine.refresh' not in strip_comments(SRC))
check('reconnect calls loadData instead',
      bool(re.search(r"addEventListener\('online'[\s\S]{0,600}?PriceEngine\.loadData", SRC)))

print('=== B2: enable() cannot hang or die silently ===')
en = SRC[SRC.index('async function enable()'):]
en = en[:en.index('async function disable()')]
check('serviceWorker.ready is raced against a timeout',
      'sw timeout' in en and 'Promise.race' in en)
check('subscribe() failure reaches a toast',
      bool(re.search(r'try\{[\s\S]{0,200}?pushManager\.subscribe[\s\S]{0,200}?\}catch', en)))
check('the /api/subscribe fetch failure reaches a toast',
      bool(re.search(r'try\{[\s\S]{0,250}?/api/subscribe[\s\S]{0,250}?\}catch', en)))

print('=== B3: restore names the date backup actually writes ===')
check('restoreFile reads d.exported', 'd.exported' in SRC)
check("backup still writes 'exported'", re.search(r'exported:\s*new Date\(\)\.toISOString\(\)', SRC) is not None)

print('=== B4: the feature guide does not miscount the tour ===')
check("no 'five step' claim survives", 'five step' not in SRC)

print('=== B5: the PiP document styles itself with literals ===')
pip = SRC[SRC.index('const PiP='):]
pip = pip[:pip.index('function netStatus')]
# only the requestWindow block runs in the bare document; pinnedChip lives in
# the main document where the variables exist, so scope the check to `show`.
show = pip[:pip.index('function pinnedChip')]
check('no var(--...) inside the PiP window markup', 'var(--' not in strip_comments(show),
      'custom properties resolve to nothing in a fresh document')

print('=== C1: no em dashes in user-visible copy (2026-08-30, Mason) ===')
# The em dash has become the tell people read as machine-written copy. Every
# prose instance was rewritten (comma, colon, parenthetical, or a full stop).
# The ONE sanctioned use is the standalone no-price placeholder '\u2014' in
# price cells, which is a table convention, not a sentence.
lit = SRC.count('\u2014')            # literal em dash characters in the page
ent = SRC.count('&mdash;')
esc = SRC.count("'\\u2014'")          # the quoted placeholder literal in JS
check('no literal em dash anywhere in the page', lit == 0, f'found {lit}')
check('no &mdash; entity anywhere', ent == 0, f'found {ent}')
check('the no-price placeholder survives as the sanctioned exception',
      esc == 2, f'found {esc} (expected exactly 2: priceTag and PiP)')

print()
print('ALL PASS' if not failed else f'{failed} FAILED')
sys.exit(1 if failed else 0)
