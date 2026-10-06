"""Descoberta (somente leitura) de feeds, sitemaps e páginas de imprensa de um domínio.
Usa PoliteHttp (User-Agent identificado, robots.txt, limite por host). Não escreve nada no banco.

Cuidados contra falsos positivos de "newsroom":
- Host final: segue redirects (apex -> www etc.) e usa o host final em todas as sondagens.
- Catch-all: um caminho inexistente que responde 200 revela site genérico (SPA / fallback). Candidatos cujo conteúdo é
  praticamente idêntico ao do caminho inexistente (ou à home) NÃO são tratados como newsroom."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import feedparser
from rapidfuzz import fuzz

from radar.collectors.base import CollectorError
from radar.collectors.http import HttpResult, PoliteHttp

FEED_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml"]
NEWSROOM_PATHS = ["/imprensa", "/sala-de-imprensa", "/noticias", "/blog", "/newsroom", "/press", "/ri", "/investidores"]
PROBE_PATH = "/radar-probe-inexistente-7f3a9c"      # caminho que não deve existir em nenhum site
MIN_TEXT_CHARS = 200                                 # abaixo disso o HTML não traz conteúdo (renderizado por JavaScript)
SIMILARITY_LIMIT = 90.0                              # % de similaridade para considerar "mesmo conteúdo"
_ALT = re.compile(r'<link[^>]+rel=["\']alternate["\'][^>]*>', re.I)
_TYPE = re.compile(r'type=["\']application/(?:rss|atom)\+xml["\']', re.I)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_SITEMAP_LINE = re.compile(r"^\s*sitemap:\s*(\S+)", re.I | re.M)
_SCRIPT_STYLE = re.compile(r"<(script|style|title)\b.*?</\1>", re.I | re.S)   # <title> reflete o caminho; ignorar
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_NEWS_SIGNALS = re.compile(
    r"<time\b|<article\b|datetime=|\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro) de \d{4}", re.I)


@dataclass
class Discovery:
    domain: str                                        # como foi informado
    final_host: str | None = None                      # host após redirects
    home_final_url: str | None = None
    reachable: bool = False
    robots: str = "?"
    catch_all: bool = False                            # caminho inexistente respondeu 200
    feeds: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    newsroom: list[str] = field(default_factory=list)  # distintas, com texto no HTML e sinais de notícia (datas/<article>/<time>)
    weak: list[str] = field(default_factory=list)      # distintas e com texto, mas SEM sinais de notícia (ex.: listagem de produtos)
    rejected: list[str] = field(default_factory=list)  # "caminho: motivo" (genérica, redireciona p/ home...)
    duplicate_of: str | None = None                    # outro domínio informado com o mesmo host final
    errors: list[str] = field(default_factory=list)


def normalize_domain(value: str) -> str:
    """'https://WWW.Exemplo.com.br/x' -> 'www.exemplo.com.br' (apenas o host)."""
    v = value.strip().lower()
    if "//" in v:
        v = urlsplit(v).hostname or v
    return v.split("/")[0].split(":")[0]


def _fingerprint(content: bytes) -> str:
    """Texto comparável: sem scripts/estilos/<title>/tags/números/espaços, limitado a 20k caracteres."""
    text = _SCRIPT_STYLE.sub(" ", content.decode("utf-8", "ignore"))
    text = _DIGITS.sub("", _TAGS.sub(" ", text))
    return _WS.sub(" ", text).strip().lower()[:20000]


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if not a or not b:
        return False
    return fuzz.ratio(a, b) >= SIMILARITY_LIMIT


def _try(http: PoliteHttp, url: str, d: Discovery) -> HttpResult | None:
    try:
        return http.get(url)
    except CollectorError as e:
        if e.code not in ("http404", "http403", "http410"):
            d.errors.append(f"{url}: {e}")
        return None


def discover(domain: str, http: PoliteHttp, seen: dict[str, "Discovery"] | None = None) -> Discovery:
    domain = normalize_domain(domain)
    d = Discovery(domain)
    home = _try(http, f"https://{domain}/", d)
    if home is None:
        d.robots = "bloqueado/indisponível" if any("robots" in e for e in d.errors) else "?"
        return d
    final = urlsplit(home.final_url or f"https://{domain}/")
    d.final_host, d.home_final_url, d.reachable = final.hostname or domain, home.final_url, True
    if seen is not None:
        if d.final_host in seen:
            d.duplicate_of = seen[d.final_host].domain
            return d
        seen[d.final_host] = d
    base = f"{final.scheme}://{final.netloc}"          # todas as sondagens usam o host FINAL
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
            d.feeds.append(r.final_url or base + path)
    for path in SITEMAP_PATHS:
        if any(path in s for s in d.sitemaps):
            continue
        r = _try(http, base + path, d)
        if r and (b"<urlset" in r.content[:2000] or b"<sitemapindex" in r.content[:2000]):
            d.sitemaps.append(r.final_url or base + path)

    # --- páginas de imprensa, com detecção de catch-all ---
    probe = _try(http, base + PROBE_PATH, d)
    d.catch_all = probe is not None                      # inexistente respondeu 200 => fallback genérico
    probe_fp = _fingerprint(probe.content) if probe else None
    home_fp = _fingerprint(home.content)
    for path in NEWSROOM_PATHS:
        r = _try(http, base + path, d)
        if r is None:
            continue
        fp = _fingerprint(r.content)
        final_path = urlsplit(r.final_url).path.rstrip("/")
        if final_path in ("", "/") or (r.final_url.rstrip("/") == (home.final_url or "").rstrip("/")):
            d.rejected.append(f"{path}: redireciona para a home")
        elif probe_fp is not None and _same(fp, probe_fp):
            d.rejected.append(f"{path}: catch-all (igual ao caminho inexistente)")
        elif _same(fp, home_fp):
            d.rejected.append(f"{path}: idêntica à home")
        elif len(fp) < MIN_TEXT_CHARS:
            d.rejected.append(f"{path}: sem conteúdo no HTML (renderizado por JavaScript; inviável para coleta simples)")
        elif _NEWS_SIGNALS.search(r.content.decode("utf-8", "ignore")):
            d.newsroom.append(r.final_url or base + path)
        else:
            d.weak.append(r.final_url or base + path)
    d.feeds = list(dict.fromkeys(d.feeds))
    d.sitemaps = list(dict.fromkeys(d.sitemaps))
    d.newsroom = list(dict.fromkeys(d.newsroom))
    d.weak = list(dict.fromkeys(d.weak))
    return d
