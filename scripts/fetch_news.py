#!/usr/bin/env python3
"""Append new Ultimate Frisbee articles to news.json.

APPEND-ONLY: existing entries are never removed or rewritten. Each run adds only
articles whose URL isn't already in the log, so news.json grows into a permanent
record of everything the site has ever surfaced.

Images: RSS feeds for these outlets carry no images, so each new article's page is
fetched once and its og:image (or twitter:image) is read. The URL is then verified
to actually return an image. If any of that fails, the article is stored with no
image and renders with no image area at all — never a placeholder.

Standard library only, so the GitHub Action needs no pip install.

Usage:  python3 scripts/fetch_news.py [--dry-run]
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import SOURCES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_JSON = os.path.join(ROOT, "news.json")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
FEED_TIMEOUT = 25
PAGE_TIMEOUT = 20
MAX_SUMMARY = 260

SSL_CTX = ssl.create_default_context()

NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def log(msg):
    print(msg, flush=True)


def get(url, timeout, max_bytes=600_000):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read(max_bytes), resp.headers, resp.geturl()


def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    import html as html_mod

    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


BOILERPLATE = [
    re.compile(r"\s*The post\b.*?appeared first on\b.*?$", re.I | re.S),
    re.compile(r"\s*(Continue reading|Read more|Read the full story|Leggi tutto|"
               r"Weiterlesen|Lire la suite)\s*[.…>»]*\s*$", re.I),
    re.compile(r"\s*Source\s*$", re.I),
    re.compile(r"^\s*(Share this:|Tweet|Facebook)\s*", re.I),
]


def clean_summary(text):
    """Strip the syndication boilerplate WordPress feeds append to descriptions."""
    previous = None
    while text and text != previous:
        previous = text
        for pattern in BOILERPLATE:
            text = pattern.sub("", text).strip()
    return text


def shorten(text, limit=MAX_SUMMARY):
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:—-") + "…"


def normalise_url(url):
    """Strip tracking params and trailing slashes so the same article isn't logged twice."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query)
        if not k.lower().startswith(("utm_", "fbclid", "gclid", "mc_"))
    ]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urllib.parse.urlencode(query), "")
    )


def parse_date(item):
    for tag, ns in (("pubDate", None), ("date", NS), ("updated", None)):
        raw = item.findtext(tag, namespaces=ns) if ns else item.findtext(tag)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


# Deliberately narrow. The dimension check below is the real filter — several outlets
# name genuine hero photos "*-header.jpg", so broad word matching throws away good images.
JUNK_IMAGE = re.compile(
    r"(logo|favicon|/icons?/|[-_]icon[-_.]|avatar|sprite|placeholder|"
    r"default[-_]image|social[-_]?share|og[-_]?default|footer[-_])",
    re.I,
)
MIN_IMAGE_WIDTH = 600
MIN_IMAGE_HEIGHT = 300


