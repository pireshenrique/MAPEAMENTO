import httpx
import pytest

from radar.collectors.discovery import discover, normalize_domain
from radar.collectors.http import PoliteHttp
from radar.settings import HttpConfig

SHELL = "<html><head><title>App</title></head><body>" + "<div>aplicação genérica de página única com menu e rodapé</div>" * 40 + "</body></html>"
HOME = "<html><head><title>Home</title></head><body>" + "<p>Bem-vindo à empresa, produtos e serviços para você</p>" * 40 + "</body></html>"
NEWS = ("<html><head><title>Notícias</title></head><body>"
        + "<article><time datetime='2026-10-01'>01/10/2026</time> Lançamento de produto, investimento em fábrica e resultados</article>" * 40
        + "</body></html>")
LISTING = ("<html><head><title>Press</title></head><body>"
           + "<div class='produto'>Torneira linha Press cor cromada filtros por categoria preço relevância</div>" * 40 + "</body></html>")


def run(handler, domain="site.example", seen=None):
    c = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return discover(domain, PoliteHttp(HttpConfig(min_delay_seconds=0, respect_robots=False), client=c, sleep=lambda s: None), seen)


def test_normalize_domain():
    assert normalize_domain("https://WWW.Exemplo.com.br/x?y=1") == "www.exemplo.com.br"
    assert normalize_domain(" exemplo.com:8080/ ") == "exemplo.com"


def test_spa_catch_all_is_not_a_newsroom():
    """Docol/Kohler: caminhos existentes e inexistentes devolvem o mesmo conteúdo."""
    def h(req):
        return httpx.Response(404) if req.url.path in ("/robots.txt", "/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/sitemap.xml", "/sitemap_index.xml") \
            else httpx.Response(200, text=HOME if req.url.path == "/" else SHELL)

    d = run(h)
    assert d.reachable and d.catch_all and d.newsroom == []
    assert len(d.rejected) == 8 and all("catch-all" in r for r in d.rejected)


def test_catch_all_ignores_irrelevant_numbers_and_scripts():
    def h(req):
        if req.url.path == "/": return httpx.Response(200, text=HOME)
        if req.url.path in ("/robots.txt",) or req.url.path.endswith((".xml", "/feed", "/feed/", "/rss")): return httpx.Response(404)
        return httpx.Response(200, text=SHELL + f"<script>var nonce={hash(req.url.path) % 99999}</script> <span>{len(req.url.path)}</span>")

    assert run(h).newsroom == []


def test_real_newsroom_is_accepted_when_unknown_path_is_404():
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/noticias": return httpx.Response(200, text=NEWS)
        return httpx.Response(404)

    d = run(h)
    assert not d.catch_all and d.newsroom == ["https://site.example/noticias"] and d.rejected == []


def test_catch_all_site_with_a_genuinely_different_page_keeps_that_page():
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/blog": return httpx.Response(200, text=NEWS)
        if p == "/robots.txt" or p.endswith((".xml", "/feed", "/feed/", "/rss")): return httpx.Response(404)
        return httpx.Response(200, text=SHELL)

    d = run(h)
    assert d.catch_all and d.newsroom == ["https://site.example/blog"] and len(d.rejected) == 7


def test_page_identical_to_home_or_redirecting_home_is_rejected():
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/imprensa": return httpx.Response(301, headers={"location": "/"})
        if p == "/noticias": return httpx.Response(200, text=HOME)          # mesma página da home
        if p == "/blog": return httpx.Response(200, text=NEWS)
        return httpx.Response(404)

    d = run(h)
    assert d.newsroom == ["https://site.example/blog"]
    assert any(r.startswith("/imprensa") and "home" in r for r in d.rejected)
    assert any(r.startswith("/noticias") and "idêntica" in r for r in d.rejected)


