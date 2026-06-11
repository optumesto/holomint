/*
 * generate-prices.mjs — Holomint auto-catalog build step
 * Pulls the ENTIRE Pokémon sealed-product catalog + prices from TCGcsv
 * (community mirror of TCGplayer) and writes products.json + prices.json.
 * Runs daily via .github/workflows/prices.yml. Node 18+.
 */
import { writeFile } from 'node:fs/promises';

const CAT = 3; // Pokémon
const BASE = `https://tcgcsv.com/tcgplayer/${CAT}`;

// What counts as "sealed" — name patterns (case-insensitive)
const SEALED = /(booster box|booster pack|sleeved booster|elite trainer box|\betb\b|booster bundle|build & battle|build and battle|premium collection|ultra.?premium|collection box|special collection|pencil case|mini tin|\btin\b|booster display|sleeved booster case|booster case|box set|poke ?ball tin|premier deck|league battle deck|battle deck bundle)/i;
// Exclusions that sneak past the patterns
const EXCLUDE = /(single|\bcard\b only|code card|empty|damaged|opened|japanese)/i;

const OOP_MONTHS = 24; // sets older than this flag out-of-print (heuristic — override per product if wrong)

const HEADERS = {
  // TCGcsv fronts with Cloudflare; identify ourselves like a normal client
  'User-Agent': 'Holomint/1.0 (+https://holomint.app; sealed price tracker)',
  'Accept': 'application/json'
};
async function getJSON(url, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: HEADERS });
      if (r.ok) {
        const d = await r.json();
        return d.results ?? d;            // TCGcsv wraps in {results}; tolerate raw arrays
      }
      console.warn(`HTTP ${r.status} on ${url} (try ${i + 1}/${tries})`);
    } catch (e) {
      console.warn(`fetch error on ${url} (try ${i + 1}/${tries}):`, e.message || e);
    }
    await new Promise(res => setTimeout(res, 1000 * (i + 1)));
  }
  return null;
}

const SINGLE_MIN = 5; // chase singles only — cards at/above this market price

function isSealed(p) {
  if (!p.name || EXCLUDE.test(p.name)) return false;
  return SEALED.test(p.name);
}
function isChaseSingle(p, price) {
  if (!p.name || EXCLUDE.test(p.name)) return false;
  if (price == null || price < SINGLE_MIN) return false;
  return (p.extendedData || []).some(d => /^number$/i.test(d.name || ''));
}

async function main() {
  const groups = await getJSON(`${BASE}/groups`);
  if (!groups) { console.error('Could not fetch groups — aborting, files untouched.'); process.exit(1); }

  const products = [];
  const prices = {};
  const now = Date.now();

  for (const g of groups) {
    const [prods, priceRows] = await Promise.all([
      getJSON(`${BASE}/${g.groupId}/products`),
      getJSON(`${BASE}/${g.groupId}/prices`)
    ]);
    if (!prods || !priceRows) continue;

    const priceById = {};
    for (const row of priceRows) {
      const v = row.marketPrice ?? row.midPrice ?? null;
      if (v != null) priceById[row.productId] = v;
    }

    const ageMonths = g.publishedOn ? (now - new Date(g.publishedOn).getTime()) / (1000 * 60 * 60 * 24 * 30.44) : 0;
    const status = ageMonths > OOP_MONTHS ? 'oop' : 'in-print';

    for (const p of prods) {
      const price = priceById[p.productId];
      if (price == null || price <= 0) continue;
      let type = null;
      if (isSealed(p)) type = 'sealed';
      else if (isChaseSingle(p, price)) type = 'single';
      if (!type) continue;
      const id = String(p.productId);
      products.push({ id, type, name: p.name, status: type === 'single' ? 'raw' : status, set: g.name });
      prices[id] = Math.round(price * 100) / 100;
    }
  }

  if (products.length < 50) {
    console.error(`Only ${products.length} sealed products found — looks wrong; leaving existing files untouched.`);
    process.exit(1);
  }

  // newest sets first so search feels current
  products.sort((a, b) => (b.id.length - a.id.length) || b.id.localeCompare(a.id));

  await writeFile('products.json', JSON.stringify(products));
  await writeFile('prices.json', JSON.stringify(prices));
  console.log(`Wrote ${products.length} sealed products across ${groups.length} sets.`);
}

main().catch(e => { console.error(e); process.exit(1); });
