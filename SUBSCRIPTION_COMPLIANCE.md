# Holomint — Subscription Compliance (BUILD SPEC)

**This is the most important file in the compliance set.**

Auto-renewal liability is almost never about what your Terms page says. It is about **what the checkout flow discloses, how consent is captured, and how easy it is to cancel.** These are engineering requirements, not legal boilerplate. Enforcement actions (Amazon Prime, Uber One, Chegg, LA Fitness) have targeted *flows*, not documents.

*Not legal advice — verify against your target jurisdictions. But build to this bar.*

---

## 1. The current legal landscape (as of July 2026)

- The FTC's 2024 **"Click-to-Cancel"** Negative Option Rule was **vacated** by the Eighth Circuit in July 2025 (*Custom Communications, Inc. v. FTC*) on **procedural** grounds — the FTC skipped a required preliminary regulatory analysis. The court did **not** reject the FTC's substantive authority or the policy itself.
- **The rule being gone changes almost nothing in practice.** The FTC continues to enforce the same three principles case-by-case under **ROSCA** (Restore Online Shoppers' Confidence Act), which remains good law, and under **Section 5** of the FTC Act.
- The FTC issued an **ANPRM in March 2026** to revive the rule. Commentators expect any new rule to closely resemble the vacated one.
- **~30 states have their own automatic-renewal laws (ARLs)**, and several (California, New York, Massachusetts) are **stricter** than the vacated federal rule. You will have customers in these states.

**Design conclusion: build to the vacated rule's standard.** It is what ROSCA + the strictest state ARLs already require, and it is what the coming federal rule will most likely look like. Building to it now costs you nothing and future-proofs the flow.

---

## 2. ROSCA's three requirements → your three build tasks

| Legal requirement | What Holomint must do |
|---|---|
| **1. Clear and conspicuous disclosure of all material terms — BEFORE billing information is collected** | The "Go Pro" screen (§3) must state price, monthly recurrence, auto-renewal, and how to cancel — *before* the user reaches the payment form. |
| **2. Express informed consent to the recurring charge, before charging** | An **unchecked** consent checkbox tied specifically to the recurring terms (§4). No pre-ticked boxes. Keep the record. |
| **3. A simple mechanism to stop recurring charges** | A **"Manage Subscription / Cancel"** link inside Holomint that reaches cancellation **online, in the same medium, at least as easily as signing up** (§5). |

---

## 3. BUILD: pre-checkout disclosure block

Must appear on the "Go Pro" screen, **adjacent to the button that starts checkout** — not behind a link, not in a tooltip, not only in the Terms. Legible size, high contrast, no scroll required to see it.

**Paste-ready copy:**

> **Holomint Pro — $[X]/month**
> Billed **monthly** to your payment method. **Your subscription automatically renews every month at $[X] and you will be charged each month until you cancel.**
> **Cancel anytime** in Settings → Holomint Pro, or from the link in your receipt email. Cancelling stops future charges; your Pro access continues to the end of the month you've paid for.
> No partial refunds for unused time. See [Terms] and [Refund Policy].

**Rules:**
- The word **"automatically renews"** (or equivalent) must be present, not implied.
- Price + billing frequency + "until you cancel" + how to cancel must **all** appear here.
- Do **not** bury this in the Terms link only. Terms are the backup, not the disclosure.
- If you ever add a **free trial**, this section gets materially stricter (trial length, conversion date, price after conversion, cancellation deadline). **Do not add a free trial without revisiting this file.**

---

## 4. BUILD: express consent

- A checkbox, **unchecked by default**, immediately above the checkout button:
  > ☐ I understand this is a **$[X]/month subscription that automatically renews** until I cancel.
- The checkout button must be labeled unambiguously — **"Subscribe — $[X]/month"**, not "Continue" or "Get Pro."
- **Also capture assent to the Terms in the same affirmative step:**
  > ☐ I agree to the [Terms of Service], [Privacy Policy], and [Refund Policy].
  **This is load-bearing for your entire ToS**, not just billing. Terms accepted by *clickwrap* (an affirmative click, with the terms conspicuously presented/linked, and a record kept) are routinely enforced. Terms imposed by *browsewrap* ("by using this site you agree," link buried in a footer) are struck down constantly. Every protective clause you have — the liability cap, the not-financial-advice disclaimer, the no-scraping rule — depends on being able to prove the user actually agreed. **No assent record = the ToS may be worth nothing.**
- **Record the consent:** store timestamp + the exact terms version shown. If a chargeback or complaint ever comes, this record is your defense. Your payment processor (Polar / Lemon Squeezy) captures much of this at its hosted checkout — **verify what it actually records and retains**, and keep your own log of what your pre-checkout screen displayed.
- No dark patterns: no pre-selection, no misdirection, no obscuring the recurring nature.

---

## 5. BUILD: cancellation (the highest-risk item)

**The rule of thumb the FTC applies: cancellation must be at least as easy as sign-up, and available in the same medium.** You sign up online, in-app, in a few taps — therefore **cancellation must be online, in-app, in a few taps.**

### ✅ Polar solves this out of the box — but you still have to wire it

Polar's documentation states directly that jurisdictions such as California's Automatic Renewal Law require customers to cancel the same way they signed up, and that **their Customer Portal satisfies that requirement out of the box.** Specifically:
- **"Cancel at period end" is always available to the customer in the portal** — Polar calls this the portal's self-service guarantee. It cannot be disabled, which is exactly what you want.
- **Polar automatically includes a Customer Portal link in its transactional emails** — order confirmations, renewal notices, failed-payment alerts. That satisfies the "receipt must contain a cancellation mechanism" requirement without extra work.
- By default customers authenticate to the portal with a one-time emailed code. **You can instead generate a pre-authenticated link from Holomint** — do this, so "Manage Subscription" is one tap, not an email round-trip.

**Your remaining work:**
- A **"Manage Subscription"** entry in Settings → Holomint Pro, visible whenever a license is active, opening the Polar customer portal (ideally pre-authenticated).
- Cancellation must complete **online, without contacting a human**. Polar's portal does this. Do not add friction in front of it.
- **Do not build a custom cancel flow that bypasses the portal.** The portal is your compliance; a homegrown retention funnel in front of it is exactly what gets enforced against.
- **No retention maze.** A single, skippable "are you sure?" is acceptable. Multi-step surveys, forced discount offers you must decline repeatedly, or "pause" options pre-selected instead of cancel — these are exactly what enforcement actions have targeted.
- Cancellation must **actually stop the charges.** Test this end-to-end with a real subscription before launch. (Chegg was alleged to have kept charging people after they cancelled — that is the nightmare scenario, and it's a *bug*, not a policy failure.)
- Send a **cancellation confirmation email**.

---

## 6. BUILD: post-purchase and ongoing

- **Purchase acknowledgment email** containing: the terms of the subscription, the price and billing frequency, and **cancellation instructions + a direct cancel/manage link**. (Your processor likely sends a receipt — confirm it includes the cancellation mechanism; if not, send your own.)
- **Price-change notice.** Never raise the price on an existing subscriber without advance notice and a chance to cancel first.
- **Renewal reminders.** Some state ARLs require advance renewal notice in certain circumstances (longer terms, trial conversions). For a plain month-to-month subscription this is generally *not* required. Note that **Polar automatically sends renewal reminders only for yearly-or-longer cycles** (and before trials end) — monthly subscribers get an order confirmation each cycle instead, which serves the purpose. If you ever switch to annual billing, Polar's 7-day reminder covers you.
- **Records.** Retain consent records, subscription events, and cancellation requests.

---

## 7. Pre-launch test checklist

Run these against a **real** subscription (use a real card, refund yourself) before you take a single customer:

- [ ] The pre-checkout screen shows price + "automatically renews monthly" + how to cancel, **before** any payment field appears.
- [ ] The consent checkbox is **unchecked** on load and blocks checkout until ticked.
- [ ] The receipt email includes the cancellation link.
- [ ] "Manage Subscription" appears in Settings while Pro is active, and it opens the customer portal.
- [ ] I can **fully cancel online in under a minute, without talking to anyone**.
- [ ] After cancelling: **no further charge occurs** on the next billing date. (Verify with a real cycle if at all possible.)
- [ ] After cancelling: Pro access persists to the end of the paid period, then downgrades.
- [ ] After downgrade: **the user's local collection data is intact.**
- [ ] Privacy Policy + Terms + Refund Policy are linked from the checkout screen and the site footer.

---

## 8. The one that bites hardest

If you build only one thing from this file correctly, build **§5 — cancellation**. Every major enforcement action in this space has centered on making cancellation hard. It is also, conveniently, the cheapest item here: a link to your processor's customer portal.

**Making cancellation easy is not a business risk. Making it hard is a legal one.**
