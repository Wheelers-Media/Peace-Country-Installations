import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validate, buildEvent } from '../api/quote.js';

const form = (o) => { const f = new FormData(); for (const [k, v] of Object.entries(o)) f.append(k, v); return f; };
const ok = { name: 'Pat Example', phone: '780-555-0100', email: 'pat@example.com', service: 'Equipment Rentals', location: 'Sexsmith' };

test('accepts a valid submission', () => {
  const r = validate(form(ok));
  assert.equal(r.error, undefined);
  assert.equal(r.fields.service, 'Equipment Rentals');
});

test('rejects missing required, bad email, unknown service, oversized notes', () => {
  assert.ok(validate(form({ ...ok, phone: '' })).error);
  assert.ok(validate(form({ ...ok, email: 'nope' })).error);
  assert.ok(validate(form({ ...ok, service: 'Hacking' })).error);
  assert.ok(validate(form({ ...ok, location: 'x'.repeat(4001) })).error);
});

test('builds an all-day event that rolls over month end', () => {
  const ev = buildEvent(validate(form(ok)).fields, '2026-10-31');
  assert.deepEqual([ev.start.date, ev.end.date], ['2026-10-31', '2026-11-01']);
  assert.match(ev.summary, /Pat Example \(Equipment Rentals\)/);
  assert.match(ev.description, /Sexsmith/);
});
