"""Headlines. The only file that touches Google News RSS and Yahoo Finance RSS.

Google News first, Yahoo as fallback. Publisher shown, paywall tag from config/news.yaml,
duplicates removed, polite delay between requests.
"""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests
import yaml

from src.paths import CONFIG
from src.retry import retry

UA = {"User-Agent": "morning-market-brief (personal, non-commercial)"}
TIMEOUT = 30
DELAY_SECONDS = 1.0  # polite gap before every request; tests set it to 0
_last_request = [0.0]
_settings = None


def settings():
    global _settings
    if _settings is None:
        with open(CONFIG / "news.yaml", encoding="utf-8") as f:
            _settings = yaml.safe_load(f)
    return _settings


def google_url(query, hl="en-US", gl="US"):
    ceid = f"{gl}:{hl.split('-')[0]}"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"


def yahoo_url(ticker):
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(ticker)}&region=US&lang=en-US"


def _polite_get(url):
    wait = DELAY_SECONDS - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()
    resp = requests.get(url, headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def domain_of(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_paywall(domain):
    domains = settings().get("paywall_domains", [])
    return any(domain == d or domain.endswith("." + d) for d in domains)


def parse_google(xml_text):
    """Google items: title 'Headline - Publisher', <source url=...>Publisher</source>, redirect link."""
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        src = item.find("source")
        publisher = (src.text or "").strip() if src is not None else ""
        src_url = src.get("url", "") if src is not None else ""
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3].strip()
        elif " - " in title and not publisher:
            title, publisher = title.rsplit(" - ", 1)
        domain = domain_of(src_url) if src_url else ""
        items.append({"title": title, "url": link, "publisher": publisher or domain,
                      "paywall": is_paywall(domain), "published": item.findtext("pubDate", "")})
    return items


def parse_yahoo(xml_text):
    """Yahoo items: plain title and the real article link; publisher is the link's domain."""
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        link = (item.findtext("link") or "").strip()
        domain = domain_of(link)
        items.append({"title": (item.findtext("title") or "").strip(), "url": link, "publisher": domain,
                      "paywall": is_paywall(domain), "published": item.findtext("pubDate", "")})
    return items


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = _norm(it["title"])
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def get_headlines(query, n=3, hl="en-US", gl="US", ticker=None):
    """Return up to n {title, url, publisher, paywall, published} dicts.

    Google News RSS first; if it fails or is empty and a ticker is given, Yahoo Finance RSS.
    Raises only if every source fails.
    """
    errors = []
    try:
        items = dedupe(parse_google(retry(_polite_get, google_url(query, hl, gl))))
        if items:
            return items[:n]
        errors.append("google: no results")
    except Exception as e:  # noqa: BLE001
        errors.append(f"google: {type(e).__name__}: {e}")
    if ticker:
        try:
            items = dedupe(parse_yahoo(retry(_polite_get, yahoo_url(ticker))))
            if items:
                return items[:n]
            errors.append("yahoo: no results")
        except Exception as e:  # noqa: BLE001
            errors.append(f"yahoo: {type(e).__name__}: {e}")
    raise RuntimeError("; ".join(errors))
