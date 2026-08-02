#!/usr/bin/env python3
"""Regenerate news.html from news.json.

news.json is the source of truth; this writes plain static HTML so the page needs
no JavaScript, stays fast, and remains fully indexable.

Layout: newest article as the feature, the next few as cards, then a dated archive
listing every article ever logged — nothing is dropped as the log grows.

Image rule: an article renders an image area only when it has a verified `image`.
No images means no image area — never a placeholder.

Usage:  python3 scripts/build_news.py
"""

import html
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_JSON = os.path.join(ROOT, "news.json")
NEWS_HTML = os.path.join(ROOT, "news.html")

GRID_COUNT = 6  # cards shown below the feature; everything older falls into the archive

APPLY_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSejl_A42zerhqujVrLGKBe6hxJUETIFZT-razD8FwH_9sLFWQ/viewform"
)

# Native-language sources get a country flag so mixed-language headlines read as
# deliberate international coverage rather than a mistake.
LANG_LABEL = {"de": "🇩🇪 German", "it": "🇮🇹 Italian", "fr": "🇫🇷 French", "ja": "🇯🇵 Japanese"}


def esc(text):
    return html.escape(str(text or ""), quote=True)


def fmt_date(iso, style="long"):
    try:
        dt = datetime.strptime(iso, "%Y-%m-%d")
    except (ValueError, TypeError):
        return esc(iso)
    if style == "long":
        return f"{dt.day} {dt.strftime('%B %Y')}"
    return f"{dt.day} {dt.strftime('%b')}"


def cover(article, css_class):
    """Image block — returns '' when the article has no verified image."""
    if not article.get("image"):
        return ""
    return (
        f'\n      <div class="{css_class}">'
        f'<img src="{esc(article["image"])}" alt="{esc(article["title"])}" '
        f'loading="lazy" decoding="async" referrerpolicy="no-referrer"></div>'
    )


def meta_row(article):
    bits = [f'<span class="tag">{esc(article.get("region") or article.get("source"))}</span>']
    lang = LANG_LABEL.get(article.get("lang"))
    if lang:
        bits.append(f'<span class="lang">{lang}</span>')
    bits.append(f'<span class="date">{fmt_date(article["published"])}</span>')
    return "".join(bits)


def render_featured(a):
    return f"""  <a class="featured{'' if a.get('image') else ' no-img'}" href="{esc(a['url'])}" target="_blank" rel="noopener">{cover(a, 'cover cover-lg')}
    <div class="featured-body">
      <div class="card-meta">{meta_row(a)}</div>
      <h2>{esc(a['title'])}</h2>
      <p>{esc(a['summary'])}</p>
      <span class="read-more">Read on {esc(a['source'])} →</span>
    </div>
  </a>"""


def render_card(a):
    return f"""    <a class="news-card{'' if a.get('image') else ' no-img'}" href="{esc(a['url'])}" target="_blank" rel="noopener">{cover(a, 'cover')}
      <div class="news-body">
        <div class="card-meta">{meta_row(a)}</div>
        <h3>{esc(a['title'])}</h3>
        <p>{esc(a['summary'])}</p>
        <span class="read-more">Read on {esc(a['source'])} →</span>
      </div>
    </a>"""


def render_archive(articles):
    """Every article, newest first, grouped by month."""
    if not articles:
        return ""
    months = OrderedDict()
    for a in articles:
        try:
            key = datetime.strptime(a["published"], "%Y-%m-%d").strftime("%B %Y")
        except (ValueError, TypeError):
            key = "Undated"
        months.setdefault(key, []).append(a)

    blocks = []
    for month, items in months.items():
        rows = "\n".join(
            f'        <li><a href="{esc(a["url"])}" target="_blank" rel="noopener">'
            f'<span class="ar-date">{fmt_date(a["published"], "short")}</span>'
            f'<span class="ar-title">{esc(a["title"])}</span>'
            f'<span class="ar-src">{esc(a["source"])}</span></a></li>'
            for a in items
        )
        blocks.append(
            f'      <div class="ar-month">\n'
            f'        <h3>{esc(month)} <span>{len(items)}</span></h3>\n'
            f'      </div>\n'
            f'      <ul class="ar-list">\n{rows}\n      </ul>'
        )
    return "\n".join(blocks)


def build(data):
    articles = data.get("articles", [])
    if not articles:
        raise SystemExit("news.json has no articles — nothing to build.")

    featured = articles[0]
    grid = articles[1 : 1 + GRID_COUNT]
    updated = data.get("updated") or datetime.utcnow().strftime("%Y-%m-%d")

    grid_html = "\n\n".join(render_card(a) for a in grid)
    archive_html = render_archive(articles)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" href="logo.png">
