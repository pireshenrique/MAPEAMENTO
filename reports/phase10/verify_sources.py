"""Verificação read-only dos achados da descoberta (Fase 10.1). Usa PoliteHttp (UA identificado, robots, delay)."""
import calendar, json, re, sys, hashlib
from datetime import datetime, timezone
import feedparser
sys.path.insert(0, ".")
from radar.collectors.base import CollectorError
from radar.collectors.http import PoliteHttp
from radar.settings import HttpConfig
http = PoliteHttp(HttpConfig(min_delay_seconds=1.0, respect_robots=True))
out = {}
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

def get(url):
    try:
        r = http._raw_get(url, {}) if False else http.get(url)
        return r
    except CollectorError as e:
        return str(e)

def head(url):  # status/final url sem exigir 200
    import httpx
    try:
        r = http._client.get(url, headers={"User-Agent": http.cfg.user_agent}); http._throttle(httpx.URL(url).host)
        return r
    except Exception as e:
        return e

def describe(url):
    r = head(url)
    if isinstance(r, Exception): return {"url": url, "erro": f"{type(r).__name__}"}
    t = TITLE.search(r.text[:20000]); 
    return {"url": url, "http": r.status_code, "final": str(r.url), "ctype": r.headers.get("content-type", "")[:40],
            "bytes": len(r.content), "title": (t.group(1).strip()[:80] if t else None), "sha": hashlib.sha1(r.content[:5000]).hexdigest()[:8]}

# 1) FEEDS (ri.tigre)
feeds = {}
for u in ["https://ri.tigre.com.br/feed", "https://ri.tigre.com.br/feed/", "https://ri.tigre.com.br/rss"]:
    r = head(u)
    if isinstance(r, Exception): feeds[u] = {"erro": type(r).__name__}; continue
    p = feedparser.parse(r.content)
    dates = [calendar.timegm(e.published_parsed) for e in p.entries if e.get("published_parsed")]
    feeds[u] = {"http": r.status_code, "final": str(r.url), "ctype": r.headers.get("content-type"), "versao": p.get("version"),
                "titulo_feed": p.feed.get("title"), "itens": len(p.entries),
                "mais_recente": datetime.fromtimestamp(max(dates), timezone.utc).isoformat() if dates else None,
                "mais_antigo": datetime.fromtimestamp(min(dates), timezone.utc).isoformat() if dates else None,
                "guid": [e.get("id") for e in p.entries[:3]], "corpo_completo": [bool(e.get("content")) for e in p.entries[:5]],
                "exemplos": [(e.get("title"), e.get("link")) for e in p.entries[:3]], "etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified")}
out["feeds"] = feeds

# 2) SITEMAPS
sm = {}
def parse_sitemap(url, depth=0):
    r = head(url)
    if isinstance(r, Exception): return {"url": url, "erro": type(r).__name__}
    txt = r.text
    info = {"url": url, "http": r.status_code, "final": str(r.url), "tipo": "index" if "<sitemapindex" in txt[:3000] else "urlset" if "<urlset" in txt[:3000] else "outro"}
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", txt)
    mods = re.findall(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", txt)
    info["locs"] = len(locs); info["lastmod_max"] = max(mods) if mods else None
    if info["tipo"] == "index": info["filhos"] = locs[:12]
    else: info["amostra_noticia"] = [l for l in locs if re.search(r"notic|blog|imprensa|press|comunicad|fato|news", l, re.I)][:5]; info["total_urls_noticia"] = len([l for l in locs if re.search(r"notic|blog|imprensa|press|comunicad|fato|news", l, re.I)])
    return info
for u in ["https://www.deca.com.br/sitemap_index.xml", "https://www.docol.com.br/sitemap.xml", "https://www.tigre.com.br/sitemap_index.xml",
          "https://ri.tigre.com.br/sitemap_index.xml", "http://dev.celite.com.br:80/sitemap.xml", "https://www.celite.com.br/sitemap.xml",
          "https://br.kohler.com/sitemap.xml", "https://www.dex.co/sitemap_index.xml", "https://ri.dex.co/sitemap_index.xml"]:
    sm[u] = parse_sitemap(u)
out["sitemaps"] = sm

# 3) PÁGINAS de imprensa: detectar catch-all comparando com caminho inexistente
pages = {}
for base, paths in {"https://www.docol.com.br": ["/", "/imprensa", "/noticias", "/blog", "/zz-nao-existe-9x7"],
                    "https://br.kohler.com": ["/", "/imprensa", "/noticias", "/blog", "/zz-nao-existe-9x7"],
                    "https://www.deca.com.br": ["/", "/blog", "/zz-nao-existe-9x7"], "https://www.celite.com.br": ["/", "/blog", "/zz-nao-existe-9x7"],
                    "https://www.dex.co": ["/", "/imprensa", "/noticias", "/press", "/zz-nao-existe-9x7"], "https://ri.tigre.com.br": ["/", "/noticias", "/zz-nao-existe-9x7"],
                    "https://www.tigre.com.br": ["/", "/zz-nao-existe-9x7"], "https://ri.dex.co": ["/", "/zz-nao-existe-9x7"]}.items():
    pages[base] = [describe(base + p) for p in paths]
out["paginas"] = pages
json.dump(out, open("reports/phase10/verify.json", "w"), ensure_ascii=False, indent=1)
print("ok")
