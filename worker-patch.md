# holomint-feed — patch for the show

Two changes. Both are the same idea the Worker already applies to licences,
carried over to the two places it was missing.

---

## 1. `/api/pricing` needs the tri-state that `licenseState` already has

**Why.** `licenseState()` is careful and correct: a 5xx, a 429, a 401/403 on
*our own* API key, or a network error all return `'unknown'`, never `'no'`,
with the comment *"Never let a server credential problem look like an invalid
licence."*

`/api/pricing` has no such distinction. Every failure path returns
`{ configured: false }`:

```js
if (!env.POLAR_API_KEY || !env.POLAR_PRODUCT_ID) return json({ configured: false });
...
if (!r.ok) return json({ configured: false });
...
} catch (e) { return json({ configured: false }); }
```

The app renders `configured:false` as **"Subscriptions are not open yet."** So a
Polar outage, a rotated key, or a cold-start timeout tells a buyer standing at
your table that the product is not for sale. They do not retry — nothing on
screen suggests retrying would help — and the only trace is a sale that quietly
does not happen.

The app already understands the fixed shape: `{configured:false,
unreachable:true}` renders *"Could not reach the store — this is usually the
network, not you. Pro is still on sale"* plus a **Try again** button.

**Replace the whole `/api/pricing` block with:**

```js
    if (p === '/api/pricing' && req.method === 'GET') {
      const cached = await env.DROPS.get('pricing', 'json');
      if (cached && Date.now() - cached.at < 120000) return json(cached.data);   // 2 min: the founder seat counter must not lie

      // Deliberately not selling: an honest, final answer.
      if (!env.POLAR_API_KEY || !env.POLAR_PRODUCT_ID)
        return json({ configured: false });

      // Could not ask. Same reasoning as licenseState's 'unknown': a problem on
      // our side must never render as "this product is not for sale". The app
      // shows a retry for this shape instead of the shop-is-shut copy.
      const unreachable = () => json({ configured: false, unreachable: true });

      try {
        const base = env.POLAR_SANDBOX === '1' ? 'https://sandbox-api.polar.sh' : 'https://api.polar.sh';
        const r = await fetch(`${base}/v1/products/${env.POLAR_PRODUCT_ID}`, {
          headers: { 'Authorization': `Bearer ${env.POLAR_API_KEY}` },
        });
        // 5xx/429 is Polar's problem; 401/403 is OUR credential, not the
        // shop being closed. Both are "ask again later", never "not for sale".
        if (r.status >= 500 || r.status === 429 || r.status === 401 || r.status === 403)
          return unreachable();
        if (!r.ok) return unreachable();
        const prod = await r.json();
        const pr = (prod.prices || []).find(x => !x.is_archived) || (prod.prices || [])[0];
        // A product with no price is a misconfiguration we cannot price from,
        // and charging nothing is worse than saying nothing.
        if (!pr) return unreachable();

        const list = (pr.price_amount || 0) / 100;
        const data = {
          configured: true,
          name: prod.name || 'Holomint Pro',
          amount: list,
          currency: (pr.price_currency || 'usd').toUpperCase(),
          interval: prod.recurring_interval || pr.recurring_interval || 'month',
          checkout: env.POLAR_CHECKOUT_URL || null,
          portal: env.POLAR_PORTAL_URL || null,
          founder: null,
        };

        // Founder tier: a forever discount with a hard redemption cap. Polar
        // enforces the cap, so it cannot be oversold. redemptions_count drives a
        // live counter, because scarcity only converts when it is real.
        if (env.POLAR_DISCOUNT_ID && env.POLAR_FOUNDER_URL) {
          try {
            const dr = await fetch(`${base}/v1/discounts/${env.POLAR_DISCOUNT_ID}`, {
              headers: { 'Authorization': `Bearer ${env.POLAR_API_KEY}` },
            });
            if (dr.ok) {
              const d = await dr.json();
              const total = d.max_redemptions || 0;
              const used  = d.redemptions_count || 0;
              const left  = Math.max(0, total - used);
              const off   = d.type === 'fixed'
                ? (d.amount || 0) / 100
                : list * ((d.basis_points || 0) / 10000);
              if (left > 0) {
                data.founder = {
                  amount: Math.max(0, +(list - off).toFixed(2)),
                  left, total,
                  checkout: env.POLAR_FOUNDER_URL,
                };
              }
            }
          } catch (e) { /* no founder tier is not an error */ }
        }
        // Only a real answer is cached. An unreachable one must never be served
        // for two minutes to everyone who asks after it.
        await env.DROPS.put('pricing', JSON.stringify({ at: Date.now(), data }));
        return json(data);
      } catch (e) {
        return unreachable();
      }
    }
```

