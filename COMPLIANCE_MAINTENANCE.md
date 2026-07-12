# Holomint — Compliance Maintenance Protocol

**The problem this solves:** a privacy policy that describes what your app *used to do* is worse than none. An inaccurate policy is itself a deceptive practice (FTC Act §5) — you get punished for the *mismatch*, not just the gap. So compliance can't be a one-time launch task; it has to be **triggered by shipping**.

This file is the trigger. **Read the table below before every release.**

---

## 1. The rule

> **If a change touches (a) what data is collected or where it goes, (b) money, (c) a new third party, or (d) a new device permission — the compliance docs must be reviewed before that change ships.**

Everything else (UI tweaks, new calculators, catalog refreshes, bug fixes) needs **no** compliance action. Most releases will need nothing. That's the point — keep the trigger narrow so it actually gets followed.

---

## 2. Trigger table

| If you ship… | You must update / do… | Severity |
|---|---|---|
| **Analytics of any kind** (even privacy-friendly, even self-hosted) | Privacy Policy §5 + §6 sub-processor table. EU/UK users likely need a **consent mechanism** before non-essential storage. | 🔴 High |
| **Ads, or any affiliate/referral links** | Privacy Policy (ad tech + tracking). **FTC endorsement rules require clear disclosure of affiliate relationships.** ToS. | 🔴 High |
| **User accounts, logins, or email collection** | Privacy Policy §2/§3 (you now hold personal data), add data-rights request process, security section, retention schedule. | 🔴 High |
| **Server-side storage of user collections** (i.e., cloud sync) | **Major Privacy Policy rewrite** — the entire "your data stays on your device" claim breaks. This is the single biggest claim in your policy; do not silently invalidate it. | 🔴 Critical |
| **Price change, billing period change, or new paid tier** | ToS §6, Refund Policy, checkout disclosures. **Advance notice to existing subscribers before it applies to them.** | 🔴 High |
| **A free trial** | `SUBSCRIPTION_COMPLIANCE.md` §3 — trial rules are materially stricter (conversion date, price after trial, cancellation deadline). State ARLs add renewal-reminder duties. **Do not ship a trial without re-reading that file.** | 🔴 High |
| **A new third-party data source or API** (e.g., an image-recognition API for the scanner) | Privacy Policy §6 sub-processor table. If user photos/screens are sent to it → **also disclose what is transmitted and retained.** | 🟠 Medium |
| **The card scanner sending images off-device** | Privacy Policy — you are now transmitting user-captured images to a third party. Must be disclosed explicitly. Today's browser-OCR scanner is on-device; an API scanner is **not**. | 🔴 High |
| **The Android overlay + screen capture** (`SYSTEM_ALERT_WINDOW`, `MediaProjection`) | Privacy Policy (what the app can see and whether anything leaves the device); **Play Store policy scrutiny on these permissions is high** — expect to justify them and to complete Play's **Data safety** form accurately. | 🔴 High |
| **Native app / Play Store release** | Play **Data safety** declaration, Play billing/subscription policy, store listing accuracy, target-API requirements. Store terms must match your ToS. | 🔴 High |
| **User-generated content** (comments, shared lists, trade board with other users) | DMCA agent registration + takedown process, content/moderation policy, ToS content license section. | 🟠 Medium |
| **Expanding marketing to EU/UK customers in earnest** | GDPR specifics: consent mechanism, DSAR process, possible representative requirement. | 🟠 Medium |
| **New card images / expanded image use in the paid tier** | **IP risk review** — see `COMPLIANCE_CHECKLIST.md`. Commercial image use is the standing open risk. | 🟠 Medium |
| **Email marketing / newsletters** | CAN-SPAM: working unsubscribe, physical mailing address in every email, no deceptive subject lines. | 🟠 Medium |
| **You cross ~a few hundred paying subscribers** (or before a big paid push) | **Revisit the arbitration / class-action-waiver decision** (deliberately omitted at launch — see below). Class-action exposure only becomes real once there are enough subscribers to interest a plaintiffs' firm. | 🟠 Medium |
| **Anything else** (UI, calculators, catalog refresh, bug fixes, feed tweaks) | **Nothing.** Ship it. | ⚪ None |

