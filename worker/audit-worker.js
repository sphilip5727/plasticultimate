/**
 * Plastic Ultimate — free marketing-audit Worker.
 *
 * Stateless. No bindings, no secrets, no storage → stays on the Cloudflare FREE plan.
 * ⚠️  Do NOT add KV / D1 / Queues or enable "Workers Paid" unless you intend to incur cost.
 *
 * GET /audit?url=<site>
 *   →  { ok:true,  finalUrl, checks:{ "<id>": {status,score,note,value} }, generatedAt }
 *   →  { ok:false, reason, message }
 *
 * Data sources (both free, no API key required):
 *   1. Google PageSpeed Insights (mobile + desktop)  → Core Web Vitals, perf, a11y, SEO
 *   2. Fetching the page's own HTML + robots.txt + sitemap.xml, parsed with HTMLRewriter
 *
 * A free PSI key is optional; if you ever add one: `wrangler secret put PSI_KEY`.
 */

const PSI_ENDPOINT = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed';
const UA = 'Mozilla/5.0 (compatible; PlasticAuditBot/1.0)';
const CORS = {
  'Access-Control-Allow-Origin': '*', // read-only public GET; tighten to your site origin later if you like
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });

    const url = new URL(request.url);
    if (url.pathname !== '/audit' && url.pathname !== '/') {
      return json({ ok: false, reason: 'not_found' }, 404);
    }

    const target = normaliseTarget(url.searchParams.get('url'));
    if (!target) {
      return json({ ok: false, reason: 'bad_url', message: 'Provide a valid ?url=' }, 400);
    }

    try {
      return json(await runAudit(target, env));
    } catch (err) {
      return json({ ok: false, reason: 'error', message: String((err && err.message) || err) });
    }
  },
};

/* ------------------------------------------------------------------ helpers */

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS },
  });
}

function normaliseTarget(raw) {
  if (!raw) return null;
  raw = raw.trim();
  if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
  let u;
  try { u = new URL(raw); } catch { return null; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
  const host = u.hostname;
  if (!host.includes('.')) return null;
  // SSRF hygiene — refuse localhost / private ranges
  if (/^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|::1$)/i.test(host)) return null;
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(host)) return null;
  return u.toString();
}

async function fetchText(url, ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch(url, {
      headers: { 'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,*/*' },
      redirect: 'follow',
      signal: c.signal,
    });
    const body = (await r.text()).slice(0, 2_000_000); // cap 2MB
    return { ok: r.ok, status: r.status, finalUrl: r.url, body };
  } finally {
    clearTimeout(t);
  }
}

