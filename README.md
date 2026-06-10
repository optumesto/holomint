# Holomint

Sealed & graded Pokémon **flip and portfolio** tool. Value a pile at the table, see real net-of-fees margin, balance trades, run grading math with live card lookup, and track holdings as a P&L — not a binder.

Installable PWA (offline-capable). Free tier + Pro tier (license key).

## Files

| File | Purpose |
|------|---------|
| `index.html` | The whole app — Trade Block, Portfolio, Slab Math |
| `manifest.json`, `sw.js`, `icon-*.png` | PWA shell (network-first for JSON data, cache-first for app shell) |
| `products.json` | Sealed/graded catalog (id, name, type, print status) |
| `prices.json` | Current prices, keyed by catalog id |
| `generate-prices.mjs` | Build step: pulls TCGcsv → writes prices.json |
| `.github/workflows/prices.yml` | GitHub Action: runs the build step daily, commits fresh prices |
| `market/` | Public SEO product pages (acquisition layer + affiliate links) |

## Architecture

**Spine** (all surfaces ride on these): generic holding model (`type` = sealed/graded), price engine (loads products.json + prices.json, seeded fallback), fee calculator (editable channel profiles; eBay cards FVF 13.6% verified 2026).

**Data layers:**
1. *Sealed prices* — TCGcsv via daily build step (free). **Required before launch.**
2. *Raw card lookup* — pokemontcg.io, live client-side (free). Already wired in Slab Math.
3. *Graded values / pop / recent sales* — `SlabData.gradeData` adapter. Needs paid source (e.g. PriceCharting API) + PSA Public API (free 100 calls/day, no browser CORS → route via build step or proxy). **Post-launch, funded by revenue; ships as the Pro data feed.**

**Grading dataset** (Slab Math): fees, business-day turnarounds, declared-value caps, and paused-tier flags for PSA, CGC, Beckett, TAG, SGC — sourced June 2026. Industry reprices often (PSA changed twice in 5 months); refresh quarterly. Beckett mid-tiers and CGC/SGC caps are the least-certain figures. TAG = no value upcharges (encoded as unlimited caps).

## Tiers

**Free:** Trade Block (buy rates, per-item overrides, store-credit bump, trades w/ cash offsets, manual entry + hotlist, receipts, Send to Desk), Portfolio (P&L, realized/unrealized, sell/return flow, allocation, basic CSV), Slab Math (full calculator, live lookup, upcharge model), backup/restore.

**Pro (license key):** Deal log, tax-year P&L, full CSV (holdings+sales+deals), FIFO/LIFO lot accounting. *Planned:* graded data auto-fill (values/pop/sales), price + OOP alerts, retail drop alerts (notification-only — never auto-cart).

**Pricing (decision pending):** candidate stack = $4.99/mo + $39/yr founder rate + capped one-time Founder Lifetime (~$79, first 25–50), price rises when the graded data feed ships; founders grandfathered.

## Payments & app stores (critical design rule)

Sold via Lemon Squeezy (merchant of record) on the web. **Store builds (Play/App Store) must contain no purchase buttons or external checkout links** — key entry only — to comply with store billing rules (15–30% cut otherwise). The license-key gate is the cross-platform unlock everywhere.

`Premium.validate()` in index.html is the Lemon Squeezy drop-in: POST `/v1/licenses/validate`, then verify `store_id` + `product_id` match ours so foreign LS keys don't unlock Pro.

## Roadmap

- **Phase 3 — payments:** LS store + product(s) w/ license keys; wire real validation. Needs: store ID, variant ID(s), checkout URL.
- **Phase 4 — launch package:** real catalog + prices via build step, market hub + more SEO pages, affiliate links (eBay Partner Network, TCGplayer), deploy to GitHub Pages, domain.
- **Phase 5 — stores:** Google Play via PWABuilder/TWA ($25 one-time, needs live HTTPS + site verification). Apple via Capacitor wrap ($99/yr, needs Mac or cloud build; expect 4.2 "not just a website" scrutiny — add native touches). Order: web first, Play after first revenue, iOS after Play proves demand.
- **Phase 6 — Pro data feed:** PriceCharting API + PSA API into the build step → Slab Math auto-fill + alerts; founder price rise event.

## Run locally

Static — open `index.html`, or `python3 -m http.server 8080`. Service worker + install require HTTPS (GitHub Pages).

---
*Independent tool. Not affiliated with The Pokémon Company, Nintendo, eBay, TCGplayer, PSA, CGC, Beckett, TAG, or SGC.*
