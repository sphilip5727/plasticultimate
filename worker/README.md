# Plastic Ultimate — audit Worker

A tiny **free** Cloudflare Worker that powers the marketing audit on `marketing.html` → `audit.html`.
It scans a website using Google PageSpeed Insights (mobile + desktop) plus a live fetch of the
page's HTML, and returns scored results as JSON. **Stateless — no database, no keys, no billing.**

## Deploy (one time, ~2 minutes)

You need a (free) Cloudflare account. From this `worker/` folder:

```bash
npx wrangler login      # opens your browser — pick the account for this project
npx wrangler deploy     # prints your URL, e.g. https://plastic-audit.<you>.workers.dev
```

Then open `../audit.html`, find the line near the top of the `<script>`:

```js
var WORKER_URL = 'https://plastic-audit.YOUR-SUBDOMAIN.workers.dev/audit';
```

…and replace it with your deployed URL **(keep the `/audit` on the end)**. Commit + reload — done.

## Test it locally first (optional)

```bash
npx wrangler dev        # serves http://localhost:8787
```

Temporarily set `WORKER_URL` in `audit.html` to `http://localhost:8787/audit`, then run an audit
from `marketing.html`. Change it back to your real Worker URL before deploying the site.

Quick check from the terminal:

```bash
curl "http://localhost:8787/audit?url=https://example.com"
```

## Costs

Free tier = **100,000 requests/day**. Each audit is ~1 request. There is nothing here that bills.
If you ever hit PageSpeed rate limits, add a free API key (no billing required):

```bash
npx wrangler secret put PSI_KEY
```

⚠️ Keep this Worker stateless (no KV / D1 / Queues / cron) to stay on the free plan.

## What it scores (and what it can't, for free)

**Real, automated:** Technical health (Core Web Vitals, speed, HTTPS, schema, crawlability),
Mobile, UX/accessibility, on-page SEO, CTAs, social presence, brand basics.

**Manual review (needs account access / paid data):** Conversion analytics, Paid ads, Content &
email, Lead handling, GA4, keyword rankings/backlinks, review data. These show in the report but
are marked "Manual review" rather than guessed.
