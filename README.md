# Peace Country Installations

Astro static site built from `capture/` (copy, products, images). Deploys to Vercel with no config: import the repo and Vercel detects Astro. The quote form posts to `api/quote.js`, a Vercel Function.

```bash
npm install
npm run dev      # http://localhost:4321
npm run build    # static output in dist/
npm test         # quote form validation tests
```

## Quote form → Google Calendar

Each submission becomes an all-day event (America/Edmonton date) on the business calendar, with every form field in the event description.

One-time setup:

1. In Google Cloud, enable the **Google Calendar API**, then create a **service account** with a JSON key.
2. In Google Calendar, share the business calendar with the service account email and set its permission to **Make changes to events**.
3. Add these environment variables in Vercel (Project → Settings → Environment Variables):

| Variable | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_EMAIL` | `client_email` from the JSON key |
| `GOOGLE_PRIVATE_KEY` | `private_key` from the JSON key. Literal `\n` is fine |
| `GOOGLE_CALENDAR_ID` | Calendar settings → "Integrate calendar" → Calendar ID |