<title>News — Plastic Ultimate Academy</title>
<meta name="description" content="Ultimate Frisbee news from around the world — world championships, results and the stories shaping the sport, gathered from federations across the US, Europe and Asia.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<!-- GENERATED FILE — do not edit by hand.
     Source of truth: news.json  ·  Rebuild: python3 scripts/build_news.py -->
<style>
  :root{{--black:#0a0a0a;--grey-90:#1a1a1a;--grey-70:#333;--grey-50:#666;--grey-30:#999;--grey-15:#d4d4d4;--grey-08:#ebebeb;--grey-04:#f5f5f5;--white:#fff;--orange:#f5640a;--orange-light:#ff7f2a;--orange-pale:#fff4ed;--orange-mid:#fde8d8;--orange-border:rgba(245,100,10,0.2);}}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  html{{scroll-behavior:smooth;-webkit-text-size-adjust:100%;}}
  body{{background:var(--white);color:var(--black);font-family:'Inter',-apple-system,sans-serif;font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased;overflow-x:hidden;}}
  img{{max-width:100%;}}

  nav{{position:fixed;top:0;left:0;right:0;z-index:100;height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 2.5rem;background:rgba(255,255,255,.95);backdrop-filter:blur(16px);border-bottom:1px solid var(--orange-border);}}
  .nav-logo{{font-size:.95rem;font-weight:700;letter-spacing:-.01em;color:var(--black);text-decoration:none;display:flex;align-items:center;gap:.6rem;}}
  .nav-logo img{{width:32px;height:32px;object-fit:contain;}}
  .nav-links{{display:flex;align-items:center;gap:1.8rem;list-style:none;}}
  .nav-toggle{{display:none;background:none;border:none;color:var(--black);cursor:pointer;padding:.4rem;line-height:0;}}
  .nav-links a{{color:var(--grey-50);text-decoration:none;font-size:.875rem;font-weight:500;transition:color .15s;}}
  .nav-links a:hover,.nav-links a.active{{color:var(--black);}}
  .btn-nav{{background:var(--orange)!important;color:var(--white)!important;padding:.45rem 1.2rem;border-radius:6px;font-size:.8rem!important;font-weight:600!important;}}
  .btn-nav:hover{{background:var(--orange-light)!important;}}

  .page-top{{margin-top:64px;padding:4rem 2.5rem 3rem;border-bottom:1px solid var(--orange-border);background:var(--orange-pale);text-align:center;}}
  .breadcrumb{{font-size:.78rem;color:var(--grey-30);margin-bottom:1.5rem;display:flex;align-items:center;justify-content:center;gap:.4rem;}}
  .breadcrumb a{{color:var(--grey-30);text-decoration:none;}}
  .page-title{{font-size:clamp(2rem,4vw,3.5rem);font-weight:700;letter-spacing:-.03em;line-height:1.05;color:var(--black);margin-bottom:.75rem;}}
  .page-sub{{font-size:1rem;color:var(--grey-50);max-width:620px;line-height:1.7;margin-left:auto;margin-right:auto;}}
  .update-badge{{display:inline-flex;align-items:center;gap:.5rem;margin-top:1.5rem;background:var(--white);border:1px solid var(--orange-border);color:var(--grey-70);font-size:.78rem;font-weight:500;padding:.4rem .9rem;border-radius:100px;}}
  .update-dot{{width:7px;height:7px;border-radius:50%;background:var(--orange);flex-shrink:0;}}
  .update-badge strong{{color:var(--black);font-weight:600;}}

  .news-wrap{{max-width:1080px;margin:0 auto;padding:3.5rem 2.5rem 5rem;}}

  .cover{{overflow:hidden;background:var(--grey-04);height:150px;}}
  .cover img{{width:100%;height:100%;object-fit:cover;object-position:center;display:block;}}
  .cover-lg{{height:280px;}}

  /* FEATURED */
  .featured{{display:block;text-decoration:none;background:var(--orange-pale);border:1px solid var(--orange-border);border-radius:16px;overflow:hidden;margin-bottom:2.5rem;transition:transform .15s,box-shadow .15s;}}
  .featured:hover{{transform:translateY(-2px);box-shadow:0 8px 28px rgba(245,100,10,.1);}}
  .featured-body{{padding:2.5rem;}}
  .card-meta{{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin-bottom:1rem;}}
  .tag{{font-size:.68rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--orange);background:var(--white);border:1px solid var(--orange-border);border-radius:100px;padding:.25rem .7rem;}}
  .lang{{font-size:.7rem;font-weight:500;color:var(--grey-50);background:var(--grey-04);border-radius:100px;padding:.25rem .6rem;}}
  .date{{font-size:.78rem;color:var(--grey-30);font-weight:500;}}
  .featured h2{{font-size:clamp(1.4rem,2.6vw,2rem);font-weight:700;letter-spacing:-.025em;line-height:1.15;color:var(--black);margin-bottom:.9rem;}}
  .featured p{{font-size:.975rem;color:var(--grey-50);line-height:1.7;max-width:720px;margin-bottom:1.25rem;}}
  .read-more{{font-size:.85rem;font-weight:600;color:var(--orange);display:inline-flex;align-items:center;gap:.35rem;}}

  /* GRID */
  .news-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:1.5rem;align-items:start;}}
  .news-card{{display:flex;flex-direction:column;text-decoration:none;background:var(--white);border:1px solid var(--orange-border);border-radius:14px;overflow:hidden;transition:transform .15s,box-shadow .15s,background .15s;}}
  .news-card:hover{{transform:translateY(-2px);box-shadow:0 6px 22px rgba(245,100,10,.08);background:var(--orange-pale);}}
  .news-body{{display:flex;flex-direction:column;flex:1;padding:1.6rem 1.75rem 1.75rem;}}
  .news-card h3{{font-size:1.1rem;font-weight:700;letter-spacing:-.02em;line-height:1.3;color:var(--black);margin-bottom:.6rem;}}
  .news-card p{{font-size:.875rem;color:var(--grey-50);line-height:1.65;margin-bottom:1.1rem;flex-grow:1;}}

  /* ARCHIVE */
  .archive{{margin-top:4rem;padding-top:2.5rem;border-top:1px solid var(--orange-border);}}
  .archive-head h2{{font-size:1.4rem;font-weight:700;letter-spacing:-.02em;color:var(--black);margin-bottom:1.75rem;}}
  .ar-month h3{{font-size:.72rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--grey-30);margin:2rem 0 .5rem;display:flex;align-items:center;gap:.6rem;}}
  .ar-month:first-of-type h3{{margin-top:0;}}
  .ar-month h3 span{{background:var(--orange-pale);color:var(--orange);border-radius:100px;padding:.1rem .55rem;font-size:.68rem;letter-spacing:0;}}
  .ar-list{{list-style:none;border-top:1px solid var(--grey-08);}}
  .ar-list a{{display:flex;align-items:baseline;gap:1rem;padding:.85rem .35rem;border-bottom:1px solid var(--grey-08);text-decoration:none;transition:background .15s;}}
  .ar-list a:hover{{background:var(--orange-pale);}}
  .ar-date{{flex:0 0 62px;font-size:.76rem;color:var(--grey-30);font-weight:500;font-variant-numeric:tabular-nums;}}
  .ar-title{{flex:1;font-size:.9rem;color:var(--grey-90);line-height:1.5;}}
  .ar-list a:hover .ar-title{{color:var(--orange);}}
  .ar-src{{flex:0 0 auto;font-size:.72rem;color:var(--grey-30);white-space:nowrap;}}

  .news-foot{{margin-top:3rem;padding-top:2rem;border-top:1px solid var(--orange-border);font-size:.85rem;color:var(--grey-50);line-height:1.7;}}
  .news-foot a{{color:var(--orange);text-decoration:none;font-weight:600;}}
  .news-foot a:hover{{text-decoration:underline;}}

  .footer-wrap{{border-top:1px solid var(--orange-border);background:var(--orange-pale);}}
  footer{{padding:2.5rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1.5rem;max-width:1080px;margin:0 auto;}}
  .footer-logo{{font-size:.9rem;font-weight:700;color:var(--black);text-decoration:none;display:flex;align-items:center;gap:.6rem;}}
  .footer-logo img{{width:26px;height:26px;object-fit:contain;}}
  .footer-links{{display:flex;gap:1.8rem;list-style:none;}}
  .footer-links a{{color:var(--grey-50);text-decoration:none;font-size:.82rem;transition:color .15s;}}
  .footer-links a:hover{{color:var(--orange);}}
  .footer-copy{{font-size:.78rem;color:var(--grey-30);}}

  @media(max-width:860px){{
    nav{{padding:0 1rem;}}
    .nav-toggle{{display:flex;}}
    .nav-links{{position:absolute;top:64px;left:0;right:0;flex-direction:column;align-items:stretch;gap:0;background:rgba(255,255,255,.98);backdrop-filter:blur(16px);border-bottom:1px solid var(--orange-border);box-shadow:0 10px 24px rgba(0,0,0,.07);padding:.5rem 1rem 1rem;display:none;}}
    nav.open .nav-links{{display:flex;}}
    .nav-links li{{width:100%;}}
    .nav-links a{{display:block;padding:.85rem .5rem;font-size:1rem;border-bottom:1px solid var(--grey-08);}}
    .nav-links li:last-child a{{border-bottom:none;margin-top:.5rem;text-align:center;}}
    .page-top{{padding:3rem 1.25rem 2rem;}}
    .news-wrap{{padding:2.5rem 1.25rem 3.5rem;}}
    .cover-lg{{height:200px;}}
    .featured{{margin-bottom:1.75rem;}}
    .featured-body{{padding:1.6rem 1.5rem 1.75rem;}}
    .news-grid{{grid-template-columns:1fr;gap:1.25rem;}}
    .news-card:hover,.featured:hover{{transform:none;box-shadow:none;}}
    .news-body{{padding:1.4rem 1.5rem 1.6rem;}}
    .archive{{margin-top:3rem;padding-top:2rem;}}
    .ar-list a{{flex-wrap:wrap;gap:.15rem .75rem;padding:.9rem .25rem;}}
    .ar-date{{flex:0 0 auto;order:1;}}
    .ar-src{{order:2;}}
    .ar-title{{order:3;flex:1 1 100%;font-size:.92rem;}}
    footer{{padding:2rem 1.25rem;flex-direction:column;align-items:flex-start;gap:1.1rem;}}
    .footer-links{{flex-wrap:wrap;gap:1.1rem;}}
  }}