def test_apex_to_www_redirect_uses_final_host_for_probes():
    hosts = []

    def h(req):
        hosts.append(req.url.host)
        if req.url.host == "site.example": return httpx.Response(301, headers={"location": f"https://www.site.example{req.url.path}"})
        return httpx.Response(200, text=HOME) if req.url.path == "/" else (httpx.Response(200, text=NEWS) if req.url.path == "/imprensa" else httpx.Response(404))

    d = run(h)
    assert d.final_host == "www.site.example" and d.home_final_url == "https://www.site.example/"
    assert d.newsroom == ["https://www.site.example/imprensa"]
    assert hosts.count("site.example") == 1                                  # só a home passou pelo apex
    assert set(hosts) == {"site.example", "www.site.example"}


def test_same_final_host_is_not_probed_twice():
    calls = []

    def h(req):
        calls.append((req.url.host, req.url.path))
        if req.url.host == "site.example": return httpx.Response(301, headers={"location": f"https://www.site.example{req.url.path}"})
        return httpx.Response(200, text=HOME) if req.url.path == "/" else httpx.Response(404)

    seen: dict = {}
    first = run(h, "site.example", seen)
    n = len(calls)
    second = run(h, "www.site.example", seen)
    assert first.duplicate_of is None and second.duplicate_of == "site.example" and len(calls) == n + 1   # só a home


def test_unreachable_domain_has_no_final_host():
    def h(req):
        raise httpx.ConnectError("blocked")

    d = run(h)
    assert not d.reachable and d.final_host is None and d.errors


def test_http_result_exposes_final_url():
    def h(req):
        return httpx.Response(301, headers={"location": "https://b.example/x"}) if req.url.host == "a.example" else httpx.Response(200, content=b"ok")

    c = httpx.Client(transport=httpx.MockTransport(h), follow_redirects=True)
    r = PoliteHttp(HttpConfig(min_delay_seconds=0, respect_robots=False), client=c, sleep=lambda s: None).get("https://a.example/")
    assert r.final_url == "https://b.example/x"


def test_catch_all_pages_that_differ_only_in_title_are_detected():
    """Caso real da Docol: texto curto; as páginas só diferem no <title>, que reflete o caminho."""
    def page(path):
        return f"<html><head><title>{path.strip('/')} - Docol</title></head><body><p>institucional ajuda suporte onde encontrar downloads</p><p>menu rodapé contato</p></body></html>"

    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/robots.txt" or p.endswith((".xml", "/feed", "/feed/", "/rss")): return httpx.Response(404)
        return httpx.Response(200, text=page(p))

    d = run(h)
    assert d.catch_all and d.newsroom == [] and len(d.rejected) == 8


def test_js_rendered_empty_page_is_not_a_collectable_newsroom():
    """Rota reconhecida pelo SPA, mas sem texto no HTML (conteúdo montado por JavaScript)."""
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/blog": return httpx.Response(200, text="<html><head><title>Blog</title></head><body><div id='root'></div></body></html>")
        if p == "/noticias": return httpx.Response(200, text=NEWS)
        if p == "/robots.txt" or p.endswith((".xml", "/feed", "/feed/", "/rss")): return httpx.Response(404)
        return httpx.Response(200, text="<html><body>" + "<p>Página não encontrada. Possíveis causas: endereço digitado errado</p>" * 6 + "</body></html>")

    d = run(h)
    assert d.newsroom == ["https://site.example/noticias"]
    assert any(r.startswith("/blog") and "JavaScript" in r for r in d.rejected)


def test_distinct_page_without_news_signals_goes_to_weak_not_newsroom():
    """Caso Docol /press: listagem de produtos (página distinta, mas sem datas/<article>/<time>)."""
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text=HOME)
        if p == "/press": return httpx.Response(200, text=LISTING)
        if p == "/noticias": return httpx.Response(200, text=NEWS)
        return httpx.Response(404)

    d = run(h)
    assert d.newsroom == ["https://site.example/noticias"] and d.weak == ["https://site.example/press"]