### Deferred decision on record: arbitration / class-action waiver — **OMITTED at launch (deliberate)**
Reasoning, so future-you doesn't re-litigate it from scratch:
- The class-action waiver is the real objective; it only reliably survives when carried by an arbitration clause (FAA preemption — *Concepcion*, *Italian Colors*).
- But mandatory consumer arbitration **invites mass arbitration**: under AAA/JAMS consumer rules the business pays nearly all the per-case fees, so a few hundred coordinated demands can be an extinction event for a solo LLC — regardless of merit. Amazon (2021) and Valve (2024) *removed* their consumer arbitration clauses for exactly this reason.
- It also does **nothing** against the two most likely threats: a **state AG / FTC auto-renewal action** (regulators aren't parties to the ToS) and an **IP claim from a rights-holder** (not a customer).
- At launch scale, class-action risk ≈ 0, so the clause would trade a nonexistent risk for a real one.
- **Revisit when subscriber count makes a class action economically attractive to a plaintiffs' firm.** If added later, it must include: informal-resolution precondition, small-claims carve-out, 30-day opt-out, IP/injunctive carve-out, and a **mass-arbitration batching protocol** — and should be lawyer-drafted. Adding it later requires notice + assent from existing subscribers.

---

## 3. Where the docs live (this is what makes it stick)

Put the policies **in the repo, next to the code**, and publish them from there:

```
holomint/
  index.html
  sw.js
  privacy.html      ← rendered from PRIVACY_POLICY.md
  terms.html        ← rendered from TERMS_OF_SERVICE.md
  refunds.html      ← rendered from REFUND_POLICY.md
  compliance/       ← the source .md files + this protocol
```

Because they're version-controlled alongside the app, a compliance change is a **commit in the same PR as the feature that triggered it**. That's the only mechanism that reliably keeps them in sync. Policies that live in a Notion page or a website builder always rot.

**Footer requirement:** every page of Holomint links **Privacy · Terms · Refunds · Contact**, plus the non-affiliation line.

---

## 4. Encode it as a Claude Code rule

Add to Holomint's `CLAUDE.md` so the trigger fires automatically during development:

```markdown
## Compliance gate (hard constraint)
Before completing any change that touches:
  - data collection, storage location, or transmission off-device
  - payments, pricing, billing period, tiers, or trials
  - a new third-party service, API, or data source
  - a new device permission (camera, screen capture, overlay, storage)
STOP and report: "⚠️ COMPLIANCE TRIGGER — see compliance/COMPLIANCE_MAINTENANCE.md"
Do not silently ship it. The privacy policy makes specific factual claims
(local-only storage, no analytics, no tracking). Breaking one of those claims
without updating the policy is a deceptive practice, not just a docs gap.
```

## 5. Versioning discipline

- Every doc has **Version + Effective date + change log** at the bottom.
- **Material change for paid subscribers → advance notice** (email + in-app) *before* it takes effect, with a chance to cancel. Non-material → update the date and post.
- Keep **dated archives** of superseded versions. If a dispute ever arises about what a customer agreed to, you need the version that was live on their signup date. Git gives you this for free — another reason the docs live in the repo.

## 6. Recurring review

- **Every release:** scan the trigger table (30 seconds).
- **Every 6 months:** re-read the docs against what the app actually does now. Drift is silent and cumulative.
- **Watch for:** the FTC's revived negative-option rule (ANPRM issued March 2026 — a proposed rule and then a final rule will follow, and it is expected to resemble the vacated Click-to-Cancel rule). When it lands, re-check `SUBSCRIPTION_COMPLIANCE.md`. Building to that standard now means you should already be compliant.
