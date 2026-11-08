# Cart, GST Checkout and 12V Cable Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Customers can add several store items to a cart and pay in one Square checkout with 5% GST, and the 12V cable listing shows the new photo and description.

**Architecture:** `capture/products.json` stays the product list; `src/lib/catalog.js` derives ids, cents and variants from it and is the only price source, used by both the browser cart and the server. Cart state is pure functions in `src/lib/cart.js` persisted to `localStorage`. `api/checkout.js` validates the cart, builds a Square payment-link body (line items + GST) and returns Square's URL.

**Tech Stack:** Astro 7 static site, Vercel serverless function (ESM, Web `Request`/`Response`), `node --test`, Square Online Checkout API (`POST /v2/online-checkout/payment-links`).

**Spec:** `docs/superpowers/specs/2026-11-08-cart-and-gst-design.md`

## Global Constraints

- Currency CAD; all money handled as integer cents; GST `percentage: '5'`, `scope: 'ORDER'`, name `GST`.
- Prices come only from `src/lib/catalog.js`; the browser never sends a price.
- Quantities are integers 1..20; max 20 cart lines.
- Env vars: `SQUARE_ACCESS_TOKEN`, `SQUARE_LOCATION_ID`; never returned, logged or sent to the client.
- Cart storage key `pci-cart`; every `localStorage` access in try/catch.
- Redirect after payment: `https://peacecountryinstallations.ca/store?thanks=1`.
- 12V cable: name `Starlink Mini 12V DC Cable with 30V Booster`, `$35.00`, variants `3m` and `5m`. Gen 4 cable variants `15m` $105.00 and `45m` $210.00.
- Primary CTA wording elsewhere on the site is unchanged; phone number on errors is `587-416-0303`.
- Use existing CSS tokens in `src/styles/global.css`; no new dependencies.

## Review Focus

- A product id in `localStorage` that no longer exists in the catalog: dropped silently, store page still works (Task 2).
- Quantity `0`, `-1`, `1.5`, `"abc"`, or `21`: rejected by the API, clamped or ignored by the cart (Tasks 2, 3).
- Corrupt or non-array JSON in `pci-cart`: treated as an empty cart (Task 2).
- Adding the same product and variant twice: one line with summed quantity, capped at 20 (Task 2).
- Square returns non-200, or 200 with no URL: API answers 502 with a generic message and the cart is left intact (Task 3).
- Double-clicking Checkout: button disabled while the request is pending so only one link is created (Task 5).

---

### Task 1: Catalog and 12V cable listing

**Files:**
- Create: `src/lib/catalog.js`, `test/catalog.test.js`
- Copy: `/mnt/user-data/uploads/cbd4e7e7-image.png` to `capture/assets/12v-cable-30v-booster.png`
- Modify: `capture/products.json` (the "Starlink Mini 12V Car Adapter" entry), `src/pages/store.astro` (the `extras` key for that product)

**Interfaces:**
- Produces: `slugify(name: string): string`; `catalog: Array<{ id: string, name: string, cents: number, variants: Array<{ key: string, label: string, cents: number }> | null }>`; `resolveLine(id: string, variant?: string): { name: string, cents: number } | null` (name includes variant label, e.g. `... (5m)`; returns `null` for unknown id or missing/invalid variant on a product that has variants).

- [ ] **Step 1: Write failing tests in `test/catalog.test.js`**: `resolveLine('starlink-mini-12v-dc-cable-with-30v-booster', '3m')` and `'5m'` both give `cents === 3500`; `resolveLine('starlink-gen-4-cable-multiple-lengths', '15m').cents === 10500` and `'45m'` is `21000`; Gen 4 cable with no variant is `null`; unknown id is `null`; a no-variant product (`'gen-2-router-wall-mount'`) resolves to `5000`; every product in `products.json` has a unique `id`.
- [ ] **Step 2: Run** `node --test test/catalog.test.js`; expect FAIL (module missing).
- [ ] **Step 3: Update `capture/products.json`**: rename the 12V entry to `Starlink Mini 12V DC Cable with 30V Booster`, price `$35.00`, description from Dylan's message ("Power your Starlink Mini directly from your vehicle's 12V power system. The built-in 30V voltage booster helps maintain stable power delivery, reducing unexpected reboots and connection dropouts when vehicle battery voltage fluctuates. Keep your Starlink Mini powered and connected wherever the job takes you."), `image_path` `assets/12v-cable-30v-booster.png`; leave `checkout_url` fields untouched. Copy the image into `capture/assets/`. In `store.astro` rename the `extras` key and set features to `['Direct 12V vehicle power integration', 'Built-in 30V voltage booster for stable power delivery', 'Available in 3m or 5m lengths']`.
- [ ] **Step 4: Implement `src/lib/catalog.js`**: import `capture/products.json` (`with { type: 'json' }`), build `catalog` by parsing `price` strings to cents, with a `VARIANTS` map keyed by product id supplying the two variant sets above.
- [ ] **Step 5: Run** `node --test test/catalog.test.js`; expect PASS. Also run `npm run build`; expect success (image and JSON resolve).
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: catalog module and 12V DC cable with 30V booster listing"`