Note the checkout URL still comes from `POLAR_CHECKOUT_URL`, so if that env var
is ever unset the app gets `checkout:null` and `offer()` returns null — which
renders as "not open yet" even though everything else is healthy. Worth an eye
on the health check below.

---

## 2. `/api/health` should say whether the shop can actually sell

**Why.** The health endpoint currently reports ingest freshness only. The
question that matters on Sunday morning is *"can someone give me money right
now"*, and nothing answers it. This exposes **presence of config, never
values** — safe to leave public.

**Add inside the `/api/health` handler, before the final `return json({...})`:**

```js
      // Can the shop actually take money right now? Presence only, never values.
      // POLAR_ORG_ID gates licence validation and POLAR_PRODUCT_ID gates pricing;
      // they are different variables, so one can be set without the other and the
      // failure is silent and asymmetric -- prices show but no key ever validates,
      // or vice versa. Both are checked because either alone is a broken shop.
      const sell = {
        polarKey:    !!env.POLAR_API_KEY,
        polarOrg:    !!env.POLAR_ORG_ID,        // licence validation
        polarProduct:!!env.POLAR_PRODUCT_ID,    // pricing
        checkoutUrl: !!env.POLAR_CHECKOUT_URL,  // without this there is no buy button
        founderUrl:  !!env.POLAR_FOUNDER_URL,
        portalUrl:   !!env.POLAR_PORTAL_URL,
        vapid:       !!(env.VAPID_PUBLIC_KEY && env.VAPID_PRIVATE_KEY),
        ipSalt:      !!env.IP_SALT,
        sandbox:     env.POLAR_SANDBOX === '1',
      };
      sell.canSell = sell.polarKey && sell.polarProduct && sell.checkoutUrl;
      sell.canActivate = sell.polarKey && sell.polarOrg;
```

then include `sell` in the response object.

**`sandbox` is on that list deliberately.** `POLAR_SANDBOX === '1'` in
production means every checkout is a test purchase that takes no money, and
nothing else in the system would tell you.

---

## The question I cannot answer from the code

**Is there a frequent cron trigger in `wrangler.toml`, not just the daily one?**

`scheduled()` returns early for `'0 9 * * *'`. Every *other* invocation runs the
free-tier sweep — the thing that finds drops crossing the 10-minute line and
pushes them to free users:

```js
if (evt.cron === '0 9 * * *') { ...catalog refresh...; return; }
// otherwise: free unlock sweep
```

If `wrangler.toml` only declares `0 9 * * *`, then **free users receive no
notifications at all, ever.** The whole free tier is delayed alerts, so with no
sweep there is nothing to be late — there is just nothing. Free users would
experience an app that never notifies, and never convert.

The sweep also matches on `age > delay && age < delay + 30min`, so the trigger
needs to fire well inside that 30-minute window. Once a minute is what the
comment assumes.

Please paste `wrangler.toml` (bindings and triggers; no secret values needed).
If the frequent trigger is missing, that is a bigger conversion problem than
anything in the app, and it is a one-line fix.