def image_dimensions(blob):
    """Read (width, height) from the first bytes of PNG/JPEG/GIF/WebP. None if unknown."""
    import struct

    try:
        if blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR":
            return struct.unpack(">II", blob[16:24])
        if blob[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", blob[6:10])
        if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
            fmt = blob[12:16]
            if fmt == b"VP8 ":
                return struct.unpack("<HH", blob[26:30])
            if fmt == b"VP8L":
                bits = int.from_bytes(blob[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if fmt == b"VP8X":
                w = int.from_bytes(blob[24:27], "little") + 1
                h = int.from_bytes(blob[27:30], "little") + 1
                return w, h
        if blob[:2] == b"\xff\xd8":  # JPEG: walk the marker segments
            i = 2
            while i < len(blob) - 9:
                if blob[i] != 0xFF:
                    i += 1
                    continue
                marker = blob[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg_len = int.from_bytes(blob[i + 2 : i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(blob[i + 5 : i + 7], "big")
                    w = int.from_bytes(blob[i + 7 : i + 9], "big")
                    return w, h
                i += 2 + seg_len
    except Exception:
        pass
    return None


def find_article_image(page_url):
    """Return a usable image URL from the article page, or None.

    Never guesses. Checks og:image / twitter:image, then verifies the URL really
    serves an image before accepting it.
    """
    try:
        body, _, final_url = get(page_url, PAGE_TIMEOUT, max_bytes=400_000)
    except Exception as exc:
        log(f"      no image (page fetch failed: {type(exc).__name__})")
        return None

    html_text = body.decode("utf-8", errors="ignore")
    head = html_text[:200_000]

    candidates = []
    for prop in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        for pattern in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
        ):
            candidates += re.findall(pattern, head, re.I)

    seen = set()
    for raw in candidates:
        import html as html_mod

        img = html_mod.unescape(raw).strip()
        if not img or img in seen:
            continue
        seen.add(img)
        img = urllib.parse.urljoin(final_url, img)
        if not img.startswith(("http://", "https://")):
            continue
        if re.search(r"\.svg(\?|$)", img, re.I):
            continue  # usually a logo, not article art
        if JUNK_IMAGE.search(urllib.parse.urlsplit(img).path):
            log(f"      skipped (looks like a logo/icon): {os.path.basename(img)[:50]}")
            continue
        try:
            req = urllib.request.Request(img, headers={"User-Agent": UA}, method="GET")
            with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT, context=SSL_CTX) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if resp.status != 200 or not ctype.startswith("image/"):
                    continue
                head_bytes = resp.read(65_536)
        except Exception:
            continue

        size = image_dimensions(head_bytes)
        if size is None:
            log(f"      accepted (dimensions unreadable): {os.path.basename(img)[:50]}")
            return img
        width, height = size
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            log(f"      skipped (too small, {width}x{height}): {os.path.basename(img)[:40]}")
            continue
        return img

    log("      no usable image on the article page")
    return None


def read_feed(source):
    try:
        body, _, _ = get(source["feed"], FEED_TIMEOUT)
    except Exception as exc:
        log(f"  !! {source['name']}: feed unreachable ({type(exc).__name__}) — skipped")
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log(f"  !! {source['name']}: malformed feed ({exc}) — skipped")
        return []

    items = root.findall(".//item")
    parsed = []
    for item in items:
        link = (item.findtext("link") or "").strip()
        title = strip_html(item.findtext("title") or "")
        if not link or not title:
            continue
        summary = clean_summary(
            strip_html(
                item.findtext("description")
                or item.findtext("content:encoded", namespaces=NS)
                or ""
            )
        )
        parsed.append(
            {
                "title": title,
                "url": link,
                "summary": shorten(summary),
                "published": parse_date(item),
            }
        )
    return parsed


def load_log():
    if not os.path.exists(NEWS_JSON):
        return {"articles": []}
    with open(NEWS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("articles", [])
    return data


def refresh_images(data, dry_run):
    """Re-run image lookup over articles that currently have none.

    Useful after tuning the image filter, or when a publisher adds art to an older
    post. Only ever adds images — never removes or changes anything else.
    """
    targets = [a for a in data["articles"] if not a.get("image")]
    log(f"Re-checking images for {len(targets)} article(s) without one")
    found = 0
    for article in targets:
        log(f"   ? {article['title'][:70]}")
        image = find_article_image(article["url"])
        if image:
            article["image"] = image
            found += 1
            log(f"      image: {image[:78]}")
    log(f"\nFound {found} new image(s).")
    if found and not dry_run:
        data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(NEWS_JSON, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        log(f"Wrote {NEWS_JSON}")
    return 0


def main():
    dry_run = "--dry-run" in sys.argv
    data = load_log()

    if "--refresh-images" in sys.argv:
        return refresh_images(data, dry_run)

    known = {normalise_url(a["url"]) for a in data["articles"]}
    log(f"Existing log: {len(data['articles'])} articles")

    added = []
    for source in SOURCES:
        log(f"\n-> {source['name']} ({source['region']})")
        entries = read_feed(source)
        if not entries:
            continue
        entries.sort(key=lambda e: e["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        taken = 0
        for entry in entries:
            if taken >= source["cap"]:
                break
            key = normalise_url(entry["url"])
            if key in known:
                continue
            log(f"   + {entry['title'][:72]}")
            image = find_article_image(entry["url"])
            if image:
                log(f"      image: {image[:78]}")
            published = entry["published"] or datetime.now(timezone.utc)
            article = {
                "title": entry["title"],
                "url": entry["url"],
                "summary": entry["summary"],
                "source": source["name"],
                "source_key": source["key"],
                "region": source["region"],
                "lang": source["lang"],
                "published": published.strftime("%Y-%m-%d"),
                "added": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
            if image:
                article["image"] = image
            added.append(article)
            known.add(key)
            taken += 1

        if taken == 0:
            log("   (nothing new)")

    if not added:
        log("\nNo new articles. news.json unchanged.")
        return 0

    data["articles"].extend(added)
    # Newest first; ties broken by title so ordering is stable across runs.
    data["articles"].sort(key=lambda a: (a["published"], a["title"]), reverse=True)
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data["count"] = len(data["articles"])

    log(f"\nAdded {len(added)} article(s). Log now holds {len(data['articles'])}.")
    if dry_run:
        log("--dry-run: not writing news.json")
        return 0

    with open(NEWS_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    log(f"Wrote {NEWS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
