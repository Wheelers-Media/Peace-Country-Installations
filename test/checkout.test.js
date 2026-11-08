import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { validateCart, buildPaymentLink, POST } from '../api/checkout.js';

const CABLE = 'starlink-mini-12v-dc-cable-with-30v-booster';
const GEN4 = 'starlink-gen-4-cable-multiple-lengths';
const MOUNT = 'gen-2-router-wall-mount';

test('a valid cart passes and resolves server-side prices', () => {
  const r = validateCart([{ id: CABLE, variant: '5m', qty: 2 }, { id: MOUNT, qty: 1 }]);
  assert.equal(r.error, undefined);
  assert.deepEqual(r.lines.map((l) => [l.qty, l.cents]), [[2, 3500], [1, 5000]]);
});

test('invalid carts are rejected', () => {
  const bad = [
    [],
    'nope',
    null,
    Array.from({ length: 21 }, () => ({ id: MOUNT, qty: 1 })),
    [{ id: 'unknown', qty: 1 }],
    [{ id: GEN4, qty: 1 }],
    [{ id: MOUNT, qty: 0 }],
    [{ id: MOUNT, qty: -1 }],
    [{ id: MOUNT, qty: 1.5 }],
    [{ id: MOUNT, qty: 'abc' }],
    [{ id: MOUNT, qty: 21 }],
  ];
  for (const items of bad) assert.ok(validateCart(items).error, JSON.stringify(items));
});

test('a client-supplied price is ignored', () => {
  const r = validateCart([{ id: MOUNT, qty: 1, price: 1, cents: 1 }]);
  assert.equal(r.lines[0].cents, 5000);
});

test('buildPaymentLink builds line items, GST, shipping prompt and redirect', () => {
  const { lines } = validateCart([{ id: CABLE, variant: '3m', qty: 2 }, { id: GEN4, variant: '45m', qty: 1 }]);
  const body = buildPaymentLink(lines, 'LOC123', 'idem-1');
  assert.equal(body.idempotency_key, 'idem-1');
  assert.equal(body.order.location_id, 'LOC123');
  assert.deepEqual(body.order.line_items, [
    { name: 'Starlink Mini 12V DC Cable with 30V Booster (3m)', quantity: '2', base_price_money: { amount: 3500, currency: 'CAD' } },
    { name: 'Starlink Gen 4 Cable (Multiple Lengths) (45m)', quantity: '1', base_price_money: { amount: 21000, currency: 'CAD' } },
  ]);
  assert.deepEqual(body.order.taxes, [{ name: 'GST', percentage: '5', scope: 'ORDER' }]);
  assert.equal(body.checkout_options.ask_for_shipping_address, true);
  assert.equal(body.checkout_options.redirect_url, 'https://peacecountryinstallations.ca/store?thanks=1');
});

const realFetch = globalThis.fetch;
const env = { ...process.env };
let calls;
const post = (body) => POST(new Request('http://localhost/api/checkout', {
  method: 'POST', headers: { 'content-type': 'application/json' }, body: typeof body === 'string' ? body : JSON.stringify(body),
}));
const stubFetch = (status, json) => { globalThis.fetch = async (...a) => { calls.push(a); return new Response(JSON.stringify(json), { status }); }; };

beforeEach(() => {
  calls = [];
  process.env.SQUARE_ACCESS_TOKEN = 'tok_secret';
  process.env.SQUARE_LOCATION_ID = 'LOC123';
});
afterEach(() => {
  globalThis.fetch = realFetch;
  process.env.SQUARE_ACCESS_TOKEN = env.SQUARE_ACCESS_TOKEN;
  process.env.SQUARE_LOCATION_ID = env.SQUARE_LOCATION_ID;
  if (env.SQUARE_ACCESS_TOKEN === undefined) delete process.env.SQUARE_ACCESS_TOKEN;
  if (env.SQUARE_LOCATION_ID === undefined) delete process.env.SQUARE_LOCATION_ID;
});

test('POST returns the Square checkout url and sends the bearer token', async () => {
  stubFetch(200, { payment_link: { url: 'https://square.link/u/abc' } });
  const res = await post({ items: [{ id: MOUNT, qty: 1 }] });
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { url: 'https://square.link/u/abc' });
  assert.equal(calls[0][1].headers.Authorization, 'Bearer tok_secret');
});

test('POST answers 502 with a generic message when Square fails or returns no url', async () => {
  for (const [status, json] of [[500, { errors: [{ detail: 'SQUARE INTERNAL' }] }], [200, {}]]) {
    stubFetch(status, json);
    const res = await post({ items: [{ id: MOUNT, qty: 1 }] });
    const text = await res.text();
    assert.equal(res.status, 502);
    assert.ok(!text.includes('tok_secret'));
    assert.ok(!text.includes('SQUARE INTERNAL'));
  }
});

test('POST answers 500 when Square env vars are missing', async () => {
  delete process.env.SQUARE_ACCESS_TOKEN;
  stubFetch(200, {});
  const res = await post({ items: [{ id: MOUNT, qty: 1 }] });
  assert.equal(res.status, 500);
  assert.equal(calls.length, 0);
});

test('POST answers 400 for an invalid cart or body without calling Square', async () => {
  stubFetch(200, {});
  assert.equal((await post({ items: [] })).status, 400);
  assert.equal((await post('not json')).status, 400);
  assert.equal(calls.length, 0);
});
