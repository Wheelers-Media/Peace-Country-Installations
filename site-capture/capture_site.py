#!/usr/bin/env python3
"""
Site capture tool — crawls every internal page of a site with Playwright (Chromium)
and saves screenshots, rendered HTML, readable content, assets, products and
integrations.

Usage:
    python capture_site.py https://peacecountryinstallations.ca --out ./capture

Output layout (inside --out):
    screenshots/<slug>-desktop.png   1440px wide, full page
    screenshots/<slug>-mobile.png    390px wide, full page
    html/<slug>.html                 rendered DOM after JS has run
    content/<slug>.md                headings, body text, buttons, links
    assets/<original filename>       every image, font and video
    assets/_manifest.json            source URL -> saved filename
    products.json                    name, price, description, image, checkout URL
    integrations.md                  forms, chat widgets, booking embeds, 3rd-party scripts
    summary.txt                      the printed summary + every failure
"""

import argparse
import asyncio
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from collections import OrderedDict, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, unquote, parse_qsl, urlencode

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

NON_PAGE_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?|mp4|webm|mov|m4v|ogg|ogv|mp3|wav|"
    r"woff2?|ttf|otf|eot|css|js|mjs|json|xml|txt|pdf|zip|rar|7z|gz|docx?|xlsx?|pptx?|csv)$", re.I)
ASSET_EXT = {
    "image": re.compile(r"\.(png|jpe?g|gif|webp|avif|svg|ico|bmp|tiff?)$", re.I),
    "font": re.compile(r"\.(woff2?|ttf|otf|eot)$", re.I),
    "video": re.compile(r"\.(mp4|webm|mov|m4v|ogv|m3u8)$", re.I),
}
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|msclkid$|mc_|_ga$|_gl$|ref$)", re.I)
BUY_TEXT = re.compile(r"\b(buy|add to cart|add to bag|order now|purchase|checkout|check out|"
                      r"shop now|get it now|pay now|rent now|lease now|reserve)\b", re.I)
CHECKOUT_HINT = re.compile(r"(checkout|cart|order|payment|pay|purchase|buy|stripe|paypal|"
                           r"square|shopify|/products?/)", re.I)

# Known widget signatures (host or global fragments) -> category label.
CHAT_SIGNS = {
    "intercom": "Intercom", "drift.com": "Drift", "tawk.to": "Tawk.to", "crisp.chat": "Crisp",
    "zdassets.com": "Zendesk", "zopim": "Zendesk Chat", "livechatinc": "LiveChat",
    "tidio": "Tidio", "hs-scripts.com": "HubSpot", "hubspot": "HubSpot",
    "olark": "Olark", "freshchat": "Freshchat", "smartsupp": "Smartsupp",
    "facebook.com/plugins/customerchat": "Facebook Messenger", "connect.facebook.net": "Facebook SDK",
    "chat-widget": "Chat widget", "chatwidget": "Chat widget", "webchat": "Web chat",
    "livechat": "Live chat", "messenger": "Messenger",
}
BOOKING_SIGNS = {
    "calendly": "Calendly", "acuityscheduling": "Acuity", "squareup.com/appointments": "Square Appointments",
    "setmore": "Setmore", "simplybook": "SimplyBook", "youcanbook": "YouCanBookMe",
    "booksy": "Booksy", "housecallpro": "Housecall Pro", "jobber": "Jobber",
    "servicetitan": "ServiceTitan", "tidycal": "TidyCal", "cal.com": "Cal.com",
    "/booking": "Booking embed", "/widget/booking": "Booking embed", "/calendar": "Calendar embed",
    "appointment": "Appointment embed", "schedul": "Scheduling embed",
}
FORM_EMBED_SIGNS = {
    "/widget/form": "Embedded form", "/widget/survey": "Embedded survey", "typeform": "Typeform",
    "jotform": "Jotform", "forms.gle": "Google Forms", "docs.google.com/forms": "Google Forms",
    "hsforms": "HubSpot Forms", "wufoo": "Wufoo", "formstack": "Formstack", "cognitoforms": "Cognito Forms",
}


# --------------------------------------------------------------------------- helpers

def log(msg):
    print(msg, flush=True)


def norm_host(h):
    return (h or "").lower().removeprefix("www.")


def normalize_url(url, base=None):
    """Absolute URL without fragment / tracking params, trailing slash collapsed."""
    if base:
        url = urljoin(base, url)
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((p.scheme, p.netloc.lower(), path, "", urlencode(q), ""))


def slugify(url):
    p = urlparse(url)
    path = unquote(p.path).strip("/")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.replace("/", "--")).strip("-") or "home"
    if p.query:
        slug += "__" + hashlib.md5(p.query.encode()).hexdigest()[:6]
    return slug[:120]


WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def original_filename(url, content_type=None):
    p = urlparse(url)
    name = unquote(os.path.basename(p.path)) or "index"
    name = WIN_BAD.sub("_", name).strip(" .") or "file"
    stem, ext = os.path.splitext(name)
    if stem.lower() in WIN_RESERVED:
        stem = "_" + stem
    if not ext and content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
        if ext == ".jpe":
            ext = ".jpg"
    if len(stem) > 150:
        stem = stem[:150]
    return stem + ext


def asset_kind(url, resource_type=None, content_type=None):
    ct = (content_type or "").lower()
    if resource_type == "font" or ct.startswith("font/") or "font" in ct:
        return "font"
    if resource_type == "media" or ct.startswith("video/"):
        return "video"
    if resource_type == "image" or ct.startswith("image/"):
        return "image"
    path = urlparse(url).path
    for kind, rx in ASSET_EXT.items():
        if rx.search(path):
            return kind
    return None


# --------------------------------------------------------------------------- asset store

