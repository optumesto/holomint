# Release checklist — branch `defer-history-load`

Written 2026-08-27 for the card show on **Sunday 30 August**. Run this when
you are back at the machine. Nothing on this branch is live yet.

## Before you push

- [ ] **Pull the branch up.** 15 commits, none pushed. `gh` is not authenticated
      on this machine (`gh auth login`), so the push has to be yours.
- [ ] **Run all six suites.** They must all print PASS:
      ```
      python3 test_money_path.py      # 21 checks — the subscribe path
      python3 test_ui_shell.py        # 47 — overlays, scroll lock, focus
      python3 test_tap_targets.py     # 27 — 44px targets
      python3 test_cardfind.py        # 30 — card detection accuracy
      python3 test_loader.py          # 12
      python3 test_install_offer.py   # 18
      ```
- [ ] **Confirm `sw.js` cache version is ahead of live.** It is now
      `holomint-v1.25`. The shell is cache-first, so **without a bump every
      already-installed user keeps the old `index.html` and sees none of this.**
      This is the single easiest item to forget and the one that silently
      undoes the whole release.
- [ ] **Visual check:** `python3 shots.py capture .shots/rel` then
      `python3 shots.py compare .shots/before .shots/rel`. Pages are expected to
      be TALLER (44px controls): settings ~+118px, others +26–61px. Anything
      else is worth a look.

## After you push, on a real phone

The suites cover a headless Chromium at 390px. These are the things only a real
device tells you.

- [ ] Open holomint.app **in Safari on an iPhone**, not just Chrome. Confirm the
      header clears the notch and the bottom nav clears the home indicator —
      `viewport-fit=cover` shipped earlier and the safe-area rules are live now.
- [ ] **Hard-refresh an already-installed copy** and confirm you get the new
      build (this is what the cache bump is for). If you have a device with the
      PWA installed from before, use that one.
- [ ] **Tap PRO.** Confirm a price appears, both consent boxes are easy to tick
      with a thumb, and Subscribe stays dead until both are ticked.
- [ ] **Turn wifi off, tap PRO.** You should now see *"Could not reach the
      store… Pro is still on sale"* with a **Try again**, NOT "Subscriptions are
      not open yet". Turn wifi back on and hit Try again.
- [ ] **Buy it.** Use a real card on a second account, then confirm Pro actually
      activates. See the worker section below — this is the one failure that
      cannot be tested from the app repo.

## Not in this release

- `cardfind.js` is committed but **referenced by nothing** — not `index.html`,
  not the `sw.js` SHELL list. It is inert and ships as a dead file. That is
  deliberate: the detector is validated against synthetic fixtures only.
- When it IS wired in, it **must** be added to `SHELL` in `sw.js` or the lot
  scanner breaks for installed users. Note `tesseract.min.js` is also absent
  from `SHELL` — worth checking whether the current scanner works offline at all.

## The worker (`holomint-feed`) — untested from here

The free/paid boundary is enforced in the Worker, not the app, so none of it is
covered by any suite in this repo:

- the **2 free notifications per day** cap
- the **10-minute delay** on free alerts
- **license validation** — whether a paid key actually flips Pro on

That last one is the worst failure available on Sunday: someone pays you in
person, and Pro does not turn on. Worse than any scanner bug, because you have
taken their money in front of other people. Test it with a real purchase before
the show, or have your own license key ready to demonstrate Pro directly.
