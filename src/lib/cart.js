// Cart state. Pure functions plus localStorage persistence. Lines hold ids, never prices.
import { resolveLine } from './catalog.js';

const KEY = 'pci-cart';
const MAX_QTY = 20;

const validQty = (n) => Number.isInteger(n) && n >= 1 && n <= MAX_QTY;
const same = (l, id, variant) => l.id === id && (l.variant ?? null) === (variant ?? null);

export function addLine(cart, id, variant, qty = 1) {
  const v = variant ?? null;
  const existing = cart.find((l) => same(l, id, v));
  if (!existing) return [...cart, { id, variant: v, qty: Math.min(qty, MAX_QTY) }];
  return cart.map((l) => (l === existing ? { ...l, qty: Math.min(l.qty + qty, MAX_QTY) } : l));
}

export function setQty(cart, id, variant, qty) {
  if (!Number.isInteger(qty)) return cart;
  if (qty < 1) return removeLine(cart, id, variant);
  return cart.map((l) => (same(l, id, variant) ? { ...l, qty: Math.min(qty, MAX_QTY) } : l));
}

export function removeLine(cart, id, variant) {
  return cart.filter((l) => !same(l, id, variant));
}

export function parseCart(raw) {
  let data;
  try { data = JSON.parse(raw); } catch { return []; }
  if (!Array.isArray(data)) return [];
  return data
    .filter((l) => l && typeof l.id === 'string' && validQty(l.qty) && resolveLine(l.id, l.variant ?? null))
    .map((l) => ({ id: l.id, variant: l.variant ?? null, qty: l.qty }));
}

export function cartDetails(cart) {
  return cart.flatMap((l) => {
    const r = resolveLine(l.id, l.variant);
    return r ? [{ ...l, name: r.name, cents: r.cents }] : [];
  });
}

export const subtotalCents = (cart) => cartDetails(cart).reduce((sum, l) => sum + l.cents * l.qty, 0);

export function loadCart() {
  try { return parseCart(localStorage.getItem(KEY)); } catch { return []; }
}

export function saveCart(cart) {
  try { localStorage.setItem(KEY, JSON.stringify(cart)); } catch { /* storage unavailable */ }
}
