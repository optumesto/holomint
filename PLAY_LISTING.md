# Holomint on Google Play — everything prepared, and what only you can do

Written 2026-08-29. Everything in `play/` and the files listed below are ready
to upload. The steps that need your Google account, your signing key, or your
money are in the last section.

---

## 0. Read this before spending anything

**The payments question decides whether this is worth doing at all.**

Holomint sells Pro through Polar, from a sheet inside the app. Play's Payments
policy governs that, and the rules changed this year:

- Since **30 June 2026**, Google permits external payment links in the US, UK
  and EU rather than requiring Google Play Billing.
- It is not free. External content links carry **10% on auto-renewing
  subscriptions** (first $1M of annual earnings), plus a **fixed $2.85 per app
  download** for installs completed within 24 hours of following the link.
- **From 1 October 2026** you must be enrolled in the external-links program and
  report transactions and downloads.

So there are three routes:

| route | what it costs | work |
|---|---|---|
| **External links (Polar stays)** | 10% of subs + $2.85/attributed install, enrol before 1 Oct | none in the app |
| **Play Billing via Digital Goods API** | 15% under $1M | real work — TWA + Digital Goods + a second licence path in the Worker |
| **No purchase inside the Android app** | nothing | hide the Pro sheet on Android; users subscribe on the web |

At $9.99/month the external-links route costs about **$1/month per subscriber**
plus the per-install fee. With zero subscribers today, the third route is also
perfectly reasonable for a first listing — ship it, see whether Android installs
happen at all, and add billing when there is something to bill.

**Verify the current terms yourself before enrolling.** This area moved twice in
2026 and I am reading summaries, not your Play Console.

One thing that is *not* a risk: policy 4.3 (minimum functionality) rejects raw
WebView wrappers, but a TWA over a real PWA is the compliant path, and Holomint
is a real PWA — offline shell, camera scanner, push, installable.

---

## 1. What is already done and committed

| file | what it is |
|---|---|
| `manifest.json` | `scope` and `start_url` set to `/` (Bubblewrap needs both) |
| `.well-known/assetlinks.json` | Digital Asset Links, with two placeholder fingerprints |
| `set_assetlinks.py` | fills the real fingerprints in, and `--check` verifies the live file |
| `twa-manifest.json` | Bubblewrap config, package `app.holomint.twa` |
| `play/01-portfolio.png` … `04-alerts.png` | four 1080x1920 screenshots, ratio 1.778 |
| `play/feature-graphic.png` | 1024x500, required by Play |
| `icon-512.png` | already 512x512 and genuinely maskable-safe (checked: 0% of ink outside the safe circle) |

**The old screenshots would have been rejected.** `screenshot-trade.png` and
`screenshot-portfolio.png` are 780x1688 — ratio 2.164, over Play's 2:1 cap. They
are fine for the PWA install prompt and are still referenced by `manifest.json`;
the new `play/` set is for the listing only.

---

## 2. Store listing copy — paste as-is

**App name** (max 30)

```
Holomint
```

**Short description** (max 80)

```
Pokemon restock alerts with the flip margin already worked out.
```

**Full description** (max 4000)

```
Holomint watches Pokemon TCG restocks and tells you what the flip is actually
worth — after the fees, in the channel you sell in.

Most alert apps send you a link. Holomint sends the link with the maths already
done: market price, your selling fees, and what you would actually keep.

WHAT IT DOES

• Live restock feed — Pokemon Center, Target, Walmart, Best Buy and more,
  matched to the sealed product and priced against retail.
• Flip margin on every drop, net of eBay, TCGplayer, Whatnot or cash fees.
• Scan a card with the camera, or a whole lot at once, and get a price.
• Portfolio tracking with cost basis, market value and realized gains.
• Slab Math — whether a card is worth paying to grade, given the fee, the
  graded-versus-raw spread and the odds.
• Release calendar, so you know what is coming before it drops.
• Japanese products included — roughly half the catalogue.

FREE AND PRO

Everything above works free. Free alerts arrive ten minutes after Pro.

Holomint Pro removes that delay and adds: watch any product you name, CSV
import and export, realized P&L by tax year, a log of every deal you caught,
and FIFO or LIFO lot accounting.

HONEST ABOUT WHAT IT IS NOT

Every price and margin in Holomint is an estimate for information only. It is
not financial advice, and collectible prices move fast. Restock information can
be sold out or wrong by the time you see it. You decide what to buy.

Holomint is an independent tool. It is not affiliated with, endorsed by or
sponsored by Nintendo, The Pokemon Company, Game Freak, Creatures Inc.,
TCGplayer, eBay or Whatnot. All card names, images and trademarks belong to
their respective owners.
```

**Category:** Shopping · **Tags:** collectibles, trading cards, price tracker
**Contact email:** mmmilliard@optumeventures.com
**Privacy policy URL:** `https://holomint.app/privacy.html`

---

## 3. Data Safety form — answers drawn from the live privacy policy

Play requires this to match what the app actually does. These follow
`privacy.html`; if you change the policy, change this too.

**Does your app collect or share any of the required user data types?** → **Yes**

| question | answer | why |
|---|---|---|
| Personal info (name, email, address) | **No** | no account, no login |
| Financial info | **No** | Polar is merchant of record; the app never sees a card |
| Location | **No** | never requested |
| Photos | **No** | the camera scans on-device; no image leaves the phone or is stored |
| Files and docs | **No** | CSV import is read in the browser only |
| App activity | **No** | only an anonymous aggregate count of whether alerts lead to purchases, not tied to a user |
| **Device or other IDs** | **YES** | a random per-installation id stored with the licence key, and a push subscription endpoint |

For **Device or other IDs**:
- Collected: **Yes** · Shared: **No**
- Purposes: **App functionality** and **Fraud prevention and security**
  (it enforces the three-device limit)
- Required or optional: **Optional** — only if you turn on alerts or buy Pro
- Processed ephemerally: **No**
- Users can request deletion: **Yes** — Settings → Delete my data

**Data is encrypted in transit:** Yes.
**You provide a way to request deletion:** Yes.

---

## 4. Content rating questionnaire

Answer honestly and it lands at **Everyone** / PEGI 3:
no violence, no sexual content, no profanity, no gambling, no user-generated
content, no user-to-user communication. The app does contain **digital
purchases** — say so.

Note Holomint's own Terms require you to be 18 to buy Pro, and alerts are
gated at 13 because they register a device. That is stricter than the Play
rating; there is no conflict.

---

## 5. What only you can do

See the email. Short version: Google Play developer account ($25 once), JDK +
Bubblewrap, generate a signing keystore, run the build, put the two SHA-256
fingerprints into `assetlinks.json` with `set_assetlinks.py`, push, upload the
AAB, paste the copy above.

**Back up the keystore somewhere you will still have it in five years.** Lose it
and you cannot ship an update to the same listing, ever.
