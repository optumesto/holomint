# Holomint — Launch Compliance Checklist (INDEX)

**Start here.** Maps the compliance set and what's left.
*Not legal advice — product-accurate drafts for your review.*

**Decided:** Pro = **recurring monthly subscription** · Processor = **Polar** (merchant of record) · Analytics = **none** *(code-verified)*

## The document set
| File | What it is | Status |
|---|---|---|
| **`SUBSCRIPTION_COMPLIANCE.md`** | **Build spec for checkout + cancellation. The highest-value file — auto-renewal liability lives in the flow, not the docs.** | ✅ Drafted |
| `TERMS_OF_SERVICE.md` | Auto-renewal terms, not-financial-advice, non-affiliation, liability caps | ✅ Drafted |
| `PRIVACY_POLICY.md` | Matches the real architecture; sub-processors **corrected from a code scan** | ✅ Drafted |
| `REFUND_POLICY.md` | Standalone refund/cancellation policy (Polar will want one) | ✅ Drafted |
| `COMPLIANCE_MAINTENANCE.md` | Trigger table — what to update when the app changes | ✅ Drafted |

---

## 🔎 What the code scan found (fix these — they're cheap)
I scanned the deployed app rather than trusting assumptions. Results:

**✅ Analytics claim VERIFIED.** Zero trackers, zero analytics, zero external scripts. Your "privacy-first" positioning is real, not marketing.

**⚠️ But the app contacts 3 third parties I hadn't listed** (each receives users' IP addresses). Now disclosed in the Privacy Policy — but two are worth *eliminating* instead:

- [ ] **Self-host the fonts.** `fonts.googleapis.com` / `fonts.gstatic.com` send every visitor's IP to Google. This has been the subject of **actual GDPR litigation in Germany** over exactly this pattern. Fix: download Fraunces / Hanken Grotesk / IBM Plex Mono as woff2, serve from the repo, drop the Google `<link>`. **Removes a sub-processor entirely and loads faster.** ~20 min.
- [ ] **Self-host `tesseract.js`** (currently pulled from `cdn.jsdelivr.net` at scan time). Removes another third party *and* kills a supply-chain risk — right now a compromised CDN could serve arbitrary code into your app. At minimum add SRI. *(The scanner itself runs on-device — images never leave the phone. That's a genuine privacy selling point; the Privacy Policy now says so explicitly.)*
- [ ] **`api.pokemontcg.io`** receives **users' search terms** + IP. Legitimate and now disclosed — just know it's the one place user-typed content leaves the device.
- [ ] **Dead Lemon Squeezy reference** at index.html ~L481 — remove when wiring Polar.

---

## Launch blockers (before you take a single payment)
- [ ] **Kill the `HF-XXXX` license bypass.** Anyone can self-grant Pro right now. Non-negotiable before charging.
- [ ] **"Manage Subscription" → Polar customer portal**, in Settings, whenever Pro is active. *(Polar's portal satisfies the cancel-as-easily-as-you-signed-up rule out of the box — see `SUBSCRIPTION_COMPLIANCE.md` §5.)*
- [ ] Pre-checkout screen discloses price + "automatically renews monthly" + how to cancel, **before** any payment field
- [ ] Unchecked consent checkbox; button reads **"Subscribe — $X/month"**
- [ ] Privacy / Terms / Refunds linked from **checkout** and **footer**
- [ ] End-to-end tested with a real card (`SUBSCRIPTION_COMPLIANCE.md` §7)

## In-product (cheap, and where people actually read)
- [ ] **Disclaimer near price/flip figures:** *"Estimates only — not financial advice. Prices from third parties and may be inaccurate."* Your flip-margin hands people profit numbers — this line matters more than any ToS section.
- [ ] **Footer:** Privacy · Terms · Refunds · Contact + *"Not affiliated with Nintendo, The Pokémon Company, or TCGplayer."*
- [ ] **Cookie banner: not needed today** — functional local storage only, no tracking. Changes the day you add analytics.

---

## ⚠️ The standing risk that isn't a document
**Pokémon / TCGplayer IP — card images in a paid product.**
- Card **names** for identification: generally defensible (nominative use).
- Card **images** in a **commercial, recurring-revenue** product: the exposed piece. Non-affiliation disclaimers address **trademark** confusion; they do **not** cure **copyright** in images.
- Going free tool → paid monthly subscription **raises this**: the commercial use is now unambiguous and ongoing.
- The TCG-tooling ecosystem lives in this gray zone and is largely tolerated — **tolerated ≠ licensed.**
- **Options:** images free-tier only; lean on names/text in Pro; verify what TCGplayer's terms actually permit; or knowingly accept the risk.
- **This one's yours to weigh** — it's a risk-appetite judgment, not a drafting problem, and you're better equipped for it than I am.

---

## Handled / lower priority
- **Sales tax & VAT** — Polar handles as merchant of record. Nothing to build.
- **Optume Ventures LLC** — right liability posture. Confirm name/state on docs.
- **DMCA** — not needed (no user-generated content). Revisit if the trade board goes multi-user.
- **Accessibility (WCAG)** — worth a pass eventually, not a blocker.

---

## ❗ Still needed from you
1. **Price:** $[X]/month?
2. **Contact email:** support@holomint.app?
3. **LLC state of formation** = Pennsylvania? Venue county? Business address to list (or omit)?
4. **Effective date** to stamp.
5. **Arbitration + class-action waiver — in or out?** Left out pending your decision; real tradeoffs both ways.

Then: I finalize, render as styled HTML pages matching Holomint, and we wire Polar.
