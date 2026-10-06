import json, re, sys, calendar
from datetime import datetime, timezone
import feedparser, httpx
sys.path.insert(0, ".")
from radar.collectors.http import PoliteHttp
from radar.collectors.base import CollectorError
from radar.settings import HttpConfig
http = PoliteHttp(HttpConfig(min_delay_seconds=1.0, respect_robots=True))
res = {}
def g(url):
    if not http.allowed(url): return None, "robots.txt NÃO permite"
    http._throttle(httpx.URL(url).host)
    try: return http._client.get(url, headers={"User-Agent": http.cfg.user_agent}), None
    except Exception as e: return None, type(e).__name__
def sm(url, pat=r".", n=4):
    r, err = g(url)
    if r is None: return {"url": url, "erro": err}
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text); mods = re.findall(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", r.text)
    sel = [l for l in locs if re.search(pat, l, re.I)]
    return {"url": url, "http": r.status_code, "urls": len(locs), "selecionadas": len(sel), "lastmod_max": max(mods) if mods else None,
            "lastmod_min": min(mods) if mods else None, "amostra": sel[:n]}
def feed(url):
    r, err = g(url)
    if r is None: return {"url": url, "erro": err}
    p = feedparser.parse(r.content); d = [calendar.timegm(e.published_parsed) for e in p.entries if e.get("published_parsed")]
    return {"url": url, "http": r.status_code, "final": str(r.url), "ctype": r.headers.get("content-type", "")[:30], "versao": p.get("version"),
            "itens": len(p.entries), "mais_recente": datetime.fromtimestamp(max(d), timezone.utc).date().isoformat() if d else None,
            "guid": [e.get("id") for e in p.entries[:2]], "corpo": [bool(e.get("content")) for e in p.entries[:3]], "ex": [e.get("title") for e in p.entries[:3]]}
res["sitemaps"] = [sm("https://www.dex.co/post-sitemap.xml", r"/(noticia|imprensa|202)", 5), sm("https://ri.dex.co/page-sitemap.xml", r"comunic|fato|notic|release|resultado", 6),
    sm("https://ri.tigre.com.br/post-sitemap.xml", r".", 5), sm("https://www.tigre.com.br/medias-posts-sitemap.xml", r".", 5),
    sm("https://www.deca.com.br/sitemap-blog.xml", r".", 3)]
res["feeds"] = [feed("https://www.dex.co/noticias/feed/"), feed("https://www.dex.co/category/noticias/feed/"), feed("https://www.dex.co/?feed=rss2"),
    feed("https://ri.dex.co/feed/"), feed("https://www.deca.com.br/blog/feed/"), feed("https://www.celite.com.br/blog/feed"), feed("https://www.docol.com.br/blog/feed")]
# WordPress REST (estruturado) em dex.co
r, err = g("https://www.dex.co/wp-json/wp/v2/posts?per_page=3&_fields=id,date,link,title")
res["wp_json_dex"] = {"http": r.status_code if r is not None else err, "ctype": r.headers.get("content-type", "")[:30] if r is not None else None,
                      "corpo": r.text[:400] if r is not None else None}
# robots.txt relevantes
rob = {}
for h in ["www.dex.co", "ri.dex.co", "www.deca.com.br", "www.docol.com.br", "br.kohler.com", "www.celite.com.br", "ri.tigre.com.br", "dados.cvm.gov.br"]:
    r, err = g(f"https://{h}/robots.txt")
    rob[h] = {"http": r.status_code if r is not None else err, "disallow_count": len(re.findall(r"(?im)^disallow:\s*\S", r.text)) if r is not None else None,
              "tem_sitemap": bool(re.search(r"(?i)^sitemap:", r.text, re.M)) if r is not None else None,
              "bloqueia_tudo": bool(re.search(r"(?im)^user-agent:\s*\*\s*\n(?:.*\n)*?disallow:\s*/\s*$", r.text)) if r is not None else None}
res["robots"] = rob
json.dump(res, open("reports/phase10/verify2.json", "w"), ensure_ascii=False, indent=1)
for k in ("sitemaps", "feeds"):
    for x in res[k]: print(k, json.dumps(x, ensure_ascii=False)[:420])
print("wp", json.dumps(res["wp_json_dex"], ensure_ascii=False)[:500]); print("robots", json.dumps(rob))
