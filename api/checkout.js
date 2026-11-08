// Cart checkout: validates the cart against the server-side catalog and asks Square for one
// payment link containing every line item plus 5% GST. Prices never come from the browser.
import { randomUUID } from 'node:crypto';
import { resolveLine } from '../src/lib/catalog.js';

const SQUARE_URL = 'https://connect.squareup.com/v2/online-checkout/payment-links';
const SQUARE_VERSION = '2025-07-16';
const MAX_LINES = 20;
const MAX_QTY = 20;
const THANKS_URL = 'https://peacecountryinstallations.ca/store?thanks=1';

export function validateCart(items) {
  if (!Array.isArray(items) || items.length === 0) return { error: 'Your cart is empty.' };
  if (items.length > MAX_LINES) return { error: 'Your cart has too many items.' };
  const lines = [];
  for (const item of items) {
    const qty = item?.qty;
    if (!Number.isInteger(qty) || qty < 1 || qty > MAX_QTY) return { error: 'Invalid quantity.' };
    const resolved = typeof item.id === 'string' ? resolveLine(item.id, item.variant ?? null) : null;
    if (!resolved) return { error: 'One of the items in your cart is no longer available.' };
    lines.push({ id: item.id, variant: item.variant ?? null, qty, ...resolved });
  }
  return { lines };
}

export function buildPaymentLink(lines, locationId, idempotencyKey) {
  return {
    idempotency_key: idempotencyKey,
    order: {
      location_id: locationId,
      line_items: lines.map((l) => ({
        name: l.name,
        quantity: String(l.qty),
        base_price_money: { amount: l.cents, currency: 'CAD' },
      })),
      taxes: [{ name: 'GST', percentage: '5', scope: 'ORDER' }],
    },
    checkout_options: { ask_for_shipping_address: true, redirect_url: THANKS_URL },
  };
}

export async function POST(request) {
  let payload;
  try { payload = await request.json(); } catch { return Response.json({ error: 'Invalid request.' }, { status: 400 }); }

  const { error, lines } = validateCart(payload?.items);
  if (error) return Response.json({ error }, { status: 400 });

  const token = process.env.SQUARE_ACCESS_TOKEN;
  const locationId = process.env.SQUARE_LOCATION_ID;
  if (!token || !locationId) {
    console.error('checkout: Square credentials are not configured');
    return Response.json({ error: 'Checkout is unavailable right now.' }, { status: 500 });
  }

  try {
    const res = await fetch(SQUARE_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Square-Version': SQUARE_VERSION,
      },
      body: JSON.stringify(buildPaymentLink(lines, locationId, randomUUID())),
    });
    const data = await res.json().catch(() => ({}));
    const url = data?.payment_link?.url;
    if (!res.ok || !url) {
      console.error(`checkout: Square responded ${res.status}`);
      return Response.json({ error: 'Checkout is unavailable right now.' }, { status: 502 });
    }
    return Response.json({ url });
  } catch {
    console.error('checkout: request to Square failed');
    return Response.json({ error: 'Checkout is unavailable right now.' }, { status: 502 });
  }
}