</style>
</head>
<body>

<nav>
  <a href="index.html" class="nav-logo"><img src="logo.png" alt="Plastic Ultimate">Plastic Ultimate</a>
  <button class="nav-toggle" aria-label="Menu" aria-expanded="false" onclick="var n=this.closest('nav');this.setAttribute('aria-expanded',n.classList.toggle('open'));"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
  <ul class="nav-links">
    <li><a href="index.html">Home</a></li>
    <li><a href="news.html" class="active">News</a></li>
    <li><a href="recovery.html">Recovery</a></li>
    <li><a href="merch.html">Merch</a></li>
    <li><a href="{APPLY_URL}" target="_blank" class="btn-nav">Apply now →</a></li>
  </ul>
</nav>

<div class="page-top">
  <div class="breadcrumb"><a href="index.html">Home</a> <span>/</span> News</div>
  <h1 class="page-title">Ultimate news.</h1>
  <p class="page-sub">The latest from the world of Ultimate Frisbee, gathered automatically from federations and outlets across the US, Europe and Asia — and kept as a permanent archive.</p>
  <div class="update-badge"><span class="update-dot"></span><strong>{len(articles)} articles logged</strong> · Updated {fmt_date(updated)}</div>
</div>

<div class="news-wrap">

  <!-- FEATURED -->
{render_featured(featured)}

  <!-- RECENT -->
  <div class="news-grid">

