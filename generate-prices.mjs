/*
 * generate-prices.mjs: Holomint catalog build step
 * Pulls the FULL Pokémon catalog (English + Japanese) from TCGcsv:
 * every priced product: sealed, singles, all price tiers, both languages.
 * Writes products.json + prices.json. Runs daily via GitHub Actions. Node 18+.
 */
import { writeFile } from 'node:fs/promises';

/* products.json is the biggest thing on the critical path: it is fetched before
   the load event, so its bytes are time a visitor spends on a splash screen.
   Measured on the real catalogue: 10.7 MB -> 2.2 MB raw, 824 KB -> 445 KB gzip.
   Three savings, no data lost:
     - `img` is dropped. All 60,168 rows were exactly
       product/{id}_200w.jpg, with zero exceptions, so it is 60k copies of a
       50-character prefix the app can rebuild from an id it already has.
     - `set` (658 distinct), `type` (2) and `status` (3) are interned to an
       index into a table, instead of repeating the string on every row.
     - columnar, so the key names appear once each rather than 60,168 times.
   The app decodes this back to the identical row objects, img included, so
   nothing downstream of the fetch knows the format changed. */
function encodeCatalog(products) {
  const sets = [...new Set(products.map(p => p.set))].sort();
  const types = [...new Set(products.map(p => p.type))].sort();
  const statuses = [...new Set(products.map(p => p.status))].sort();
  const si = new Map(sets.map((v, i) => [v, i]));
  const ti = new Map(types.map((v, i) => [v, i]));
  const ui = new Map(statuses.map((v, i) => [v, i]));
  return {
    f: 2,                       // format version; the app still reads a bare array
    sets, types, statuses,
    id:     products.map(p => p.id),
    name:   products.map(p => p.name),
    set:    products.map(p => si.get(p.set)),
    type:   products.map(p => ti.get(p.type)),
    status: products.map(p => ui.get(p.status)),
    // jp landed on the in-memory rows (entry.jp) but never on the wire, so the
    // columnar migration silently dropped the ENTIRE Japanese half of the
    // catalog from the app: the JP toggle filtered everything out and JP rows
    // leaked into the EN view unlabeled. Found live on launch morning.
    jp:     products.map(p => (p.jp ? 1 : 0)),
  };
}

/* Row count for either shape. The shrink guard below used Array.isArray(prev),
   which would have gone quietly false the moment the format changed -- the
   check would still "pass" every run while testing nothing at all. */
/* history.json is 29,223 products x up to 47 daily points, and every point was
   written as {"d":"2026-07-14","p":86.08} -- 1.2 million copies of the same two
   key names and of a date string shared across the whole file. The date axis is
   the union of all dates seen (47 of them), so each product becomes a plain
   array of prices aligned to it, null where it has no reading that day.

   Measured on the real file: 35.25MB -> 7.11MB raw, 3.377MB -> 0.825MB gzipped,
   round trip byte-identical.

   Fetched AFTER the load event, so this is sparkline latency rather than first
   paint -- which is why it went second. */
function encodeHistory(hist) {
  const dates = [...new Set(Object.values(hist).flat().map(pt => pt.d))].sort();
  const idx = new Map(dates.map((d, i) => [d, i]));
  const p = {};
  for (const [id, pts] of Object.entries(hist)) {
    const row = new Array(dates.length).fill(null);
    for (const pt of pts) {
      const i = idx.get(pt.d);
      if (i !== undefined) row[i] = pt.p;
    }
    p[id] = row;
  }
  return { f: 2, d: dates, p };
}

/* Back to {id: [{d,p}, ...]}. The append cycle below runs on THIS shape, so the
   daily job reads, decodes, appends exactly as it always did, and re-encodes on
   the way out. Keeping the append logic untouched is deliberate: it is the part
   that would corrupt history slowly and invisibly if it were wrong. */
function decodeHistory(raw) {
  if (!raw || typeof raw !== 'object') return {};
  if (!Array.isArray(raw.d)) return raw;      // previous format: already {id:[{d,p}]}
  const out = {};
  for (const [id, row] of Object.entries(raw.p || {})) {
    const pts = [];
    for (let i = 0; i < row.length; i++) {
      if (row[i] !== null && row[i] !== undefined) pts.push({ d: raw.d[i], p: row[i] });
    }
    out[id] = pts;
  }
  return out;
}

function catalogLength(v) {
  if (Array.isArray(v)) return v.length;
  if (v && Array.isArray(v.id)) return v.id.length;
  return 0;
}

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
const EXCLUDE = /(code card|online code|empty|opened|damaged|proxy|playtest|lot of|bulk lot|repack|custom|\berror\b|misprint|miscut|test print)/i;
const NONCARD = /(playmat|sleeve|deck box|binder|portfolio|^coin$| coin$|pin\b|figure|plush|dice|damage counter|marker|album|toploader|booster case|display case)/i;

const OOP_MONTHS = 24;