class AssetStore:
    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.by_url = OrderedDict()          # url -> {"file", "kind", "bytes"}
        self.by_hash = {}                    # sha1 -> filename
        self.names = set()
        self.wanted = OrderedDict()          # url -> kind (seen in DOM, maybe not yet downloaded)
        self.failed = OrderedDict()          # url -> reason
        self.counts = defaultdict(int)

    def has(self, url):
        return url in self.by_url

    def want(self, url, kind):
        if url and url.startswith("http") and url not in self.by_url:
            self.wanted.setdefault(url, kind)

    def save(self, url, body: bytes, kind, content_type=None):
        if url in self.by_url or not body:
            return self.by_url.get(url, {}).get("file")
        digest = hashlib.sha1(body).hexdigest()
        if digest in self.by_hash:                       # identical file already saved
            fname = self.by_hash[digest]
        else:
            base = original_filename(url, content_type)
            fname, n = base, 2
            stem, ext = os.path.splitext(base)
            while fname.lower() in self.names:           # same name, different content
                fname = f"{stem}-{n}{ext}"
                n += 1
            (self.folder / fname).write_bytes(body)
            self.names.add(fname.lower())
            self.by_hash[digest] = fname
            self.counts[kind] += 1
        self.by_url[url] = {"file": fname, "kind": kind, "bytes": len(body)}
        self.wanted.pop(url, None)
        self.failed.pop(url, None)
        return fname

    def path_for(self, url):
        rec = self.by_url.get(url)
        return f"assets/{rec['file']}" if rec else None

    def write_manifest(self):
        (self.folder / "_manifest.json").write_text(
            json.dumps({"assets": self.by_url, "failed": self.failed}, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- in-page extraction JS

EXTRACT_JS = r"""
() => {
  const abs = u => { try { return new URL(u, location.href).href } catch(e) { return null } };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && (r.width > 0 || r.height > 0);
  };

  // ---- ordered content blocks
  const blocks = [];
  const seen = new Set();
  const sel = 'h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,td,th,dt,dd,label,' +
              'div:not(:has(*)),span:not(:has(*))';
  document.querySelectorAll(sel).forEach(el => {
    if (el.closest('script,style,noscript,template,svg,button,select,option')) return;
    if (el.matches('a, a *') && !el.matches('h1,h2,h3,h4,h5,h6,p,li')) return;
    if (!visible(el)) return;
    const t = txt(el); if (!t || t.length < 2) return;
    const tag = el.tagName.toLowerCase();
    // skip text that is wholly contained in an already-captured ancestor block
    let p = el.parentElement, dup = false;
    while (p) { if (seen.has(p)) { dup = true; break } p = p.parentElement }
    if (dup) return;
    seen.add(el);
    blocks.push({ tag, text: t });
  });

  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .filter(visible).map(h => ({ level: +h.tagName[1], text: txt(h) })).filter(h => h.text);

  // ---- buttons and button-like links
  const buttons = [];
  document.querySelectorAll('button, [role=button], input[type=submit], input[type=button], a.btn, a[class*=button i], a[class*=btn i], [class*=cta i] a')
    .forEach(el => {
      if (!visible(el)) return;
      const label = (txt(el) || el.value || el.getAttribute('aria-label') || '').trim();
      if (!label) return;
      buttons.push({ label, href: el.tagName === 'A' ? abs(el.getAttribute('href')) : null,
                     type: el.tagName.toLowerCase() + (el.type ? ':' + el.type : '') });
    });

  // ---- every link
  const links = [...document.querySelectorAll('a[href]')].map(a => ({
    text: txt(a) || a.getAttribute('aria-label') || (a.querySelector('img') ? '[image] ' + (a.querySelector('img').alt || '') : ''),
    href: abs(a.getAttribute('href')), raw: a.getAttribute('href'), target: a.getAttribute('target') || null
  }));
  // links buried in onclick / data-href (common in page builders)
  document.querySelectorAll('[onclick],[data-href],[data-url],[data-link]').forEach(el => {
    const s = el.getAttribute('data-href') || el.getAttribute('data-url') || el.getAttribute('data-link') ||
              ((el.getAttribute('onclick') || '').match(/(?:location(?:\.href)?|window\.open)\s*\(?\s*=?\s*['"]([^'"]+)['"]/) || [])[1];
    if (s) links.push({ text: txt(el), href: abs(s), raw: s, target: null, scripted: true });
  });

  // ---- assets referenced in the DOM
  const assets = { image: new Set(), video: new Set(), font: new Set() };
  document.querySelectorAll('img').forEach(i => {
    [i.currentSrc, i.getAttribute('src'), i.getAttribute('data-src'), i.getAttribute('data-lazy-src')]
      .forEach(u => u && assets.image.add(abs(u)));
    const ss = i.getAttribute('srcset') || i.getAttribute('data-srcset');
    if (ss) ss.split(',').forEach(c => { const u = c.trim().split(/\s+/)[0]; if (u) assets.image.add(abs(u)) });
  });
  document.querySelectorAll('picture source[srcset]').forEach(s =>
    s.getAttribute('srcset').split(',').forEach(c => { const u = c.trim().split(/\s+/)[0]; if (u) assets.image.add(abs(u)) }));
  document.querySelectorAll('video, video source, audio source').forEach(v => {
    const u = v.getAttribute('src') || v.currentSrc; if (u) assets.video.add(abs(u));
    if (v.poster) assets.image.add(abs(v.poster));
  });
  document.querySelectorAll('link[rel*=icon], meta[property="og:image"], meta[name="twitter:image"]').forEach(l => {
    const u = l.getAttribute('href') || l.getAttribute('content'); if (u) assets.image.add(abs(u));
  });
  document.querySelectorAll('*').forEach(el => {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== 'none') for (const m of bg.matchAll(/url\(["']?([^"')]+)["']?\)/g)) assets.image.add(abs(m[1]));
  });
  // fonts declared in stylesheets we can read
  for (const sh of document.styleSheets) {
    let rules; try { rules = sh.cssRules } catch(e) { continue }
    for (const r of rules || []) if (r.type === 5 /* FONT_FACE */) {
      for (const m of (r.style.getPropertyValue('src') || '').matchAll(/url\(["']?([^"')]+)["']?\)/g))
        assets.font.add(new URL(m[1], sh.href || location.href).href);
    }
  }

  // ---- forms
  const fieldInfo = f => {
    const id = f.id; let label = '';
    if (id) { const l = document.querySelector(`label[for="${CSS.escape(id)}"]`); if (l) label = txt(l) }
    if (!label && f.closest('label')) label = txt(f.closest('label'));
    return { tag: f.tagName.toLowerCase(), type: f.type || null, name: f.name || null, id: id || null,
             label: label || null, placeholder: f.placeholder || null, required: !!f.required,
             options: f.tagName === 'SELECT' ? [...f.options].map(o => o.text.trim()).filter(Boolean) : undefined };
  };
  const forms = [...document.querySelectorAll('form')].map((f, i) => ({
    index: i, id: f.id || null, name: f.getAttribute('name'), action: f.getAttribute('action') ? abs(f.getAttribute('action')) : null,
    method: (f.getAttribute('method') || 'get').toUpperCase(),
    fields: [...f.querySelectorAll('input,select,textarea')].filter(x => x.type !== 'hidden').map(fieldInfo),
    hidden: [...f.querySelectorAll('input[type=hidden]')].map(x => x.name).filter(Boolean),
    submit: [...f.querySelectorAll('button,input[type=submit]')].map(b => txt(b) || b.value).filter(Boolean),
  }));
  // form-like groups that aren't inside a <form> (JS-driven builders)
  const loose = [...document.querySelectorAll('input:not([type=hidden]),textarea,select')].filter(x => !x.closest('form') && visible(x));
  const looseForm = loose.length ? { index: 'no-<form>', action: null, method: 'JS', fields: loose.map(fieldInfo), hidden: [], submit: [] } : null;

  const iframes = [...document.querySelectorAll('iframe')].map(f => ({
    src: abs(f.getAttribute('src') || f.getAttribute('data-src') || ''), id: f.id || null,
    title: f.title || null, w: f.width || null, h: f.height || null }));
  const scripts = [...document.querySelectorAll('script')].map(s => ({
    src: s.src || null, type: s.type || null, async: s.async, defer: s.defer,
    inline: s.src ? null : (s.textContent || '').slice(0, 400) }));

  // ---- products: JSON-LD
  const ld = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try {
      const walk = o => { if (!o) return; if (Array.isArray(o)) return o.forEach(walk);
        if (typeof o === 'object') { const t = [].concat(o['@type'] || []); if (t.includes('Product')) ld.push(o);
          if (o['@graph']) walk(o['@graph']); if (o.itemListElement) walk(o.itemListElement); if (o.item) walk(o.item); } };
      walk(JSON.parse(s.textContent));
    } catch (e) {}
  });

  // ---- products: DOM cards
  const priceRx = /(?:CA?\$|US\$|\$|€|£)\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*(?:\.\d{2})?\s?(?:CAD|USD)/i;
  const buyRx = /\b(buy|add to cart|add to bag|order now|purchase|checkout|check out|shop now|get it now|pay now|rent now|lease now|reserve)\b/i;
  const cards = new Set();
  document.querySelectorAll('[itemtype*="Product"], [class*=product i], [id*=product i], [data-product], [data-product-id]')
    .forEach(el => { if (visible(el) && txt(el).length < 3000) cards.add(el) });
  // also: smallest container holding a price AND a buy control
  document.querySelectorAll('a,button,[role=button],input[type=submit]').forEach(b => {
    if (!buyRx.test(txt(b) || b.value || '')) return;
    let p = b.parentElement;
    for (let d = 0; p && d < 6; d++, p = p.parentElement) {
      if (priceRx.test(txt(p)) && p.querySelector('img,h1,h2,h3,h4,h5,h6')) { cards.add(p); break }
    }
  });
  // drop cards that contain other cards (keep innermost)
  const arr = [...cards].filter(c => ![...cards].some(o => o !== c && c.contains(o)));
  const domProducts = arr.map((c, i) => {
    c.setAttribute('data-capture-card', String(i));
    const nameEl = c.querySelector('[itemprop=name], h1, h2, h3, h4, h5, h6, [class*=title i], [class*=name i]');
    const priceEl = c.querySelector('[itemprop=price], [class*=price i]');
    const descEl = c.querySelector('[itemprop=description], [class*=desc i], p');
    const img = c.querySelector('img');
    const buy = [...c.querySelectorAll('a,button,[role=button],input[type=submit]')].find(b => buyRx.test(txt(b) || b.value || ''))
             || c.querySelector('a[href*=checkout i], a[href*=cart i], a[href*=order i]');
    if (buy) buy.setAttribute('data-capture-buy', String(i));
    const priceText = priceEl ? txt(priceEl) : ((txt(c).match(priceRx) || [])[0] || null);
    return {
      card: i,
      name: nameEl ? txt(nameEl) : null,
      price: priceText,
      description: descEl ? txt(descEl) : null,
      image: img ? abs(img.currentSrc || img.getAttribute('src') || img.getAttribute('data-src')) : null,
      buy_label: buy ? (txt(buy) || buy.value || null) : null,
      buy_href: buy && buy.tagName === 'A' ? abs(buy.getAttribute('href')) : null,
      buy_onclick: buy ? buy.getAttribute('onclick') : null,
      buy_form_action: buy && buy.form ? abs(buy.form.getAttribute('action') || location.href) : null,
      has_buy: !!buy,
    };
  }).filter(p => p.name && (p.price || p.has_buy));

  // globals that betray chat/booking widgets
  const globals = ['Intercom','drift','Tawk_API','$crisp','zE','LiveChatWidget','tidioChatApi','HubSpotConversations',
                   'FB','fbq','gtag','dataLayer','ga','_hsq','Calendly','olark','fcWidget','smartsupp','clarity','hj','ttq','snaptr','pintrk','lintrk']
    .filter(g => typeof window[g] !== 'undefined');
  const customEls = [...new Set([...document.querySelectorAll('*')].map(e => e.tagName.toLowerCase()).filter(t => t.includes('-')))];

  return {
    title: document.title,
    meta: {
      description: (document.querySelector('meta[name=description]') || {}).content || null,
      canonical: (document.querySelector('link[rel=canonical]') || {}).href || null,
      og_title: (document.querySelector('meta[property="og:title"]') || {}).content || null,
      lang: document.documentElement.lang || null,
    },
    headings, blocks, buttons, links,
    assets: { image: [...assets.image].filter(Boolean), video: [...assets.video].filter(Boolean), font: [...assets.font].filter(Boolean) },
    forms, looseForm, iframes, scripts, ldProducts: ld, domProducts, globals, customEls,
  };
}
"""

AUTOSCROLL_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let last = -1;
  for (let i = 0; i < 60; i++) {
    window.scrollBy(0, Math.max(400, window.innerHeight * 0.8));
    await sleep(150);
    const h = document.documentElement.scrollHeight;
    if (window.scrollY + window.innerHeight >= h - 2) { if (h === last) break; last = h; await sleep(400); }
  }
  window.scrollTo(0, 0);
  await sleep(300);
}
"""


# --------------------------------------------------------------------------- capture

class Capture:
    def __init__(self, start_url, out: Path, max_pages, timeout_ms, extra_hosts, headed):
        self.start = normalize_url(start_url)
        self.host = norm_host(urlparse(self.start).netloc)
        self.allowed_hosts = {self.host, *(norm_host(h) for h in extra_hosts)}
        self.out = out
        self.max_pages = max_pages
        self.timeout = timeout_ms
        self.headed = headed
        for d in ("screenshots", "html", "content", "assets"):
            (out / d).mkdir(parents=True, exist_ok=True)
        self.assets = AssetStore(out / "assets")
        self.queue = [self.start]
        self.queued = {self.start}
        self.pages = OrderedDict()         # url -> record
        self.slugs = {}
        self.failures = []                 # (where, url, reason)
        self.bad_responses = OrderedDict() # url -> (status, page)
        self.request_failures = OrderedDict()
        self.console_errors = []
        self.third_party_requests = defaultdict(set)  # host -> pages
        self.redirected = {}
        self.overflow = []                 # (url, view, content width, viewport width)

    def internal(self, url):
        return norm_host(urlparse(url).netloc) in self.allowed_hosts

    def enqueue(self, url):
        u = normalize_url(url) if url else None
        if not u or not self.internal(u) or NON_PAGE_EXT.search(urlparse(u).path):
            return
        if re.search(r"/(wp-admin|wp-login|cdn-cgi|logout|signout)\b", u):
            return
        if u not in self.queued and len(self.queued) < self.max_pages:
            self.queued.add(u)
            self.queue.append(u)

    def slug_for(self, url):
        s = slugify(url)
        base, n = s, 2
        while s in self.slugs.values() and self.slugs.get(url) != s:
            s = f"{base}-{n}"; n += 1
        self.slugs[url] = s
        return s

    # ---------- network listeners
    def attach(self, page, label):
        current = {"url": None}

        async def on_response(resp):
            try:
                url = resp.url
                if url.startswith("data:"):
                    return
                status = resp.status
                req = resp.request
                if status >= 400:
                    self.bad_responses.setdefault(url, (status, current["url"] or "?"))
                host = norm_host(urlparse(url).netloc)
                if host and host not in self.allowed_hosts:
                    self.third_party_requests[host].add(current["url"] or "?")
                ct = resp.headers.get("content-type", "")
                kind = asset_kind(url, req.resource_type, ct)
                if not kind or status >= 300 or self.assets.has(url):
                    return
                if kind == "video" and status == 206:      # partial range — fetch whole file later
                    self.assets.want(url, kind)
                    return
                try:
                    body = await resp.body()
                except Exception:
                    self.assets.want(url, kind)
                    return
                self.assets.save(url, body, kind, ct)
            except Exception as e:  # never let a listener kill the crawl
                self.failures.append(("listener", resp.url, repr(e)))

        def on_request_failed(req):
            err = req.failure or "failed"
            if "ERR_ABORTED" in err and req.resource_type in ("media", "image"):
                self.assets.want(req.url, asset_kind(req.url, req.resource_type) or "image")
                return
            if not req.url.startswith("data:"):
                self.request_failures.setdefault(req.url, (err, current["url"] or "?"))

        def on_console(msg):
            if msg.type == "error":
                self.console_errors.append((current["url"] or "?", label, msg.text[:300]))

        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        page.on("requestfailed", on_request_failed)
        page.on("console", on_console)
        return current

    async def goto(self, page, url):
        """Navigate and wait for network idle; fall back gracefully on chatty pages."""
        resp = None
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=self.timeout)
        except PWTimeout:
            try:
                resp = await page.goto(url, wait_until="load", timeout=self.timeout)
                self.failures.append(("network-idle", url, "network never went idle; captured after 'load' + 5s"))
                await page.wait_for_timeout(5000)
            except Exception as e:
                raise e
        try:
            await page.evaluate(AUTOSCROLL_JS)                 # trigger lazy-loaded images/sections
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        await page.wait_for_timeout(500)
        return resp

    async def shoot(self, page, path, width):
        try:
            dims = await page.evaluate(
                "() => ({w: Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0),"
                " h: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)})")
            if dims["w"] > width + 1:
                self.overflow.append((page.url, path.stem.rsplit("-", 1)[-1], dims["w"], width))
            await page.screenshot(path=str(path), full_page=True, timeout=self.timeout, animations="disabled",
                                  clip={"x": 0, "y": 0, "width": width, "height": max(dims["h"], 1)})
        except Exception as e:
            self.failures.append(("screenshot", str(path.name), repr(e)[:200]))

    async def capture_page(self, dpage, mpage, url, dstate, mstate):
        dstate["url"] = url
        try:
            resp = await self.goto(dpage, url)
        except Exception as e:
            self.failures.append(("page", url, f"desktop load failed: {str(e).splitlines()[0][:200]}"))
            return
        status = resp.status if resp else None
        final = normalize_url(dpage.url) or url
        if status and status >= 400:
            self.failures.append(("page", url, f"HTTP {status}"))
        if final != url:
            self.redirected[url] = final
            if not self.internal(final):
                self.failures.append(("page", url, f"redirects off-site to {final}"))
                return
            if final in self.pages:
                return
            self.queued.add(final)
        slug = self.slug_for(final)
        log(f"  [{len(self.pages)+1:>3}] {final}  ->  {slug}")

        data = await dpage.evaluate(EXTRACT_JS)
        html = await dpage.content()
        (self.out / "html" / f"{slug}.html").write_text(html, encoding="utf-8")
        await self.shoot(dpage, self.out / "screenshots" / f"{slug}-desktop.png", DESKTOP["width"])

        # mobile pass (fresh mobile context so responsive JS + mobile-only assets load)
        mstate["url"] = final
        try:
            await self.goto(mpage, final)
            await self.shoot(mpage, self.out / "screenshots" / f"{slug}-mobile.png", MOBILE["width"])
            try:
                mdata = await mpage.evaluate(EXTRACT_JS)
                for k in ("image", "video", "font"):
                    data["assets"][k] = list(dict.fromkeys(data["assets"][k] + mdata["assets"][k]))
                for l in mdata["links"]:
                    if l.get("href"):
                        self.enqueue(l["href"])
            except Exception:
                pass
        except Exception as e:
            self.failures.append(("page", final, f"mobile load failed: {str(e).splitlines()[0][:200]}"))

        for kind in ("image", "video", "font"):
            for a in data["assets"][kind]:
                if a and not a.startswith("data:"):
                    self.assets.want(a, kind)
        for l in data["links"]:
            if l.get("href"):
                self.enqueue(l["href"])

        self.pages[final] = {"url": final, "slug": slug, "status": status, **data}
        self.write_markdown(final, slug, status, data)

    def write_markdown(self, url, slug, status, d):
        L = [f"# {d['title'] or slug}", "", f"- **URL:** {url}", f"- **HTTP status:** {status}"]
        m = d["meta"]
        if m.get("description"): L.append(f"- **Meta description:** {m['description']}")
        if m.get("canonical"): L.append(f"- **Canonical:** {m['canonical']}")
        L += ["", "## Headings", ""]
        L += [f"{'  ' * (h['level'] - 1)}- H{h['level']}: {h['text']}" for h in d["headings"]] or ["_none_"]
        L += ["", "## Body text", ""]
        for b in d["blocks"]:
            t = b["tag"]
            if t[0] == "h" and t[1:].isdigit():
                L.append(f"{'#' * min(int(t[1]) + 2, 6)} {b['text']}")
            elif t == "li":
                L.append(f"- {b['text']}")
            elif t == "blockquote":
                L.append(f"> {b['text']}")
            else:
                L.append(b["text"])
            L.append("")
        L += ["## Buttons", ""]
        seen = set()
        for b in d["buttons"]:
            key = (b["label"], b["href"])
            if key in seen: continue
            seen.add(key)
            L.append(f"- **{b['label']}**" + (f" → {b['href']}" if b["href"] else f" ({b['type']})"))
        if not d["buttons"]: L.append("_none_")
        L += ["", "## Links", "", "| Text | Target | Type |", "|---|---|---|"]
        seen = set()
        for l in d["links"]:
            href = l.get("href") or l.get("raw") or ""
            key = (l["text"], href)
            if key in seen: continue
            seen.add(key)
            typ = "internal" if href.startswith("http") and self.internal(href) else (
                  "external" if href.startswith("http") else href.split(":")[0] if ":" in href else "other")
            if l.get("scripted"): typ += " (scripted)"
            if l.get("target") == "_blank": typ += ", new tab"
            text = (l["text"] or "").replace("|", "\\|")[:120]
            L.append(f"| {text} | {href.replace('|', '%7C')} | {typ} |")
        (self.out / "content" / f"{slug}.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---------- assets the browser didn't hand us directly
    async def download_missing(self, request_ctx):
        todo = [(u, k) for u, k in self.assets.wanted.items() if not self.assets.has(u)]
        if todo:
            log(f"\nDownloading {len(todo)} remaining assets…")
        for url, kind in todo:
            try:
                r = await request_ctx.get(url, timeout=120000, max_redirects=5)
                if r.ok:
                    body = await r.body()
                    ct = r.headers.get("content-type", "")
                    if "text/html" in ct and kind != "video":
                        self.assets.failed[url] = "server returned HTML, not an asset"
                        continue
                    self.assets.save(url, body, asset_kind(url, None, ct) or kind, ct)
                else:
                    self.assets.failed[url] = f"HTTP {r.status}"
            except Exception as e:
                self.assets.failed[url] = str(e).splitlines()[0][:200]

    # ---------- products
    async def resolve_checkout(self, browser, page_url, card_idx):
        """Click a buy control that has no plain href and record where it goes. Stops there."""
        ctx = await browser.new_context(viewport=DESKTOP, user_agent=DESKTOP_UA)
        page = await ctx.new_page()
        seen_reqs = []
        page.on("request", lambda r: seen_reqs.append(r.url) if r.is_navigation_request() or r.resource_type in ("xhr", "fetch") else None)
        try:
            await self.goto(page, page_url)
            await page.evaluate(EXTRACT_JS)                          # re-tags cards + buy buttons
            btn = page.locator(f'[data-capture-buy="{card_idx}"]').first
            if not await btn.count():
                return None, "buy control not found on re-render"
            start = page.url
            popup_url = None
            try:
                async with ctx.expect_page(timeout=8000) as pinfo:
                    await btn.click(timeout=5000)
                pop = await pinfo.value
                await pop.wait_for_load_state("domcontentloaded", timeout=15000)
                popup_url = pop.url
            except PWTimeout:
                pass
            if popup_url:
                return popup_url, "opened in new tab"
            try:
                await page.wait_for_url(lambda u: u != start, timeout=8000)
            except PWTimeout:
                pass
            if page.url != start:
                return page.url, "navigated"
            hits = [u for u in seen_reqs if CHECKOUT_HINT.search(u) and u != start]
            if hits:
                return hits[-1], "request fired on click (no navigation)"
            modal = await page.evaluate("""() => { const d=[...document.querySelectorAll('[role=dialog],.modal,[class*=modal i],[class*=drawer i],[class*=cart i]')].find(e=>e.offsetParent); return d ? (d.innerText||'').slice(0,200) : null }""")
            return None, ("opened on-page cart/modal: " + modal.replace("\n", " ")) if modal else "click did not navigate"
        except Exception as e:
            return None, f"click failed: {str(e).splitlines()[0][:150]}"
        finally:
            await ctx.close()

    async def collect_products(self, browser):
        products, seen = [], set()
        for url, rec in self.pages.items():
            for p in rec.get("ldProducts", []):
                offers = p.get("offers") or {}
                if isinstance(offers, list): offers = offers[0] if offers else {}
                img = p.get("image")
                if isinstance(img, list): img = img[0] if img else None
                if isinstance(img, dict): img = img.get("url")
                name = p.get("name")
                key = (name, url)
                if not name or key in seen: continue
                seen.add(key)
                price = offers.get("price") or offers.get("lowPrice")
                cur = offers.get("priceCurrency")
                products.append({
                    "name": name,
                    "price": f"{price} {cur}".strip() if price else None,
                    "description": p.get("description"),
                    "image_path": self.assets.path_for(urljoin(url, img)) if img else None,
                    "image_url": urljoin(url, img) if img else None,
                    "checkout_url": offers.get("url") and urljoin(url, offers["url"]),
                    "checkout_resolution": "schema.org offer URL" if offers.get("url") else None,
                    "source_page": url, "source": "json-ld",
                })
            for p in rec.get("domProducts", []):
                key = (p["name"], url)
                if key in seen: continue
                seen.add(key)
                checkout, how = None, None
                if p["buy_href"] and not p["buy_href"].startswith("javascript") and not p["buy_href"].endswith("#"):
                    checkout, how = p["buy_href"], "button href"
                elif p["has_buy"]:
                    checkout, how = await self.resolve_checkout(browser, url, p["card"])
                    if checkout is None and p["buy_form_action"]:
                        checkout, how = p["buy_form_action"], "form action (POST target)"
                elif not p["has_buy"]:
                    how = "no buy button on card"
                img_url = p["image"]
                products.append({
                    "name": p["name"], "price": p["price"], "description": p["description"],
                    "image_path": self.assets.path_for(img_url) if img_url else None,
                    "image_url": img_url,
                    "buy_button_label": p["buy_label"],
                    "checkout_url": checkout, "checkout_resolution": how,
                    "source_page": url, "source": "page markup",
                })
        # follow product checkout redirects to their final URL (GET only, nothing submitted)
        req = browser.contexts[0].request if browser.contexts else None
        for p in products:
            u = p.get("checkout_url")
            if req and u and u.startswith("http"):
                try:
                    r = await req.get(u, max_redirects=10, timeout=20000)
                    if r.url != u:
                        p["checkout_url_final"] = r.url
                    p["checkout_http_status"] = r.status
                except Exception as e:
                    p["checkout_http_status"] = f"error: {str(e).splitlines()[0][:100]}"
        return products

    # ---------- integrations
    def classify(self, s, table):
        s = (s or "").lower()
        return sorted({label for sig, label in table.items() if sig in s})

    def write_integrations(self):
        L = ["# Integrations", "", f"Site: {self.start}  ", f"Captured: {time.strftime('%Y-%m-%d %H:%M')}  ",
             f"Pages scanned: {len(self.pages)}", ""]

        # Forms
        L += ["## Forms", ""]
        form_sigs = {}
        for url, rec in self.pages.items():
            fs = list(rec["forms"]) + ([rec["looseForm"]] if rec.get("looseForm") else [])
            for f in fs:
                sig = json.dumps([f["action"], [(x["name"], x["type"]) for x in f["fields"]]])
                form_sigs.setdefault(sig, {"form": f, "pages": []})["pages"].append(url)
        if not form_sigs:
            L.append("_No native `<form>` elements or standalone inputs found (forms may live inside iframes — see Embeds)._")
        for i, (sig, v) in enumerate(form_sigs.items(), 1):
            f = v["form"]
            L += [f"### Form {i}" + (f" — `#{f['id']}`" if f.get("id") else ""), "",
                  f"- **Submits to:** {f['action'] or '(same page / handled by JavaScript)'}",
                  f"- **Method:** {f['method']}",
                  f"- **Submit button:** {', '.join(f['submit']) or '—'}",
                  f"- **Found on:** " + ", ".join(v["pages"]), ""]
            if f["fields"]:
                L += ["| Label | Name | Type | Required | Options |", "|---|---|---|---|---|"]
                for x in f["fields"]:
                    opts = ", ".join(x.get("options") or [])[:120]
                    L.append(f"| {x['label'] or x['placeholder'] or '—'} | {x['name'] or x['id'] or '—'} | "
                             f"{x['type'] or x['tag']} | {'yes' if x['required'] else ''} | {opts} |")
            if f.get("hidden"):
                L.append(f"\nHidden fields: `{', '.join(f['hidden'])}`")
            L.append("")

        # Iframes / embeds
        iframes = defaultdict(set)
        for url, rec in self.pages.items():
            for fr in rec["iframes"]:
                if fr["src"]: iframes[fr["src"]].add(url)
        all_scripts = defaultdict(set)
        inline_hits = defaultdict(set)
        for url, rec in self.pages.items():
            for s in rec["scripts"]:
                if s["src"]: all_scripts[s["src"]].add(url)
                elif s["inline"]:
                    for lbl in self.classify(s["inline"], {**CHAT_SIGNS, **BOOKING_SIGNS}):
                        inline_hits[lbl].add(url)

        L += ["## Chat widgets", ""]
        chat = defaultdict(set)
        for src, pgs in {**all_scripts, **iframes}.items():
            for lbl in self.classify(src, CHAT_SIGNS): chat[(lbl, src)] |= pgs
        for host, pgs in self.third_party_requests.items():
            for lbl in self.classify(host, CHAT_SIGNS): chat[(lbl, host)] |= pgs
        for url, rec in self.pages.items():
            for g in rec["globals"]:
                lbl = {"Intercom": "Intercom", "drift": "Drift", "Tawk_API": "Tawk.to", "$crisp": "Crisp",
                       "zE": "Zendesk", "LiveChatWidget": "LiveChat", "tidioChatApi": "Tidio",
                       "HubSpotConversations": "HubSpot chat", "olark": "Olark", "fcWidget": "Freshchat"}.get(g)
                if lbl: chat[(lbl, f"window.{g}")].add(url)
            for el in rec["customEls"]:
                if "chat" in el: chat[("Chat widget (custom element)", f"<{el}>")].add(url)
        for lbl, pgs in inline_hits.items():
            if lbl in CHAT_SIGNS.values(): chat[(lbl, "inline script")] |= pgs
        L += [f"- **{lbl}** — `{src}` (on {len(pgs)} page{'s' * (len(pgs) != 1)})" for (lbl, src), pgs in sorted(chat.items())] \
             or ["_None detected._"]

        L += ["", "## Booking / calendar embeds", ""]
        book = defaultdict(set)
        for src, pgs in {**iframes, **all_scripts}.items():
            for lbl in self.classify(src, BOOKING_SIGNS): book[(lbl, src)] |= pgs
        L += [f"- **{lbl}** — {src}  \n  on: {', '.join(sorted(pgs))}" for (lbl, src), pgs in sorted(book.items())] \
             or ["_None detected._"]

        L += ["", "## All iframes / embeds", ""]
        if iframes:
            L += ["| Embed | Kind | Pages |", "|---|---|---|"]
            for src, pgs in sorted(iframes.items()):
                kind = ", ".join(self.classify(src, {**FORM_EMBED_SIGNS, **BOOKING_SIGNS, **CHAT_SIGNS,
                       "youtube": "YouTube", "vimeo": "Vimeo", "google.com/maps": "Google Maps",
                       "maps.google": "Google Maps", "recaptcha": "reCAPTCHA", "facebook.com": "Facebook"})) or "—"
                L.append(f"| {src} | {kind} | {len(pgs)} |")
        else:
            L.append("_None._")

        L += ["", "## Third-party scripts", ""]
        by_host = defaultdict(lambda: {"srcs": set(), "pages": set()})
        for src, pgs in all_scripts.items():
            h = norm_host(urlparse(src).netloc)
            if h and h not in self.allowed_hosts:
                by_host[h]["srcs"].add(src); by_host[h]["pages"] |= pgs
        if by_host:
            L += ["| Host | Script(s) | Pages |", "|---|---|---|"]
            for h, v in sorted(by_host.items()):
                L.append(f"| {h} | " + "<br>".join(sorted(v["srcs"])[:6]) + f" | {len(v['pages'])} |")
        else:
            L.append("_None._")

        tracking = sorted({g for r in self.pages.values() for g in r["globals"]
                           if g in ("gtag", "dataLayer", "ga", "fbq", "_hsq", "clarity", "hj", "ttq", "snaptr", "pintrk", "lintrk")})
        L += ["", "## Analytics / tracking globals present", "",
              ", ".join(f"`{t}`" for t in tracking) if tracking else "_None detected._"]

        L += ["", "## Every third-party host contacted at runtime", "",
              "Includes requests made by scripts after load (APIs, pixels, CDNs).", ""]
        L += [f"- {h} ({len(p)} page{'s' * (len(p) != 1)})" for h, p in sorted(self.third_party_requests.items())] or ["_None._"]
        (self.out / "integrations.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---------- main
    async def run(self):
        t0 = time.time()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not self.headed)
            dctx = await browser.new_context(viewport=DESKTOP, user_agent=DESKTOP_UA, ignore_https_errors=True)
            # is_mobile stays False so the layout is always exactly 390px wide, even on pages
            # without a viewport meta tag (Chromium would otherwise render them at 980px).
            mctx = await browser.new_context(viewport=MOBILE, user_agent=MOBILE_UA, is_mobile=False,
                                             has_touch=True, device_scale_factor=1, ignore_https_errors=True)
            dpage, mpage = await dctx.new_page(), await mctx.new_page()
            dstate, mstate = self.attach(dpage, "desktop"), self.attach(mpage, "mobile")

            # seed from sitemap.xml so unlinked pages are captured too
            try:
                for sm in ("/sitemap.xml", "/sitemap_index.xml"):
                    r = await dctx.request.get(urljoin(self.start, sm), timeout=15000)
                    if r.ok and "xml" in r.headers.get("content-type", ""):
                        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", await r.text())
                        for loc in locs:
                            if loc.endswith(".xml"):
                                r2 = await dctx.request.get(loc, timeout=15000)
                                if r2.ok:
                                    for l2 in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", await r2.text()):
                                        self.enqueue(l2)
                            else:
                                self.enqueue(loc)
                        log(f"Sitemap {sm}: {len(locs)} entries")
                        break
            except Exception:
                pass

            log(f"Crawling {self.start}  (max {self.max_pages} pages)\n")
            while self.queue:
                url = self.queue.pop(0)
                if url in self.pages:
                    continue
                await self.capture_page(dpage, mpage, url, dstate, mstate)

            await asyncio.sleep(1)  # let pending response handlers finish
            await self.download_missing(dctx.request)
            self.assets.write_manifest()

            log("\nLooking for products…")
            products = await self.collect_products(browser)
            (self.out / "products.json").write_text(json.dumps(products, indent=2, ensure_ascii=False), encoding="utf-8")

            self.write_integrations()
            (self.out / "pages.json").write_text(json.dumps(
                [{"url": u, "slug": r["slug"], "status": r["status"], "title": r["title"], **r["meta"]}
                 for u, r in self.pages.items()], indent=2, ensure_ascii=False), encoding="utf-8")
            await browser.close()

        self.summary(products, time.time() - t0)

    def summary(self, products, secs):
        c = self.assets.counts
        L = ["", "=" * 64, "CAPTURE SUMMARY", "=" * 64,
             f"Site:         {self.start}",
             f"Output:       {self.out.resolve()}",
             f"Time:         {secs:.0f}s",
             f"Pages:        {len(self.pages)}",
             f"Products:     {len(products)}"
             + (f"  ({sum(1 for p in products if p.get('checkout_url'))} with a checkout URL)" if products else ""),
             f"Assets:       {sum(c.values())} files  (images {c['image']}, fonts {c['font']}, videos {c['video']})",
             f"Screenshots:  {len(list((self.out / 'screenshots').glob('*.png')))}", ""]
        page_fail = [f for f in self.failures if f[0] in ("page", "screenshot")]
        idle = [f for f in self.failures if f[0] == "network-idle"]
        L.append(f"FAILED TO LOAD — pages ({len(page_fail)}):")
        L += [f"  - {u}: {r}" for _, u, r in page_fail] or ["  none"]
        if idle:
            L.append(f"\nPages that never reached network idle ({len(idle)}) — captured anyway:")
            L += [f"  - {u}" for _, u, _ in idle]
        if self.overflow:
            L.append(f"\nLayout warning — content wider than the screen ({len(self.overflow)}):")
            L += [f"  - {u} [{v}]: {w}px content in a {vw}px viewport (screenshot clipped to {vw}px)" for u, v, w, vw in self.overflow]
        L.append(f"\nFAILED TO LOAD — assets ({len(self.assets.failed)}):")
        L += [f"  - {u}: {r}" for u, r in self.assets.failed.items()] or ["  none"]
        L.append(f"\nHTTP errors seen in the browser ({len(self.bad_responses)}):")
        L += [f"  - {s}  {u}  (on {p})" for u, (s, p) in self.bad_responses.items()] or ["  none"]
        rf = {u: v for u, v in self.request_failures.items() if u not in self.bad_responses}
        L.append(f"\nRequests that failed outright ({len(rf)}):")
        L += [f"  - {e}  {u}  (on {p})" for u, (e, p) in rf.items()] or ["  none"]
        uniq_console = list(dict.fromkeys((p, m) for p, _, m in self.console_errors))
        L.append(f"\nJavaScript console errors ({len(uniq_console)}):")
        L += [f"  - {p}: {m}" for p, m in uniq_console[:40]] or ["  none"]
        if len(uniq_console) > 40:
            L.append(f"  … {len(uniq_console) - 40} more")
        text = "\n".join(L)
        log(text)
        (self.out / "summary.txt").write_text(text + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Capture every page, asset, product and integration of a site.")
    ap.add_argument("url", nargs="?", default="https://peacecountryinstallations.ca")
    ap.add_argument("--out", default="capture", help="output folder (default: ./capture)")
    ap.add_argument("--max-pages", type=int, default=500)
    ap.add_argument("--timeout", type=int, default=60, help="per-page timeout in seconds (default 60)")
    ap.add_argument("--also-host", action="append", default=[],
                    help="extra hostname to treat as internal (e.g. a shop subdomain); repeatable")
    ap.add_argument("--headed", action="store_true", help="show the browser while it works")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cap = Capture(a.url, Path(a.out), a.max_pages, a.timeout * 1000, a.also_host, a.headed)
    asyncio.run(cap.run())


if __name__ == "__main__":
    main()
