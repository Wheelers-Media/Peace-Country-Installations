import { test } from 'node:test';
import assert from 'node:assert/strict';
import products from '../capture/products.json' with { type: 'json' };
import { catalog, resolveLine, slugify } from '../src/lib/catalog.js';

const CABLE = 'starlink-mini-12v-dc-cable-with-30v-booster';
const GEN4 = 'starlink-gen-4-cable-multiple-lengths';

test('12V cable is $35.00 in both 3m and 5m', () => {
  assert.equal(resolveLine(CABLE, '3m').cents, 3500);
  assert.equal(resolveLine(CABLE, '5m').cents, 3500);
});

test('variant label is part of the line name', () => {
  assert.equal(resolveLine(CABLE, '5m').name, 'Starlink Mini 12V DC Cable with 30V Booster (5m)');
});

test('Gen 4 cable is $105.00 at 15m and $210.00 at 45m', () => {
  assert.equal(resolveLine(GEN4, '15m').cents, 10500);
  assert.equal(resolveLine(GEN4, '45m').cents, 21000);
});

test('products with variants reject a missing or unknown variant', () => {
  assert.equal(resolveLine(GEN4), null);
  assert.equal(resolveLine(GEN4, '99m'), null);
  assert.equal(resolveLine(CABLE, '4m'), null);
});

test('unknown id resolves to null', () => {
  assert.equal(resolveLine('nope', null), null);
});

test('product without variants resolves from its listed price', () => {
  assert.equal(resolveLine('gen-2-router-wall-mount').cents, 5000);
  assert.equal(resolveLine('gen-2-router-wall-mount', null).cents, 5000);
});

test('every product has a unique id and slugify matches the name', () => {
  const ids = catalog.map((p) => p.id);
  assert.equal(new Set(ids).size, products.length);
  assert.equal(ids.length, products.length);
  assert.equal(slugify('Gen 2 Router Wall Mount'), 'gen-2-router-wall-mount');
});

test('old Car Adapter listing is gone', () => {
  assert.equal(resolveLine('starlink-mini-12v-car-adapter'), null);
});
