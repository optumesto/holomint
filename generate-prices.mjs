/*
 * generate-prices.mjs — Holomint price build step
 * --------------------------------------------------
 * Runs daily (locally, or via a scheduled job / GitHub Action), pulls current
 * sealed + graded prices from TCGcsv, and writes prices.json. The app loads that
 * file on launch (PriceEngine.fetchLive), so the UI stays fast, static, and offline-capable.
 *
 * This is where your PokemonPriceTracker.gs logic ports in — same idea (productId -> price),
 * just writing a JSON file instead of a spreadsheet. Node 18+ (built-in fetch).
 *
 *   node generate-prices.mjs
 *
 * TCGcsv reference (category 3 = Pokemon):
 *   Groups:   https://tcgcsv.com/tcgplayer/3/groups
 *   Products: https://tcgcsv.com/tcgplayer/3/{groupId}/products
 *   Prices:   https://tcgcsv.com/tcgplayer/3/{groupId}/prices
 */
import { writeFile } from 'node:fs/promises';

// Map each app catalog key -> the TCGplayer productId it should track.
// Fill these in from TCGcsv product listings (search the products endpoint by name).
const KEY_TO_PRODUCT_ID = {
  // 'es-bb':   0,   // Evolving Skies Booster Box
  // 'lo-bb':   0,   // Lost Origin Booster Box
  // 'moon':    0,   // Moonbreon PSA 10 (graded comps may come from a different source)
};

// Which TCGplayer groupIds to pull (the sets your products live in).
const GROUP_IDS = [/* e.g. 3118, 3170, ... */];

async function getPrices(groupId) {
  const res = await fetch(`https://tcgcsv.com/tcgplayer/3/${groupId}/prices`);
  if (!res.ok) throw new Error(`prices ${groupId}: ${res.status}`);
  const { results } = await res.json();
  const byId = {};
  for (const p of results) byId[p.productId] = p.marketPrice ?? p.midPrice ?? null;
  return byId;
}

async function main() {
  const idToPrice = {};
  for (const g of GROUP_IDS) Object.assign(idToPrice, await getPrices(g));

  const out = {};
  for (const [key, productId] of Object.entries(KEY_TO_PRODUCT_ID)) {
    const price = idToPrice[productId];
    if (price != null) out[key] = Math.round(price);
  }

  if (Object.keys(out).length === 0) {
    console.warn('No prices resolved — fill in KEY_TO_PRODUCT_ID and GROUP_IDS. Leaving prices.json untouched.');
    return;
  }
  await writeFile('prices.json', JSON.stringify(out, null, 2));
  console.log(`Wrote prices.json with ${Object.keys(out).length} items.`);
}

main().catch(err => { console.error(err); process.exit(1); });
