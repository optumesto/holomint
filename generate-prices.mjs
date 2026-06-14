/*
 * generate-prices.mjs — Holomint catalog build step
 * Pulls the FULL Pokémon catalog (English + Japanese) from TCGcsv:
 * every priced product — sealed, singles, all price tiers, both languages.
 * Writes products.json + prices.json. Runs daily via GitHub Actions. Node 18+.
 */
import { writeFile } from 'node:fs/promises';

const HEADERS = {
  'User-Agent': 'Holomint/1.0 (+https://holomint.app; price tracker)',
  'Accept': 'application/json'
};

async function getJSON(url, tries = 3) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: HEADERS });
      if (r.ok) { const d = await r.json(); return d.results ?? d; }
      console.warn(`HTTP ${r.status} on ${url} (try ${i + 1}/${tries})`);
    } catch (e) { console.warn(`fetch error ${url}:`, e.message || e); }
    await new Promise(res => setTimeout(res, 1000 * (i + 1)));
  }
  return null;
}

// Identify the Pokémon categories (English + Japan) by name, so we don't hardcode IDs
async function pokemonCategories() {
  const cats = await getJSON('https://tcgcsv.com/tcgplayer/categories');
  if (!cats) return [{ id: 3, lang: 'EN' }]; // fallback: English is well-known id 3
  const out = [];
  for (const c of cats) {
    const name = (c.name || c.displayName || '').toLowerCase();
    if (name === 'pokemon') out.push({ id: c.categoryId, lang: 'EN' });
    else if (name.includes('pokemon') && name.includes('japan')) out.push({ id: c.categoryId, lang: 'JP' });
  }
  return out.length ? out : [{ id: 3, lang: 'EN' }];
}

// Sealed detection (everything else priced is a card/single we keep)
const SEALED = /(booster box|booster pack|sleeved booster|elite trainer box|\betb\b|booster bundle|build & battle|build and battle|premium collection|ultra.?premium|collection box|special collection|mini tin|\btin\b|booster display|booster case|box set|poke ?ball tin|premier deck|league battle deck|battle deck|starter set|gift box|surprise box|holiday calendar|advent calendar)/i;
const EXCLUDE = /(code card|online code|empty|opened|damaged|proxy|playtest|lot of|bulk lot|repack|custom)/i;
const NONCARD = /(playmat|sleeve|deck box|binder|portfolio|^coin$| coin$|pin\b|figure|plush|dice|damage counter|marker|album|toploader|booster case|display case)/i;

const OOP_MONTHS = 24;

function classify(p) {
  const name = p.name || '';
  if (!name || EXCLUDE.test(name)) return null;
  if (SEALED.test(name)) return 'sealed';
  if (NONCARD.test(name)) return null;
  const ext = p.extendedData || [];
  if (ext.length) return ext.some(d => /^(number|rarity)$/i.test(d.name || '')) ? 'single' : null;
  return 'single'; // no metadata on this set — treat priced non-sealed as a card
}

async function main() {
  const cats = await pokemonCategories();
  console.log('Categories:', cats.map(c => `${c.lang}:${c.id}`).join(' '));

  const products = [];
  const prices = {};
  const now = Date.now();

  for (const cat of cats) {
    const groups = await getJSON(`https://tcgcsv.com/tcgplayer/${cat.id}/groups`);
    if (!groups) { console.warn(`No groups for category ${cat.id}`); continue; }

    for (const g of groups) {
      const [prods, priceRows] = await Promise.all([
        getJSON(`https://tcgcsv.com/tcgplayer/${cat.id}/${g.groupId}/products`),
        getJSON(`https://tcgcsv.com/tcgplayer/${cat.id}/${g.groupId}/prices`)
      ]);
      if (!prods || !priceRows) continue;

      const priceById = {};
      for (const row of priceRows) {
        const v = row.marketPrice ?? row.midPrice ?? null;
        if (v != null && v > 0) priceById[row.productId] = v;
      }

      const ageM = g.publishedOn ? (now - new Date(g.publishedOn).getTime()) / (1000 * 60 * 60 * 24 * 30.44) : 0;

      for (const p of prods) {
        const price = priceById[p.productId];
        if (price == null) continue;            // unpriced = noise
        const kind = classify(p);
        if (!kind) continue;
        const id = String(p.productId);
        const status = kind === 'single' ? 'raw' : (ageM > OOP_MONTHS ? 'oop' : 'in-print');
        const entry = { id, type: kind, name: p.name, status, set: g.name };
        if (p.imageUrl) entry.img = p.imageUrl;   // TCGplayer CDN thumbnail
        if (cat.lang === 'JP') entry.jp = true;  // flag for the JP/EN toggle
        products.push(entry);
        prices[id] = Math.round(price * 100) / 100;
      }
    }
    console.log(`${cat.lang}: running total ${products.length} products`);
  }

  if (products.length < 100) {
    console.error(`Only ${products.length} products — looks wrong; leaving files untouched.`);
    process.exit(1);
  }

  await writeFile('products.json', JSON.stringify(products));
  await writeFile('prices.json', JSON.stringify(prices));
  const jp = products.filter(p => p.jp).length;
  console.log(`Wrote ${products.length} products (${jp} JP, ${products.length - jp} EN).`);
}

main().catch(e => { console.error(e); process.exit(1); });