{grid_html}

  </div>

  <!-- ARCHIVE -->
  <div class="archive">
    <div class="archive-head">
      <h2>Full archive</h2>
    </div>
{archive_html}
  </div>

  <div class="news-foot">
    Headlines are collected automatically from
    <a href="https://wfdf.sport/" target="_blank" rel="noopener">WFDF</a>,
    <a href="https://ultiworld.com/" target="_blank" rel="noopener">Ultiworld</a>,
    USA Ultimate and the national federations of Germany, Italy, France and Japan.
    Each headline links straight to the original publisher.
  </div>

</div>

<div class="footer-wrap">
  <footer>
    <a href="index.html" class="footer-logo"><img src="logo.png" alt="Plastic Ultimate">Plastic Ultimate Academy</a>
    <ul class="footer-links"><li><a href="index.html">Home</a></li><li><a href="news.html">News</a></li><li><a href="recovery.html">Recovery</a></li><li><a href="merch.html">Merch</a></li><li><a href="join.html">Join</a></li></ul>
    <div class="footer-copy">© 2026 Plastic Ultimate Academy · London</div>
  </footer>
</div>

</body>
</html>
"""


def main():
    with open(NEWS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    output = build(data)
    with open(NEWS_HTML, "w", encoding="utf-8") as fh:
        fh.write(output)
    total = len(data.get("articles", []))
    with_img = sum(1 for a in data["articles"] if a.get("image"))
    print(f"Wrote {NEWS_HTML}")
    print(f"  {total} articles ({with_img} with images, {total - with_img} without)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
