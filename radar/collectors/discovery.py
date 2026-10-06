"""Descoberta (somente leitura) de feeds, sitemaps e páginas de imprensa de um domínio.
Usa PoliteHttp (User-Agent identificado, robots.txt, limite por host). Não escreve nada no banco."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import feedparser

from radar.collectors.base import CollectorError
from radar.collectors.http import PoliteHttp

FEED_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml"]
NEWSROOM_PATHS = ["/imprensa", "/sala-de-imprensa", "/noticias", "/blog", "/newsroom", "/press", "/ri", "/investidores"]
_ALT = re.compile(r'<link[^>]+rel=["\']alternate["\'][^>]*>', re.I)
_TYPE = re.compile(r'type=["\']application/(?:rss|atom)\+xml["\']', re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_SITEMAP_LINE = re.compile(r"^\s*sitemap:\s*(\S+)", re.I | re.M)


@dataclass
class Discovery:
    domain: str
    reachable: bool = False
    robots: str = "?"
    feeds: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    newsroom: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _try(http: PoliteHttp, url: str, d: Discovery):
    try:
        return http.get(url)
    except CollectorError as e:
        if e.code not in ("http404", "http403", "http410"):
            d.errors.append(f"{url}: {e}")
        return None


def discover(domain: str, http: PoliteHttp) -> Discovery:
    d = Discovery(domain)
    base = f"https://{domain}"
    home = _try(http, base + "/", d)
    if home is None:
        d.robots = "bloqueado/indisponível" if any("robots" in e for e in d.errors) else "?"
        return d
    d.reachable = True
    html = home.content.decode("utf-8", "ignore")
    for tag in _ALT.findall(html):
        if _TYPE.search(tag) and (m := _HREF.search(tag)):
            d.feeds.append(urljoin(base + "/", m.group(1)))
    robots = _try(http, base + "/robots.txt", d)
    d.robots = "ok" if robots else "sem robots.txt"
    if robots:
        d.sitemaps += _SITEMAP_LINE.findall(robots.content.decode("utf-8", "ignore"))
    for path in FEED_PATHS:
        if base + path in d.feeds or len(d.feeds) >= 3:
            continue
        r = _try(http, base + path, d)
        if r and feedparser.parse(r.content).entries:
            d.feeds.append(base + path)
    for path in SITEMAP_PATHS:
        if any(path in s for s in d.sitemaps):
            continue
        r = _try(http, base + path, d)
        if r and (b"<urlset" in r.content[:2000] or b"<sitemapindex" in r.content[:2000]):
            d.sitemaps.append(base + path)
    for path in NEWSROOM_PATHS:
        if _try(http, base + path, d):
            d.newsroom.append(base + path)
    d.feeds = list(dict.fromkeys(d.feeds))
    d.sitemaps = list(dict.fromkeys(d.sitemaps))
    return d
