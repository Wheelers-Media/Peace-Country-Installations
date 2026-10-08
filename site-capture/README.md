# Site capture

Crawls every internal page of a site in Chromium (Playwright), waiting for the network to go idle so JavaScript-rendered content is there, then saves everything to `..\capture\`.

## Run it

Double-click **run-capture.bat**. The first run installs Playwright and Chromium into a private `.venv` folder (needs Python 3.9+). After that it starts straight away.

Other site: `run-capture.bat https://example.ca`

Advanced (from a terminal in this folder):

```
.venv\Scripts\python capture_site.py https://peacecountryinstallations.ca --out ..\capture
    --max-pages 500      stop after N pages
    --timeout 60         seconds per page before giving up
    --also-host shop.example.ca   treat another subdomain as internal (repeatable)
    --headed             watch the browser work
```

## What you get

| Path | Contents |
|---|---|
| `screenshots/<slug>-desktop.png` | full page, 1440px wide |
| `screenshots/<slug>-mobile.png` | full page, 390px wide (mobile user agent + touch) |
| `html/<slug>.html` | rendered DOM after scripts ran |
| `content/<slug>.md` | meta, heading outline, body text in order, buttons, every link (internal / external / tel / mailto, scripted links flagged) |
| `assets/` | every image, font and video under its original filename (a `-2` suffix only when two different files share a name; identical files are stored once). `_manifest.json` maps each source URL to its file |
| `products.json` | name, price, description, `image_path`, `checkout_url`, how the checkout URL was found, final URL after redirects |
| `integrations.md` | forms (fields, labels, required, where they submit), chat widgets, booking/calendar embeds, all iframes, third-party scripts, tracking globals, every third-party host contacted |
| `pages.json` | every page: URL, slug, HTTP status, title, meta description, canonical |
| `summary.txt` | counts plus everything that failed |

## How it works

- **Finding pages:** starts at the home page, reads `sitemap.xml` if there is one, and follows every same-domain link, including links hidden in `onclick` / `data-href` (common in page builders). `www.` and the bare domain count as the same site. Tracking parameters (`utm_*`, `fbclid`, …) and `#anchors` are stripped so pages aren't captured twice.
- **Waiting for content:** `networkidle`, then scrolls the whole page to trigger lazy-loaded images and sections, waits for idle again and for fonts. If a page never goes idle (live chat polling, for example) it is captured after `load` + 5 s and listed in the summary.
- **Assets:** saved straight from the browser's network traffic on both the desktop and mobile passes, plus anything referenced in the DOM (`srcset`, `data-src`, CSS backgrounds, `@font-face`, video posters, favicons, og:image) that wasn't requested yet.
- **Products:** schema.org Product data first, then product cards in the page (a name + a price or a buy button). If the buy button is a plain link, that link is the checkout URL. If it's a scripted button, the tool clicks it in a separate throwaway browser and records the page or tab it opens, or the checkout request it fires. It never fills in or submits anything past that click.
- **Summary:** pages that failed or returned errors, pages wider than the screen (a mobile layout bug), assets that couldn't be downloaded, every 4xx/5xx response, failed requests and JavaScript console errors.