### Task 2: Cart logic

**Files:**
- Create: `src/lib/cart.js`, `test/cart.test.js`

**Interfaces:**
- Consumes: `resolveLine` from Task 1.
- Produces (all pure unless noted): `type Line = { id: string, variant: string | null, qty: number }`; `addLine(cart: Line[], id: string, variant: string | null, qty?: number): Line[]`; `setQty(cart: Line[], id: string, variant: string | null, qty: number): Line[]` (qty < 1 removes); `removeLine(cart, id, variant): Line[]`; `parseCart(raw: string | null): Line[]`; `cartDetails(cart): Array<{ id, variant, qty, name, cents }>` and `subtotalCents(cart): number` (both drop lines `resolveLine` rejects); `loadCart(): Line[]` and `saveCart(cart: Line[]): void` (use `localStorage`, `pci-cart`, try/catch).

- [ ] **Step 1: Write failing tests** covering: add twice merges and sums (`qty` 2); add beyond 20 caps at 20; `setQty(...,0)` removes; `setQty(...,1.5)` and `NaN` are ignored (cart unchanged); `parseCart('not json')`, `parseCart('{}')`, `parseCart(null)` all `[]`; `parseCart` drops lines with unknown ids, bad variants or qty outside 1..20; `subtotalCents` for 2 x 12V cable (5m) + 1 x Gen 4 cable 15m is `17500`.
- [ ] **Step 2: Run** `node --test test/cart.test.js`; expect FAIL.
- [ ] **Step 3: Implement `src/lib/cart.js`** to those signatures; `parseCart` validates via `resolveLine` and integer/range checks.
- [ ] **Step 4: Run** `node --test`; expect all PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: cart state functions"`

### Task 3: Checkout API

**Files:**
- Create: `api/checkout.js`, `test/checkout.test.js`

**Interfaces:**
- Consumes: `resolveLine` from Task 1.
- Produces: `validateCart(items: unknown): { error: string } | { lines: Array<{ id, variant, qty, name, cents }> }`; `buildPaymentLink(lines, locationId: string, idempotencyKey: string): object` (Square request body); `POST(request: Request): Promise<Response>` returning `{ url }` (200), `{ error }` (400/500/502).

- [ ] **Step 1: Write failing tests** for `validateCart`: valid cart passes; empty array, non-array, 21 lines, unknown id, missing variant on Gen 4 cable, qty `0` / `-1` / `1.5` / `"abc"` / `21` each return `{ error }`; client-supplied `price` field is ignored. For `buildPaymentLink`: two lines produce two `order.line_items` with `base_price_money: { amount: 3500, currency: 'CAD' }` and `quantity` as a string; names include the variant label; `order.taxes` equals `[{ name: 'GST', percentage: '5', scope: 'ORDER' }]`; `order.location_id` set; `checkout_options.ask_for_shipping_address === true` and `redirect_url` is the thanks URL; `idempotency_key` passed through. For `POST` (stub global `fetch`): Square 200 with `payment_link.url` returns `{ url }`; Square 500, and Square 200 without a url, both return 502 with a generic error and the response body contains neither the token nor Square's text; missing env vars return 500; invalid cart returns 400 without calling `fetch`.
- [ ] **Step 2: Run** `node --test test/checkout.test.js`; expect FAIL.
- [ ] **Step 3: Implement `api/checkout.js`** matching the `api/quote.js` style (exported pure helpers, `POST(request)`), calling `https://connect.squareup.com/v2/online-checkout/payment-links` with `Authorization: Bearer`, `Square-Version` header set to the current API version pinned in a constant, `crypto.randomUUID()` for the idempotency key, and logging only status codes server-side.
- [ ] **Step 4: Run** `node --test`; expect all PASS.
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: checkout API with GST payment links"`

