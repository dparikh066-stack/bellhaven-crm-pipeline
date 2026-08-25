"""Scrapes the Bellhaven Senior Living website (/communities) for every listed
community: name, full address, city/state/zip, care offerings, phone.
"""
import re
import time
import json
import urllib.request

BASE = "https://analyst-assessment-production.up.railway.app"

CARD_RE = re.compile(
    r'<a href="(/communities/[^"]+)">([^<]+)</a></h3>\s*'
    r'<div class="city">([^<]+)</div>\s*'
    r'<div>((?:<span class="badge">[^<]+</span>)+)</div>'
)
BADGE_RE = re.compile(r'<span class="badge">([^<]+)</span>')
PAGER_RE = re.compile(r'Page (\d+) / (\d+)')

DETAIL_RE = re.compile(
    r'<h1>([^<]+)</h1>.*?'
    r'<dt>Address</dt><dd>([^<]+)<br>([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)</dd>\s*'
    r'<dt>Care Offerings</dt><dd>((?:<span class="badge">[^<]+</span>)+)</dd>\s*'
    r'<dt>Administrator</dt><dd>([^<]*)</dd>\s*'
    r'<dt>Phone</dt><dd>([^<]*)</dd>',
    re.DOTALL,
)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "bellhaven-crm-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def _unescape(s):
    return (
        s.replace("&amp;", "&")
        .replace("&rarr;", "->")
        .replace("&larr;", "<-")
        .strip()
    )


HOMEPAGE_LINK_RE = re.compile(r'href="(/communities/[^"?]+)"')


def list_community_slugs():
    """Walk /communities?page=N and return every community slug found.

    Also scans the homepage for /communities/{slug} links: the site has shown
    a just-announced community (e.g. a fresh acquisition) linked from a promo
    banner before it's been added to the paginated directory grid, so relying
    on pagination alone silently misses it.
    """
    slugs = []
    seen = set()
    page = 1
    while True:
        url = f"{BASE}/communities?page={page}"
        html = _get(url)
        cards = CARD_RE.findall(html)
        for href, name, city_state, _badges_html in cards:
            slug = href.rsplit("/", 1)[-1]
            if slug not in seen:
                seen.add(slug)
                slugs.append(slug)
        m = PAGER_RE.search(html)
        if not m:
            break
        current, total = int(m.group(1)), int(m.group(2))
        if current >= total:
            break
        page += 1

    home_html = _get(BASE + "/")
    for href in HOMEPAGE_LINK_RE.findall(home_html):
        slug = href.rsplit("/", 1)[-1]
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    return slugs


def fetch_location(slug):
    """Fetch and parse a single community detail page into a normalized dict."""
    url = f"{BASE}/communities/{slug}"
    html = _get(url)
    m = DETAIL_RE.search(html)
    if not m:
        raise ValueError(f"Could not parse detail page for slug={slug!r}")
    name, street, city, state, zip_code, badges_html, admin, phone = m.groups()
    care_offerings = [_unescape(b) for b in BADGE_RE.findall(badges_html)]
    return {
        "slug": slug,
        "source_url": url,
        "name": _unescape(name),
        "street": _unescape(street),
        "city": _unescape(city),
        "state": state,
        "zip": zip_code,
        "care_offerings": care_offerings,
        "administrator": _unescape(admin),
        "phone": _unescape(phone),
    }


def scrape_all(delay=0.15):
    """Scrape every community on the site. Returns a list of location dicts."""
    slugs = list_community_slugs()
    locations = []
    for slug in slugs:
        locations.append(fetch_location(slug))
        time.sleep(delay)
    return locations


if __name__ == "__main__":
    locs = scrape_all()
    print(f"Scraped {len(locs)} locations")
    out_path = "data/locations.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(locs, f, indent=2)
    print(f"Wrote {out_path}")
