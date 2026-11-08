# Store cart, GST-correct checkout, and 12V cable listing

Date: 2026-11-08
Requested by: Dylan (via Nathan). Square account owner: Kyle.

## Goal

Let customers buy several store items (and quantities) in one checkout, with
5% GST shown and charged, and refresh the Starlink Mini vehicle power cable
listing with a new photo and description.

## Background (what exists today)

- Astro static site on Vercel (`peace-country-installations`), repo
  `Wheelers-Media/Peace-Country-Installations`.
- `src/pages/store.astro` renders `capture/products.json` through
  `ProductCard.astro`. Each product's Buy Now button opens its own
  `square.link` payment link (`checkout_url`). There is no cart, and tax is
  whatever each individual Square link was configured with (currently none).
- Serverless pattern already in use: `api/quote.js` (exports pure helpers,
  `POST(request)` handler, tested with `node --test`).
- Vercel env vars `SQUARE_ACCESS_TOKEN` and `SQUARE_LOCATION_ID` exist
  (Production only so far).

## Scope

1. Cart: add-to-cart, quantities, header cart icon, slide-out cart.
2. `/api/checkout`: build a Square payment link from the cart with GST.
3. Replace the "Starlink Mini 12V Car Adapter" listing with
   "Starlink Mini 12V DC Cable with 30V Booster" (3m or 5m, $35.00 either).

Out of scope: shipping fees, inventory tracking, accounts, discount codes,
changes to the quote form, removing the old `square.link` data from
`products.json`.

## Design

### Catalog (single source of truth)
`capture/products.json` stays the product list. A new `src/lib/catalog.js`
(plain JS so both Astro and the API function can import it) derives, per
product: stable `id` (slug of name), unit price in cents, and variants.
Variants: Gen 4 Cable `15m` ($105.00) / `45m` ($210.00); 12V Cable `3m` /
`5m` (both $35.00). The server resolves every price from this catalog;
the browser never sends a price.

### Cart (browser)
- `src/lib/cart.js`: pure functions (add, setQty, remove, total, serialize)
  persisted to `localStorage` (key `pci-cart`, wrapped in try/catch).
  Line = `{ id, variant?, qty }`, qty clamped 1..20.
- `ProductCard.astro`: "Add to Cart" button replaces the external Buy link;
  products with variants render a selector. Adds open the cart drawer.
- `CartDrawer.astro` + small client script, mounted in `Layout.astro`:
  header cart button with count badge, accessible dialog drawer, line items
  with +/- and remove, subtotal, "GST (5%) added at checkout" note, Checkout
  button.
- Styling uses the existing tokens in `global.css`; keyboard and
  screen-reader accessible (focus trap, Esc closes, `aria-live` count).

### Checkout (`api/checkout.js`)
- `POST` JSON `{ items: [{ id, variant?, qty }] }`.
- `validateCart(items)` (pure, exported): non-empty, max 20 lines, known id,
  valid variant, integer qty 1..20; returns normalized lines or an error.
- `buildPaymentLink(lines, locationId)` (pure, exported): Square
  `POST /v2/online-checkout/payment-links` body with
  `order.location_id`, one `line_items` entry per line (name includes
  variant, `base_price_money` in CAD cents), order-level tax
  `{ name: 'GST', percentage: '5', scope: 'ORDER' }`,
  `checkout_options.ask_for_shipping_address: true` and
  `redirect_url: https://peacecountryinstallations.ca/store?thanks=1`.
- Handler calls Square with `Authorization: Bearer $SQUARE_ACCESS_TOKEN`,
  a fresh `idempotency_key`, returns `{ url }` (`payment_link.url`).
- Errors: 400 for invalid cart, 502 for Square failures (log status/body
  server-side, never return the token or raw Square errors); missing env
  vars -> 500 with generic message.
- Client: on `url`, `location.href = url`; on error show the message with
  the 587-416-0303 number and keep the cart intact. `/store?thanks=1`
  clears the cart and shows a thank-you notice.

### Cable listing
- Name: Starlink Mini 12V DC Cable with 30V Booster. Price `$35.00`.
- Description and features from Dylan's text (direct 12V integration,
  built-in 30V booster for stable power, 3m or 5m). Photo: the supplied
  image saved into `capture/assets/` and referenced from `products.json`.
- Keeps `buy_button_label` data but the card renders "Add to Cart".

## Testing

- `node --test`: catalog prices/variants; `validateCart` (good, empty,
  unknown id, bad variant, bad qty, too many lines); `buildPaymentLink`
  (line items, cents math, GST present, variant naming, no client prices);
  cart reducer functions.
- `astro build` passes.
- Preview deployment on Vercel (requires Preview scope on the two Square env
  vars) used to create, but not pay, a checkout link; confirm subtotal, GST
  5%, total and shipping-address prompt on Square's page.
- After going live: repeat the create-link check on production; Vercel
  rollback is available if anything is wrong.

## Risks / assumptions

- Assumes Alberta GST 5% with no PST.
- Production token is used for preview testing; creating a payment link
  does not charge anyone.
- Square may refuse or alter fields the account does not support; this is
  discovered in the preview check and handled before go-live.
- Delivery fees are handled manually; customers wanting pickup arrange it
  by phone or email (Square's hosted checkout has no free-text order notes).