### Task 4: Product cards and store page

**Files:**
- Modify: `src/components/ProductCard.astro`, `src/pages/store.astro`

**Interfaces:**
- Consumes: `catalog` from Task 1 (to look up id and variants per product).
- Produces: each card renders a `<button class="btn btn-primary btn-block add-to-cart" data-id data-variant-select?>` and, when variants exist, a labelled `<select>` ; the button dispatches `window.dispatchEvent(new CustomEvent('cart:add', { detail: { id, variant } }))`. `store.astro` renders a `<p role="status" id="thanks">` notice only when `?thanks=1` (hidden otherwise).

- [ ] **Step 1: Modify `ProductCard.astro`** to accept `id` and `variants` props, replace the external link with the Add to Cart button and the variant select (default first variant; shows price per variant when prices differ). The visible price for products with differing variant prices reads "From $X CAD".
- [ ] **Step 2: Modify `store.astro`** to pass `id`/`variants` from `catalog` and add the thank-you notice markup.
- [ ] **Step 3: Verify** `npm run build` succeeds, then `npm run preview` and fetch `/store`: the HTML contains 9 `add-to-cart` buttons, no `square.link` hrefs, and the Gen 4 and 12V cards contain a `<select>`.
- [ ] **Step 4: Commit** `git add -A && git commit -m "feat: add-to-cart buttons and variant selectors on store"`

### Task 5: Cart drawer, header button and checkout flow

**Files:**
- Create: `src/components/CartDrawer.astro`
- Modify: `src/layouts/Layout.astro` (mount the drawer; add a header cart button with count badge in both desktop and mobile nav)

**Interfaces:**
- Consumes: `loadCart`, `saveCart`, `addLine`, `setQty`, `removeLine`, `cartDetails`, `subtotalCents` from Task 2; the `cart:add` event from Task 4; `POST /api/checkout` from Task 3.

- [ ] **Step 1: Build `CartDrawer.astro`**: `<dialog>`-based drawer with line items (name, qty +/- buttons, remove), subtotal, the note "GST (5%) is added at checkout", and a Checkout button; empty state text; header badge uses `aria-live="polite"`; Esc and backdrop click close; focus returns to the cart button.
- [ ] **Step 2: Client script in the component**: listens for `cart:add` (add, save, re-render, open drawer); Checkout posts `{ items }` to `/api/checkout`, disables the button while pending, sets `location.href` to the returned `url`, and on any failure shows "We couldn't start checkout. Please try again or call 587-416-0303." leaving the cart intact. On `/store?thanks=1`, clear the cart and show the notice from Task 4.
- [ ] **Step 3: Verify** `npm run build` succeeds and `node --test` passes. Run `npm run preview`, open `/store` in the browser, add a 5m 12V cable twice and one Gen 4 cable 15m: the badge reads 3, the drawer subtotal is `$175.00`, quantities change with +/-, reload keeps the cart, and the layout works at mobile width.
- [ ] **Step 4: Commit** `git add -A && git commit -m "feat: cart drawer, header cart button and checkout flow"`

### Task 6: Preview deployment and live-link check

**Files:** none (deployment and verification only).

- [ ] **Step 1: Push** `git push -u origin feat/cart-checkout`; find the preview deployment with the Vercel MCP (`list_deployments`, branch `feat/cart-checkout`) and wait for `READY`.
- [ ] **Step 2: Verify the preview** in the built-in browser: add items, press Checkout, and confirm Square's page shows each line, subtotal, **GST 5%**, the correct total, and a shipping-address prompt. Do not pay. Expected: GST line present and total = subtotal x 1.05.
- [ ] **Step 3: Verify error path** by checking the Vercel runtime logs (`get_runtime_logs`) show no secret values, and (if feasible) that a forced failure shows the call-us message.
- [ ] **Step 4: Hand the preview URL and screenshots to Nathan**; merge to `main` only after he approves.

---

Spec coverage: catalog/prices/cable listing (Task 1), cart (Tasks 2, 4, 5), checkout and GST (Task 3), error handling (Tasks 3, 5), testing and preview/live check (Tasks 1-3, 6).
