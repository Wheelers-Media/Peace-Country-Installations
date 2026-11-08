import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  addLine, setQty, removeLine, parseCart, cartDetails, subtotalCents, loadCart, saveCart,
} from '../src/lib/cart.js';

const CABLE = 'starlink-mini-12v-dc-cable-with-30v-booster';
const GEN4 = 'starlink-gen-4-cable-multiple-lengths';
const MOUNT = 'gen-2-router-wall-mount';

test('adding the same product and variant twice merges into one line', () => {
  let cart = addLine([], CABLE, '5m');
  cart = addLine(cart, CABLE, '5m');
  assert.deepEqual(cart, [{ id: CABLE, variant: '5m', qty: 2 }]);
});

test('different variants of one product stay separate lines', () => {
  const cart = addLine(addLine([], CABLE, '3m'), CABLE, '5m');
  assert.equal(cart.length, 2);
});

test('quantity is capped at 20 when adding', () => {
  const cart = addLine([{ id: MOUNT, variant: null, qty: 19 }], MOUNT, null, 5);
  assert.equal(cart[0].qty, 20);
});

test('setQty to 0 removes the line', () => {
  const cart = setQty([{ id: MOUNT, variant: null, qty: 2 }], MOUNT, null, 0);
  assert.deepEqual(cart, []);
});

test('setQty ignores fractional and NaN quantities', () => {
  const start = [{ id: MOUNT, variant: null, qty: 2 }];
  assert.deepEqual(setQty(start, MOUNT, null, 1.5), start);
  assert.deepEqual(setQty(start, MOUNT, null, NaN), start);
});

test('removeLine removes only the matching id and variant', () => {
  const start = [{ id: CABLE, variant: '3m', qty: 1 }, { id: CABLE, variant: '5m', qty: 1 }];
  assert.deepEqual(removeLine(start, CABLE, '3m'), [{ id: CABLE, variant: '5m', qty: 1 }]);
});

test('parseCart treats corrupt, non-array and null input as an empty cart', () => {
  assert.deepEqual(parseCart('not json'), []);
  assert.deepEqual(parseCart('{}'), []);
  assert.deepEqual(parseCart(null), []);
});

test('parseCart drops unknown ids, bad variants and out-of-range quantities', () => {
  const raw = JSON.stringify([
    { id: 'gone', variant: null, qty: 1 },
    { id: CABLE, variant: '9m', qty: 1 },
    { id: MOUNT, variant: null, qty: 0 },
    { id: MOUNT, variant: null, qty: 21 },
    { id: MOUNT, variant: null, qty: 1.5 },
    { id: MOUNT, variant: null, qty: 3 },
  ]);
  assert.deepEqual(parseCart(raw), [{ id: MOUNT, variant: null, qty: 3 }]);
});

test('subtotal for 2 x 12V cable (5m) and 1 x Gen 4 cable (15m) is $175.00', () => {
  const cart = [{ id: CABLE, variant: '5m', qty: 2 }, { id: GEN4, variant: '15m', qty: 1 }];
  assert.equal(subtotalCents(cart), 17500);
  assert.equal(cartDetails(cart)[0].name, 'Starlink Mini 12V DC Cable with 30V Booster (5m)');
});

test('loadCart and saveCart are safe when localStorage is unavailable', () => {
  assert.deepEqual(loadCart(), []);
  assert.doesNotThrow(() => saveCart([{ id: MOUNT, variant: null, qty: 1 }]));
});
