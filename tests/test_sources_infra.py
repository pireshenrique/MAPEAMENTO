import calendar
import csv
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from radar.collectors.base import CollectorError, SourceCollector
from radar.collectors.cvm_ipe import CvmIpeCollector
from radar.collectors.discovery import discover
from radar.collectors.http import PoliteHttp
from radar.collectors.registry import build_collectors
from radar.collectors.rss import RSSCollector
from radar.db.repositories import SourceRepository
from radar.pipeline.match import match_all
from radar.pipeline.normalize import normalize
from radar.settings import EnvSettings, HttpConfig, SourceConfig, load_config
from tests.conftest import NOW

FEED = Path("tests/fixtures/feed_sample.xml").read_bytes()
SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def http(handler, **cfg):
    c = HttpConfig(min_delay_seconds=cfg.pop("delay", 0), respect_robots=cfg.pop("robots", False), **cfg)
    return PoliteHttp(c, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


# ---------- config / contrato ----------
APPROVED_CATEGORIES = ["Fato Relevante", "Comunicado ao Mercado", "Aviso aos Acionistas", "Reunião da Administração",
                       "Assembleia", "Comunicação sobre Transação entre Partes Relacionadas", "Dados Econômico-Financeiros"]


def test_only_pilot_sources_are_enabled_and_verified(config):
    ids = {s.id for s in config.sources}
    assert {"newsapi", "cvm-dexco", "infomoney"} <= ids
    pilot = {"cvm-dexco", "braziljournal", "neofeed", "seudinheiro"}           # piloto de 7 dias (Fase 10)
    assert {s.id for s in config.sources if s.enabled} == pilot                # nenhuma outra fonte habilitada
    assert {s.id for s in config.sources if s.verified} == pilot
    assert {s.scope for s in config.sources if s.type == "rss"} == {"feed"}
    assert next(s for s in config.sources if s.type == "newsapi").scope == "per_competitor"


def test_cvm_dexco_category_filter_is_the_approved_one(config):
    opts = next(s for s in config.sources if s.id == "cvm-dexco").options
    assert opts["company_name_contains"] == "DEXCO" and opts["include_categories"] == APPROVED_CATEGORIES
    assert not any("Valores Mobiliários" in c for c in opts["include_categories"])


def test_source_config_validation():
    with pytest.raises(ValueError):
        SourceConfig(id="x", type="rss")                        # rss exige url
    with pytest.raises(ValueError):
        SourceConfig(id="x", type="rss", url="https://a/feed", tier=9)


def test_registry_builds_only_enabled(config):
    cfg = config.model_copy(deep=True)
    assert {c.source_id for c in build_collectors(cfg)} == {"cvm-dexco", "braziljournal", "neofeed", "seudinheiro"}  # padrão: piloto
    for s in cfg.sources:
        if s.id == "infomoney":
            s.enabled = True
    got = build_collectors(cfg)
    assert {c.source_id for c in got} == {"infomoney", "cvm-dexco", "braziljournal", "neofeed", "seudinheiro"} and all(isinstance(c, SourceCollector) for c in got)
    assert all(c.scope == "feed" for c in got)


def test_sources_sync_preserves_metrics(session, config):
    repo = SourceRepository(session)
    repo.sync(config.sources)
    repo.record_fetch("infomoney", ok=True, status="ok", etag='"abc"', last_modified="Mon, 05 Oct 2026 10:00:00 GMT")
    repo.record_fetch("infomoney", ok=False, status="http503", error="boom")
    repo.sync(config.sources)                                    # re-sync não zera métricas
    r = repo.get("infomoney")
    assert (r.fetches_ok, r.fetches_failed, r.consecutive_failures, r.etag) == (1, 1, 1, '"abc"')


# ---------- HTTP educado ----------
def test_user_agent_and_conditional_headers_and_304():
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(304) if req.headers.get("if-none-match") == '"v1"' else httpx.Response(200, content=b"x", headers={"etag": '"v1"'})

    c = http(h)
    r1 = c.get("https://a.example/feed")
    assert r1.etag == '"v1"' and "CompetitiveIntelligenceRadar" in seen[0].headers["user-agent"]
    r2 = c.get("https://a.example/feed", etag=r1.etag)
    assert r2.not_modified and r2.status == 304


def test_robots_txt_disallow_blocks_and_404_allows():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /privado\n")
        return httpx.Response(200, content=b"ok")

    c = http(h, robots=True)
    assert c.get("https://a.example/publico").status == 200
    with pytest.raises(CollectorError) as e:
        c.get("https://a.example/privado/x")
    assert e.value.code == "robotsDisallowed"
    assert http(lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else httpx.Response(200, content=b"ok"), robots=True).get("https://b.example/x").status == 200


def test_robots_5xx_is_conservative():
    c = http(lambda r: httpx.Response(503) if r.url.path == "/robots.txt" else httpx.Response(200, content=b"ok"), robots=True)
    with pytest.raises(CollectorError):
        c.get("https://a.example/x")


def test_retry_on_503_then_ok_and_rate_limit_sleep():
    calls, sleeps = [], []

    def h(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=b"ok")

    c = PoliteHttp(HttpConfig(min_delay_seconds=2, respect_robots=False), client=httpx.Client(transport=httpx.MockTransport(h)),
                   sleep=sleeps.append, clock=lambda: 100.0)
    assert c.get("https://a.example/x").status == 200 and len(calls) == 3
    assert any(s == 1 for s in sleeps) and any(s == 2 for s in sleeps)   # backoff 1s, 2s; e/ou atraso por host


def test_non_retryable_error():
    with pytest.raises(CollectorError) as e:
        http(lambda r: httpx.Response(404)).get("https://a.example/x")
    assert e.value.code == "http404" and not e.value.retryable


# ---------- RSS ----------
def rss(handler=None, **kw):
    cfg = SourceConfig(id="portal", type="rss", url="https://portal-ficticio.example/feed", tier=3)
    return RSSCollector(cfg, http(handler or (lambda r: httpx.Response(200, content=FEED, headers={"etag": '"e1"'}))))


def test_rss_parses_items_with_contract_fields():
    items = rss().fetch(None, SINCE)
    assert [i.external_id for i in items] == ["guid-001", "guid-002"]       # item de setembro filtrado por `since`
    a = items[0]
    assert (a.source_id, a.source_type, a.body_status) == ("portal", "rss", "feed")
    assert "Texto completo da matéria" in a.body and a.tags == ["Indústria", "Lançamentos"]
    assert a.image_url.endswith("docol.jpg") and a.published_at == datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
    assert a.source_name == "Portal Fictício de Negócios"
    assert items[1].body_status == "none" and items[1].body is None


def test_rss_scope_and_conditional_state():
    c = rss(lambda r: httpx.Response(304) if r.headers.get("if-none-match") == '"e1"' else httpx.Response(200, content=FEED, headers={"etag": '"e1"'}))
    assert c.scope == "feed"
    assert len(c.fetch(None, SINCE)) == 2 and c.etag == '"e1"'
    assert c.fetch(None, SINCE) == [] and c.not_modified and c.last_status == "not_modified"


def test_rss_invalid_feed_raises():
    with pytest.raises(CollectorError) as e:
        rss(lambda r: httpx.Response(200, content=b"<html><body>nao e feed</body></html>")).fetch(None, SINCE)
    assert e.value.code == "invalidFeed"


def test_rss_items_flow_through_normalize_and_match(config):
    items = rss().fetch(None, SINCE)
    n = normalize(items[0], NOW)
    assert n.url_normalized == "https://portal-ficticio.example/docol-linha" and n.body_status == "feed" and "Texto completo" in n.raw_content
    assert [m.competitor for m in match_all(n, config.competitors, config.settings.matching)] == ["Docol"]
    assert match_all(normalize(items[1], NOW), config.competitors, config.settings.matching) == []   # Tigre futebol


# ---------- CVM / IPE ----------
def ipe_zip(rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["CNPJ_Companhia", "Nome_Companhia", "Codigo_CVM", "Categoria", "Tipo", "Especie", "Assunto", "Data_Referencia", "Data_Entrega", "Protocolo_Entrega", "Link_Download"])
    w.writerows(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("ipe_cia_aberta_2026.csv", buf.getvalue().encode("latin-1"))
    return out.getvalue()


def test_cvm_ipe_filters_company_and_dates(config):
    rows = [["1", "DEXCO S.A.", "1", "Fato Relevante", "-", "-", "Aquisição de ativos", "2026-10-01", "2026-10-02 09:30:00", "P1", "https://rad.cvm.example/p1"],
            ["2", "OUTRA S.A.", "2", "Fato Relevante", "-", "-", "x", "2026-10-01", "2026-10-02", "P2", "https://rad.cvm.example/p2"],
            ["1", "DEXCO S.A.", "1", "Comunicado ao Mercado", "-", "-", "Antigo", "2026-01-01", "2026-01-02", "P3", "https://rad.cvm.example/p3"]]
    cfg = SourceConfig(id="cvm-dexco", type="cvm_ipe", url="https://dados.example/ipe_{year}.zip", options={"company_name_contains": "dexco"})
    c = CvmIpeCollector(cfg, http(lambda r: httpx.Response(200, content=ipe_zip(rows), headers={"etag": '"z"'})))
    items = c.fetch(None, SINCE, datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert len(items) == 1 and items[0].external_id == "P1" and items[0].title == "DEXCO S.A.: Fato Relevante - Aquisição de ativos"
    assert items[0].published_at == datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc) and c.etag == '"z"'
    n = normalize(items[0], NOW)
    assert [m.competitor for m in match_all(n, config.competitors, config.settings.matching)][:1] == ["Dexco"]


def test_cvm_requires_company_and_rejects_bad_zip():
    with pytest.raises(CollectorError):
        CvmIpeCollector(SourceConfig(id="c", type="cvm_ipe", url="https://x/{year}.zip"), http(lambda r: httpx.Response(200)))
    cfg = SourceConfig(id="c", type="cvm_ipe", url="https://x/{year}.zip", options={"company_name_contains": "DEXCO"})
    with pytest.raises(CollectorError) as e:
        CvmIpeCollector(cfg, http(lambda r: httpx.Response(200, content=b"nao-zip"))).fetch(None, SINCE, NOW)
    assert e.value.code == "invalidIpe"


# ---------- descoberta ----------
def test_discovery_finds_feed_sitemap_newsroom():
    def h(req):
        p = req.url.path
        if p == "/": return httpx.Response(200, text='<html><link rel="alternate" type="application/rss+xml" href="/noticias/feed.xml"></html>')
        if p == "/robots.txt": return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://site.example/sm.xml\n")
        if p == "/noticias/feed.xml": return httpx.Response(200, content=FEED)
        if p == "/imprensa": return httpx.Response(200, text="<html><title>Imprensa</title><body>" + "<article><time datetime='2026-10-01'>01/10/2026</time> Release da empresa sobre lançamento de produto</article>" * 20 + "</body></html>")
        return httpx.Response(404)

    d = discover("site.example", http(h))
    assert d.reachable and d.feeds == ["https://site.example/noticias/feed.xml"]
    assert d.sitemaps == ["https://site.example/sm.xml"] and d.newsroom == ["https://site.example/imprensa"] and d.robots == "ok"


def test_discovery_unreachable_domain():
    def h(req):
        raise httpx.ConnectError("blocked")

    d = discover("down.example", http(h))
    assert not d.reachable and d.errors


def test_cvm_collector_with_configured_filter_excludes_insider_positions(config):
    cfg = next(x for x in config.sources if x.id == "cvm-dexco")
    row = lambda cat, i: ["1", "DEXCO S.A.", "1", cat, "-", "-", f"Assunto {i}", "2026-10-01", "2026-10-02", f"P{i}", f"https://rad.example/{i}"]  # noqa: E731
    cats = APPROVED_CATEGORIES + ["Valores Mobiliários negociados e detidos (art. 11 da Instr. CVM nº 358)", "Outra Categoria"]
    c = CvmIpeCollector(cfg, http(lambda r: httpx.Response(200, content=ipe_zip([row(cat, i) for i, cat in enumerate(cats)]))))
    items = c.fetch(None, SINCE, datetime(2026, 10, 6, tzinfo=timezone.utc))
    assert [i.tags[0] for i in items] == APPROVED_CATEGORIES               # 7 aprovadas; insiders e outras ficam de fora