async function fetchJson(url, ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  try {
    const r = await fetch(url, { signal: c.signal });
    if (!r.ok) { const e = new Error('psi_' + r.status); e.status = r.status; throw e; }
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

/* -------------------------------------------------------------------- audit */

async function runAudit(target, env) {
  const key = env && env.PSI_KEY ? '&key=' + env.PSI_KEY : '';
  // Only request categories we actually score (dropping best-practices trims Lighthouse time).
  const psi = (strategy) =>
    `${PSI_ENDPOINT}?url=${encodeURIComponent(target)}&strategy=${strategy}` +
    `&category=performance&category=accessibility&category=seo${key}`;

  let robotsUrl, sitemapUrl;
  try {
    robotsUrl = new URL('/robots.txt', target).toString();
    sitemapUrl = new URL('/sitemap.xml', target).toString();
  } catch { /* ignore */ }

  const [mobileR, desktopR, pageR, robotsR, sitemapR] = await Promise.allSettled([
    fetchJson(psi('mobile'), 58000),
    fetchJson(psi('desktop'), 58000),
    fetchText(target, 15000),
    robotsUrl ? fetchText(robotsUrl, 8000) : Promise.reject(),
    sitemapUrl ? fetchText(sitemapUrl, 8000) : Promise.reject(),
  ]);

  const mobile = mobileR.status === 'fulfilled' ? mobileR.value : null;
  const desktop = desktopR.status === 'fulfilled' ? desktopR.value : null;
  const page = pageR.status === 'fulfilled' ? pageR.value : null;

  if (!mobile && !desktop && !page) {
    return { ok: false, reason: 'unreachable', message: 'Could not reach the site or run PageSpeed. Check the URL is public and correct.' };
  }

  const finalUrl = (page && page.finalUrl) || (mobile && mobile.id) || target;
  const dom = page && page.body ? await extractHtml(page.body, finalUrl) : null;
  const robotsOk = robotsR.status === 'fulfilled' && robotsR.value.ok;
  const sitemapOk = sitemapR.status === 'fulfilled' && sitemapR.value.ok;

  const checks = buildChecks({ mobile, desktop, dom, finalUrl, robotsOk, sitemapOk });
  return { ok: true, finalUrl, checks, generatedAt: new Date().toISOString() };
}

/* --------------------------------------------------------- HTML extraction */

async function extractHtml(html, finalUrl) {
  let base;
  try { base = new URL(finalUrl); } catch { base = new URL('https://example.com'); }

  const d = {
    title: '', metaDesc: '', hasViewport: false, robotsMeta: '', hasCanonical: false, hasFavicon: false,
    h1Count: 0, h1Text: '', headingCount: 0,
    imgCount: 0, imgAlt: 0,
    aCount: 0, internal: 0, external: 0, navLinks: 0,
    jsonLd: new Set(), tel: 0, mailto: 0, social: new Set(),
    forms: 0, inputs: 0, inputTypes: new Set(),
    ctaText: '', insecure: 0,
    reviewPlatforms: new Set(), aggRating: null,
    _titleDone: false, _ld: false, _ldBuf: '',
  };

  const rw = new HTMLRewriter()
    .on('title', { text(t) { if (!d._titleDone) { d.title += t.text; if (t.lastInTextNode) d._titleDone = true; } } })
    .on('meta', { element(e) {
      const n = (e.getAttribute('name') || '').toLowerCase();
      const c = e.getAttribute('content') || '';
      if (n === 'description') d.metaDesc = c;
      if (n === 'viewport') d.hasViewport = true;
      if (n === 'robots') d.robotsMeta = c.toLowerCase();
    } })
    .on('link', { element(e) {
      const rel = (e.getAttribute('rel') || '').toLowerCase();
      const href = e.getAttribute('href') || '';
      if (rel.includes('canonical')) d.hasCanonical = true;
      if (rel.includes('icon')) d.hasFavicon = true;
      if (href.startsWith('http://')) d.insecure++;
    } })
    .on('h1', { element() { d.h1Count++; d.headingCount++; }, text(t) { if (d.h1Count <= 1 && d.h1Text.length < 200) d.h1Text += t.text; } })
    .on('h2', { element() { d.headingCount++; } })
    .on('h3', { element() { d.headingCount++; } })
    .on('img', { element(e) {
      d.imgCount++;
      const alt = e.getAttribute('alt');
      if (alt !== null && alt.trim() !== '') d.imgAlt++;
      if ((e.getAttribute('src') || '').startsWith('http://')) d.insecure++;
    } })
    .on('script', { element(e) {
      const src = e.getAttribute('src') || '';
      if (src.startsWith('http://')) d.insecure++;
      const rp = reviewPlatformOf(src); if (rp) d.reviewPlatforms.add(rp); // e.g. Trustpilot / Feefo widgets
      d._ld = (e.getAttribute('type') || '').toLowerCase() === 'application/ld+json';
      if (d._ld) d._ldBuf = '';
    }, text(t) {
      if (d._ld) { d._ldBuf += t.text; if (t.lastInTextNode) { collectLd(d._ldBuf, d); d._ld = false; } }
    } })
    .on('a', { element(e) { d.aCount++; classifyLink(e.getAttribute('href') || '', base, d); }, text(t) { if (d.ctaText.length < 20000) d.ctaText += ' ' + t.text; } })
    .on('button', { text(t) { if (d.ctaText.length < 20000) d.ctaText += ' ' + t.text; } })
    .on('nav a', { element() { d.navLinks++; } })
    .on('form', { element() { d.forms++; } })
    .on('input', { element(e) {
      var ty = (e.getAttribute('type') || 'text').toLowerCase();
      if (['hidden', 'submit', 'button', 'image', 'reset'].indexOf(ty) >= 0) return; // not a fillable field
      d.inputs++; d.inputTypes.add(ty);
    } })
    .on('textarea', { element() { d.inputs++; } })
    .on('select', { element() { d.inputs++; } });

  await rw.transform(new Response(html)).arrayBuffer();
  return d;
}

function classifyLink(href, base, d) {
  const h = (href || '').trim();
  if (!h) return;
  if (h.startsWith('tel:')) { d.tel++; return; }
  if (h.startsWith('mailto:')) { d.mailto++; return; }
  if (h.startsWith('#') || h.toLowerCase().startsWith('javascript:')) return;
  let u;
  try { u = new URL(h, base); } catch { return; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return;
  const host = u.hostname.replace(/^www\./, '');
  const baseHost = base.hostname.replace(/^www\./, '');
  if (host === baseHost) d.internal++; else d.external++;
  const socials = ['instagram.com', 'facebook.com', 'fb.com', 'tiktok.com', 'youtube.com', 'youtu.be', 'twitter.com', 'x.com', 'linkedin.com', 'pinterest.com'];
  for (const s of socials) {
    if (host === s || host.endsWith('.' + s)) {
      d.social.add(s.replace('.com', '').replace('youtu.be', 'youtube').replace('fb', 'facebook'));
    }
  }
  const rp = reviewPlatformOf(u.href); if (rp) d.reviewPlatforms.add(rp); // e.g. Google Maps / Trustpilot links
}

// Which review platform (if any) a URL points at.
function reviewPlatformOf(urlStr) {
  const s = (urlStr || '').toLowerCase();
  if (!s) return null;
  if (s.includes('trustpilot.com')) return 'Trustpilot';
  if (s.includes('feefo.com')) return 'Feefo';
  if (s.includes('yotpo.com')) return 'Yotpo';
  if (s.includes('reviews.io') || s.includes('reviews.co.uk')) return 'Reviews.io';
  if (s.includes('trustindex')) return 'Google (widget)';
  if (s.includes('g.page')) return 'Google';
  if (s.includes('goo.gl/maps') || s.includes('maps.google') || (s.includes('google.') && s.includes('/maps'))) return 'Google';
  return null;
}

function collectLd(buf, d) {
  try {
    const walk = (o) => {
      if (!o || typeof o !== 'object') return;
      if (Array.isArray(o)) { o.forEach(walk); return; }
      if (o['@type']) [].concat(o['@type']).forEach((t) => d.jsonLd.add(String(t)));
      // Capture an embedded star rating (schema.org AggregateRating), wherever it appears.
      const ar = o.aggregateRating || (String(o['@type'] || '').toLowerCase() === 'aggregaterating' ? o : null);
      if (ar && !d.aggRating) {
        const rv = parseFloat(ar.ratingValue);
        const rc = parseInt(ar.reviewCount != null ? ar.reviewCount : ar.ratingCount, 10);
        if (!isNaN(rv)) d.aggRating = { rating: rv, count: isNaN(rc) ? null : rc };
      }
      Object.keys(o).forEach((k) => { if (k !== '@type' && o[k] && typeof o[k] === 'object') walk(o[k]); });
    };
    walk(JSON.parse(buf.trim()));
  } catch { /* ignore malformed JSON-LD */ }
}

/* ------------------------------------------------------------- scoring ---- */

function buildChecks({ mobile, desktop, dom, finalUrl, robotsOk, sitemapOk }) {
  const lhM = mobile && mobile.lighthouseResult;
  const lhD = desktop && desktop.lighthouseResult;

  const clamp = (n) => Math.max(0, Math.min(100, Math.round(n)));
  const cat = (lh, c) => (lh && lh.categories && lh.categories[c] && typeof lh.categories[c].score === 'number') ? Math.round(lh.categories[c].score * 100) : null;
  const aScore = (lh, id) => { const a = lh && lh.audits && lh.audits[id]; return a && typeof a.score === 'number' ? Math.round(a.score * 100) : null; };
  const aDisp = (lh, id) => { const a = lh && lh.audits && lh.audits[id]; return a && a.displayValue ? a.displayValue : null; };
  const avg = (arr) => { const v = arr.filter((x) => typeof x === 'number'); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const mk = (score, note, value) => (score == null ? null : { status: (score = clamp(score)) >= 80 ? 'pass' : score >= 50 ? 'warn' : 'fail', score, note: note || '', value: value || null });

  const checks = {};
  const set = (id, c) => { if (c) checks[id] = c; };

  const perfM = cat(lhM, 'performance');
  const perfD = cat(lhD, 'performance');
  const a11y = cat(lhM, 'accessibility');
  const seoLh = cat(lhM, 'seo');

  /* 1 — Brand & Positioning
     We can check the *mechanics* of a clear message (a real, descriptive headline + title + description),
     but NOT whether the positioning is right or on-brand — that's a human judgment. So this is capped
     below "green": a scraper should never certify brand positioning as strong. */
  {
    if (dom) {
      const h1 = dom.h1Count, h1t = dom.h1Text.trim(), t = dom.title.trim(), md = dom.metaDesc.trim();
      const words = h1t ? h1t.split(/\s+/).filter(Boolean).length : 0;
      const generic = /^(home|homepage|welcome[ !.]*(to.*)?|untitled|index|hello)\.?$/i.test(h1t);
      const descriptiveH1 = h1 >= 1 && !generic && h1t.length >= 15 && words >= 3; // more than a short brand name
      let score = 45;
      if (descriptiveH1) score += 18; else if (h1 >= 1 && !generic) score += 6;
      if (t && t.length >= 15) score += 6;
      if (md && md.length >= 50) score += 6;
      if (h1 === 0) score -= 20;
      if (generic) score -= 12;
      if (!t) score -= 12;
      score = Math.max(12, Math.min(72, score)); // capped — positioning fit is confirmed by a human, never auto-certified
      const weak = h1 === 0 || generic || !descriptiveH1;
      const note = weak
        ? 'Your main headline may not instantly tell a stranger what you do — a clear, benefit-led headline should say what you offer, and to whom, within 5 seconds.'
        : 'Headline, title and description are in place — but whether your branding instantly says “what you do and why you’re different” is confirmed by eye in the manual review.';
      set('brand.valueprop', mk(score, note, 'headline ' + (descriptiveH1 ? 'clear' : (h1 >= 1 ? 'weak/brand-only' : 'missing')) + ' · title ' + (t ? '✓' : '✗') + ' · desc ' + (md ? '✓' : '✗')));
    }
  }

  /* 2 — Technical Health */
  {
    const lcp = aScore(lhM, 'largest-contentful-paint'), cls = aScore(lhM, 'cumulative-layout-shift'), tbt = aScore(lhM, 'total-blocking-time');
    let s = null, sum = 0, w = 0; // LCP is the headline metric — weight it 2× so a slow LCP isn't hidden by good CLS/TBT
    if (lcp != null) { sum += lcp * 2; w += 2; }
    if (cls != null) { sum += cls; w += 1; }
    if (tbt != null) { sum += tbt; w += 1; }
    if (w) s = sum / w;
    const le = mobile && mobile.loadingExperience && mobile.loadingExperience.metrics;
    const inp = le && le.INTERACTION_TO_NEXT_PAINT ? ' · field INP ' + le.INTERACTION_TO_NEXT_PAINT.percentile + 'ms' : '';
    set('tech.cwv', mk(s, s >= 80 ? 'Core Web Vitals look healthy.' : 'Core Web Vitals need work — a common cause of lost mobile conversions.',
      [aDisp(lhM, 'largest-contentful-paint') && 'LCP ' + aDisp(lhM, 'largest-contentful-paint'), aDisp(lhM, 'cumulative-layout-shift') && 'CLS ' + aDisp(lhM, 'cumulative-layout-shift')].filter(Boolean).join(' · ') + inp));
  }
  {
    const s = (perfM != null && perfD != null) ? Math.round(perfM * 0.6 + perfD * 0.4) : (perfM != null ? perfM : perfD);
    set('tech.speed', mk(s, s >= 80 ? 'Fast on both mobile and desktop.' : 'Speed is dragging — every second costs conversions.',
      [perfM != null && 'Mobile ' + perfM, perfD != null && 'Desktop ' + perfD].filter(Boolean).join(' · ') + '/100'));
  }
  {
    const https = /^https:/i.test(finalUrl);
    const insecure = dom ? dom.insecure : 0;
    set('tech.https', mk(https ? (insecure === 0 ? 100 : 55) : 0,
      https ? (insecure ? 'HTTPS, but ' + insecure + ' insecure (http://) resource(s) found.' : 'Secure — HTTPS with no mixed content detected.') : 'Not served over HTTPS — a trust and ranking problem.',
      https ? ('HTTPS' + (insecure ? ' · ' + insecure + ' mixed' : '')) : 'HTTP only'));
  }
  {
    const noindex = dom && dom.robotsMeta.includes('noindex');
    set('tech.crawl', mk((robotsOk ? 40 : 5) + (sitemapOk ? 40 : 10) + (noindex ? 0 : 20),
      noindex ? 'Page is set to noindex — search engines are told to skip it.' : (robotsOk && sitemapOk ? 'robots.txt and sitemap.xml both present.' : 'Missing robots.txt or sitemap.xml.'),
      'robots.txt ' + (robotsOk ? '✓' : '✗') + ' · sitemap ' + (sitemapOk ? '✓' : '✗')));
  }
  {
    const s = avg([aScore(lhM, 'http-status-code'), aScore(lhM, 'redirects')]);
    set('tech.brokenlinks', mk(s, s != null && s >= 80 ? 'No status-code or redirect problems on the landing page.' : 'Redirect or status-code issues detected.', null));
  }
  {
    const types = dom ? Array.from(dom.jsonLd) : [];
    if (dom) set('tech.schema', mk(types.length ? 100 : 30,
      types.length ? 'Structured data found: ' + types.slice(0, 4).join(', ') : 'No structured data (schema.org) detected — you may miss rich results.',
      types.length ? types.slice(0, 4).join(', ') : 'none'));
  }
  {
    const srt = aScore(lhM, 'server-response-time');
    set('tech.hosting', mk(srt, srt != null && srt >= 80 ? 'Server responds quickly (good TTFB).' : 'Slow server response (TTFB) — hosting or backend may be a bottleneck.', aDisp(lhM, 'server-response-time')));
  }

  /* 3 — Mobile */
  {
    const vp = dom ? dom.hasViewport : null;
    const va = aScore(lhM, 'viewport');
    const s = vp === null ? va : (vp ? (va != null ? va : 95) : 20);
    set('mobile.responsive', mk(s, s >= 80 ? 'Responsive viewport configured.' : 'No responsive viewport meta — the page won’t adapt to phones.', vp === null ? null : (vp ? 'viewport meta ✓' : 'viewport meta ✗')));
  }
  {
    const tt = aScore(lhM, 'tap-targets');
    set('mobile.taptargets', mk(tt, tt != null && tt >= 80 ? 'Tap targets are appropriately sized.' : 'Some tap targets are too small or close together for thumbs.', aDisp(lhM, 'tap-targets')));
  }
  {
    const mif = aScore(lhM, 'modern-image-formats'), off = aScore(lhM, 'offscreen-images');
    const s = perfM != null ? Math.round(perfM * 0.7 + (mif != null ? mif : 100) * 0.15 + (off != null ? off : 100) * 0.15) : null;
    set('mobile.speed', mk(s, s >= 80 ? 'Mobile speed is solid.' : 'Mobile speed needs work — compress images (WebP/AVIF) and defer offscreen media.', perfM != null ? 'Mobile perf ' + perfM + '/100' : null));
  }
  {
    const tel = dom ? dom.tel : 0;
    if (dom) set('mobile.clicktocall', mk(tel > 0 ? 100 : 35, tel > 0 ? 'Tappable click-to-call number present.' : 'No click-to-call (tel:) link found — mobile callers must copy the number.', tel > 0 ? tel + ' tel: link(s)' : 'none'));
  }
  {
    if (dom && dom.forms > 0) {
      const typed = ['email', 'tel', 'number'].some((t) => dom.inputTypes.has(t));
      const avg = Math.round(dom.inputs / dom.forms);
      set('mobile.forms', mk(typed ? 90 : 60, typed ? 'Forms use mobile-friendly input types.' : 'Forms may not use mobile input types (email/tel) — harder to fill on phones.', dom.forms + ' form(s) · ~' + avg + ' fields each'));
    }
  }
  {
    if (dom && dom.navLinks > 0) {
      const n = dom.navLinks;
      const c = mk(n <= 7 ? 100 : n <= 10 ? 70 : 45, n <= 7 ? 'Clear navigation (' + n + ' primary links).' : 'Busy navigation (' + n + ' links) — consider simplifying to ≤7.', n + ' nav links');
      set('mobile.nav', c); set('ux.nav', c);
    }
  }
  {
    if (dom) { const h1 = dom.h1Count; set('mobile.abovefold', mk(h1 >= 1 ? 85 : 30, h1 >= 1 ? 'A clear headline (H1) communicates the offer.' : 'No H1 headline — the offer may not be clear above the fold.', h1 >= 1 ? 'H1: "' + dom.h1Text.trim().slice(0, 60) + '"' : 'no H1')); }
  }

  /* 4 — UX */
  {
    const lt = aScore(lhM, 'link-text');
    set('ux.infoscent', mk(lt, lt != null && lt >= 80 ? 'Links use descriptive text.' : 'Some links use vague text ("click here") — hurts UX and SEO.', null));
  }
  {
    if (dom) {
      const h1 = dom.h1Count, hd = dom.headingCount;
      const s = h1 === 1 ? (hd >= 3 ? 90 : 75) : (h1 === 0 ? 30 : 55);
      set('ux.hierarchy', mk(s, h1 === 1 ? 'Single clear H1 with supporting headings.' : (h1 === 0 ? 'No H1 — weak content hierarchy.' : h1 + ' H1s — there should usually be one.'), h1 + ' H1 · ' + hd + ' headings'));
    }
  }
  set('ux.accessibility', mk(a11y, a11y != null && a11y >= 80 ? 'Good accessibility foundations.' : 'Accessibility issues (contrast, alt text or font size) — fixes also help SEO.', a11y != null ? a11y + '/100' : null));

  /* 5 — CTAs */
  {
    if (dom) {
      const txt = (dom.ctaText || '').toLowerCase();
      const has = /\b(book|call|contact|get|start|buy|shop|sign ?up|subscribe|quote|enquire|inquire|request|download|apply|order|schedule|learn more|find out|get started)\b/.test(txt) || dom.tel > 0 || dom.forms > 0;
      set('cta.presence', mk(has ? 85 : 35, has ? 'Clear calls-to-action detected.' : 'No obvious call-to-action — visitors may not know the next step.', null));
      let variety = 0; if (dom.tel > 0) variety++; if (dom.mailto > 0) variety++; if (dom.forms > 0) variety++;
      if (/\b(book|call|contact|get|buy|shop|subscribe|quote|enquire|request|apply|order)\b/.test(txt)) variety++;
      set('cta.channels', mk(variety >= 3 ? 100 : variety === 2 ? 75 : variety === 1 ? 55 : 30, variety >= 2 ? 'Multiple ways to convert (phone / email / form).' : 'Limited conversion options — add a phone, form or chat option.',
        'phone ' + (dom.tel > 0 ? '✓' : '✗') + ' · email ' + (dom.mailto > 0 ? '✓' : '✗') + ' · form ' + (dom.forms > 0 ? '✓' : '✗')));
      if (dom.forms > 0) { const n = dom.inputs; set('cta.form', mk(n <= 5 ? 90 : n <= 8 ? 65 : 45, n <= 5 ? 'Lean form (' + n + ' fields).' : 'Form has ' + n + ' fields — every extra field costs conversions.', n + ' fields')); }
    }
  }

  /* 7 — Organic Search (on-page) */
  {
    if (dom) {
      const t = dom.title.trim(), md = dom.metaDesc.trim();
      const s = avg([
        !t ? 0 : (t.length >= 20 && t.length <= 65 ? 100 : 70),
        !md ? 20 : (md.length >= 50 && md.length <= 165 ? 100 : 70),
        dom.h1Count >= 1 ? 100 : 30,
        dom.imgCount > 0 ? Math.round(dom.imgAlt / dom.imgCount * 100) : 100,
        dom.internal > 0 ? 100 : 50,
        seoLh,
      ]);
      set('seo.onpage', mk(s, s >= 80 ? 'Strong on-page SEO basics.' : 'On-page SEO gaps — check title, meta description, H1 and image alt text.',
        'title ' + (t ? '✓' : '✗') + ' · meta ' + (md ? '✓' : '✗') + ' · alt ' + (dom.imgCount ? Math.round(dom.imgAlt / dom.imgCount * 100) + '%' : 'n/a')));
    }
  }

  /* 9 — Social */
  {
    if (dom) {
      const n = dom.social.size;
      set('social.presence', mk(n >= 2 ? 100 : n === 1 ? 65 : 25, n > 0 ? 'Social profiles linked: ' + Array.from(dom.social).join(', ') : 'No social profile links found on the site — link your profiles so visitors (and Google) can find them.', n > 0 ? Array.from(dom.social).join(', ') : 'none'));
    }
  }

  /* 10 — Reputation & Reviews (on-site signals only; off-site data needs a paid API, stays manual) */
  {
    if (dom) {
      const platforms = Array.from(dom.reviewPlatforms || []);
      const ar = dom.aggRating;
      let score, note, value;
      if (ar || platforms.length) {
        score = ar ? (ar.rating >= 4 ? 100 : ar.rating >= 3.5 ? 78 : 55) : (platforms.length >= 2 ? 92 : 80);
        const bits = [];
        if (ar) bits.push(ar.rating + '★' + (ar.count ? ' · ' + ar.count + ' reviews' : ''));
        if (platforms.length) bits.push(platforms.join(', '));
        note = 'Reviews are shown on your site — great for trust and click-through.';
        value = bits.join(' · ');
      } else {
        score = 35;
        note = 'No reviews shown on your site (no Google/Trustpilot links or review markup) — showcasing them builds trust and can earn star ratings in Google.';
        value = 'none found';
      }
      set('reviews.onsite', mk(score, note, value));
    }
  }

  return checks;
}