function classify(p) {
  const name = p.name || '';
  if (!name || EXCLUDE.test(name)) return null;
  // Metadata outranks the name: promo CARDS are named after the product they came in
  // ("Squirtle - 33/214 (Premium Collection Promo)", "... Elite Trainer Box"), so a
  // name test alone misfiles them as sealed. A card Number in extendedData settles it.
  const ext = p.extendedData || [];
  if (ext.some(d => /^number$/i.test(d.name || ''))) return 'single';
  if (SEALED.test(name)) return 'sealed';
  if (NONCARD.test(name)) return null;
  if (ext.length) return ext.some(d => /^rarity$/i.test(d.name || '')) ? 'single' : null;
  return 'single'; // no metadata on this set, so treat priced non-sealed as a card
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
        // fall through every available price type, including promos and low-volume cards
        // often have no marketPrice but do have mid/low. Never lose a card to this.
        const v = row.marketPrice ?? row.midPrice ?? row.directLowPrice ?? row.lowPrice ?? row.highPrice ?? null;
        if (v != null && v > 0) {
          // prefer the highest-confidence price if a product has multiple rows (e.g. foil + normal)
          if (priceById[row.productId] == null) priceById[row.productId] = v;
        }
      }

      const ageM = g.publishedOn ? (now - new Date(g.publishedOn).getTime()) / (1000 * 60 * 60 * 24 * 30.44) : 0;

      for (const p of prods) {
        const price = priceById[p.productId];
        const kind = classify(p);
        if (!kind) continue;
        // keep the card even if unpriced, because searchability matters more than price coverage.
        // (sealed with no price is usually noise; require a price for sealed only.)
        if (price == null && kind === 'sealed') continue;
        const id = String(p.productId);
        const status = kind === 'single' ? 'raw' : (ageM > OOP_MONTHS ? 'oop' : 'in-print');
        const entry = { id, type: kind, name: p.name, status, set: g.name };
        if (p.imageUrl) entry.img = p.imageUrl;   // TCGplayer CDN thumbnail
        if (cat.lang === 'JP') entry.jp = true;  // flag for the JP/EN toggle
        products.push(entry);
        if (price != null) prices[id] = Math.round(price * 100) / 100;
      }
    }
    console.log(`${cat.lang}: running total ${products.length} products`);
  }

  if (products.length < 100) {
    console.error(`Only ${products.length} products, which looks wrong. Leaving files untouched.`);
    process.exit(1);
  }

  // A floor only catches total collapse. The realistic failure is partial: getJSON
  // swallows a fetch error, returns null, and a whole category is skipped, so the run
  // still produces tens of thousands of rows and commits happily over a good file.
  // Compare against what is already committed and refuse to shrink the catalog sharply.
  // Growth is never blocked, since new sets are the normal case.
  try {
    // readFile is not imported at module scope in this file, only dynamically further down.
    const { readFile } = await import('node:fs/promises');
    const prevRaw = await readFile('products.json', 'utf8').catch(() => null);
    if (prevRaw) {
      const prev = JSON.parse(prevRaw);
      const prevN = catalogLength(prev);
      if (prevN > 1000) {
        const drop = 1 - (products.length / prevN);
        if (drop > 0.15) {
          console.error(`Catalog shrank ${(drop * 100).toFixed(1)}% (${prev.length} to ${products.length}). ` +
            `That is a partial fetch, not a real change. Leaving files untouched.`);
          process.exit(1);
        }
      }
    }
    const prevPricesRaw = await readFile('prices.json', 'utf8').catch(() => null);
    if (prevPricesRaw) {
      const prevPrices = JSON.parse(prevPricesRaw);
      const prevN = Object.keys(prevPrices).length, nowN = Object.keys(prices).length;
      if (prevN > 1000 && (1 - nowN / prevN) > 0.15) {
        console.error(`Priced rows fell from ${prevN} to ${nowN}. Leaving files untouched.`);
        process.exit(1);
      }
    }
  } catch (e) {
    console.error('Sanity comparison failed, continuing:', e.message);
  }

  await writeFile('products.json', JSON.stringify(encodeCatalog(products)));
  await writeFile('prices.json', JSON.stringify(prices));

  // Price history: append today's snapshot for tracked movers (keeps file lean,
  // only items >= $2, capped, 180-day rolling window). Chart fills in over time.
  const today = new Date().toISOString().slice(0, 10);
  let hist = {};
  try { const { readFile } = await import('node:fs/promises'); hist = decodeHistory(JSON.parse(await readFile('history.json', 'utf8'))); } catch (e) { hist = {}; }
  const CUTOFF = Date.now() - 180 * 86400 * 1000;
  for (const [id, price] of Object.entries(prices)) {
    if (price < 2) continue;
    if (!hist[id]) hist[id] = [];
    if (!hist[id].some(pt => pt.d === today)) hist[id].push({ d: today, p: price });
    hist[id] = hist[id].filter(pt => new Date(pt.d).getTime() >= CUTOFF);
  }
  await writeFile('history.json', JSON.stringify(encodeHistory(hist)));

  // sealed.json: the catalog the Cloudflare Worker matches drop titles against.
  // This MUST regenerate alongside prices. If it goes stale, sealed products from a
  // NEW set never enter it, the Worker's matcher never matches them, and alerts stop
  // firing for exactly the set that matters most. It fails silently: no error, the
  // drop just lands in the feed with no margin and no push.
  const sealed = products
    .filter(p => p.type === 'sealed' && prices[p.id] > 0)
    .map(p => ({ id: p.id, name: p.name, set: p.set }));
  await writeFile('sealed.json', JSON.stringify(sealed));

  const jp = products.filter(p => p.jp).length;
  const tracked = Object.keys(hist).length;
  console.log(`Wrote ${products.length} products (${jp} JP, ${products.length - jp} EN). History tracks ${tracked} items.`);
  console.log(`Wrote ${sealed.length} priced sealed products to sealed.json (the Worker's matching catalog).`);
}

main().catch(e => { console.error(e); process.exit(1); });
