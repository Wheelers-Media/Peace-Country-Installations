// Single source of truth for store prices. Used by the browser cart and by api/checkout.js.
import products from '../../capture/products.json' with { type: 'json' };

export const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

const toCents = (price) => Math.round(parseFloat(String(price).replace(/[^0-9.]/g, '')) * 100);

// Variant sets keyed by product id; products.json only holds one display price.
const VARIANTS = {
  'starlink-gen-4-cable-multiple-lengths': [
    { key: '15m', label: '15m', cents: 10500 },
    { key: '45m', label: '45m', cents: 21000 },
  ],
  'starlink-mini-12v-dc-cable-with-30v-booster': [
    { key: '3m', label: '3m', cents: 3500 },
    { key: '5m', label: '5m', cents: 3500 },
  ],
};

export const catalog = products.map((p) => {
  const id = slugify(p.name);
  return { id, name: p.name, cents: toCents(p.price), variants: VARIANTS[id] ?? null };
});

export function resolveLine(id, variant) {
  const product = catalog.find((p) => p.id === id);
  if (!product) return null;
  if (!product.variants) return { name: product.name, cents: product.cents };
  const v = product.variants.find((x) => x.key === variant);
  if (!v) return null;
  return { name: `${product.name} (${v.label})`, cents: v.cents };
}
