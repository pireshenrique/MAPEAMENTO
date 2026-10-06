from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from radar.api.app import create_app
from radar.bootstrap import Context
from radar.db.engine import make_engine, make_session_factory, session_scope
from radar.db.queries import NewsFilters, kpis, search_news, stats
from radar.db.repositories import CategoryRepository, CompetitorRepository, NewsRepository
from radar.db.tables import Base
from radar.domain.models import DupStatus
from tests.conftest import NOW
from tests.test_persistence import make_article

A = dict(sentiment="neutral", subcategory=None, key_points=["p"], strategic_reason="porque sim", model_used="fake",
         prompt_version="v1", raw_response="{}")


@pytest.fixture
def ctx(tmp_path, config):
    engine = make_engine(f"sqlite:///{tmp_path}/api.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as s:
        comps = CompetitorRepository(s).sync(config.competitors)
        CategoryRepository(s).sync(config.categories)
        repo = NewsRepository(s)

        def add(i, comp, title, hours, source, dup=DupStatus.UNIQUE, analysis=None, desc="desc"):
            n = repo.add(make_article(f"https://{source}.com/{i}", title, competitor_name=comp, source_name=source,
                                      source_domain=f"{source}.com", description=desc,
                                      published_at=NOW - timedelta(hours=hours)), comps[comp].id, dup_status=dup)
            if analysis:
                repo.save_analysis(n, **A, **analysis)
            return n

        add(1, "Docol", "Docol lança linha de metais premium", 2, "valor",
            analysis=dict(is_relevant=True, relevance_score=5, competitive_impact="negative", category="Lançamento",
                          summary="Docol lançou linha; compete com Lorenzetti."))
        add(2, "Roca", "Roca amplia fábrica em Pernambuco", 30, "exame",
            analysis=dict(is_relevant=True, relevance_score=4, competitive_impact="negative", category="Investimento",
                          summary="Roca investe em capacidade."))
        add(3, "Docol", "Docol patrocina evento de design", 24 * 5, "valor",
            analysis=dict(is_relevant=False, relevance_score=1, competitive_impact="neutral", category="Marketing",
                          summary="Ação institucional sem efeito."))
        add(4, "Deca", "Deca em 100% de desconto é_teste", 3, "exame")                       # sem análise
        add(5, "Docol", "Docol lança linha de metais premium", 2, "outro", dup=DupStatus.DUPLICATE)  # oculta
        add(6, "Tigre", "Tigre inaugura centro 50% maior", 10, "valor", dup=DupStatus.POSSIBLE,
            analysis=dict(is_relevant=True, relevance_score=3, competitive_impact="positive", category="Expansão",
                          summary="Tigre expande distribuição."))
    return Context(config, engine, factory)


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx))


def titles(r):
    return [i["title"] for i in r.json()["items"]]


def test_healthz_and_default_hides_duplicates(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/api/news")
    assert r.status_code == 200 and r.json()["total"] == 5
    assert "outro" not in {i["source_name"] for i in r.json()["items"]}


def test_include_duplicates(client):
    assert client.get("/api/news?include_duplicates=true").json()["total"] == 6


def test_filter_competitor_and_category(client):
    assert client.get("/api/news?competitor=Docol").json()["total"] == 2
    assert titles(client.get("/api/news?category=Investimento")) == ["Roca amplia fábrica em Pernambuco"]


def test_filter_relevance_impact_source(client):
    assert client.get("/api/news?relevance_min=4").json()["total"] == 2
    assert client.get("/api/news?impact=positive").json()["total"] == 1
    assert client.get("/api/news?source=exame").json()["total"] == 2
    assert client.get("/api/news?source=valor.com").json()["total"] == 3


def test_filter_period(client):
    # NOW é fixo em 2026-10-06; usa intervalo absoluto
    assert client.get("/api/news?date_from=2026-10-06&date_to=2026-10-06").json()["total"] == 3
    assert client.get("/api/news?date_to=2026-10-04").json()["total"] == 1


def test_text_search_title_summary_and_wildcards(client):
    assert client.get("/api/news?q=fábrica").json()["total"] == 1
    assert client.get("/api/news?q=compete com lorenzetti").json()["total"] == 1  # busca no resumo da IA
    assert client.get("/api/news?q=100%25").json()["total"] == 1                   # % tratado como literal
    assert client.get("/api/news?q=%25").json()["total"] == 2  # só os títulos com "%" literal; não é curinga
    assert client.get("/api/news?q=_").json()["total"] == 1      # "_" literal (só em "é_teste")
    assert client.get("/api/news?q=inexistente").json()["total"] == 0


def test_combined_filters_and_pagination(client):
    r = client.get("/api/news?competitor=Docol&relevance_min=3&q=metais")
    assert r.json()["total"] == 1
    p1 = client.get("/api/news?page_size=2&page=1").json()
    p3 = client.get("/api/news?page_size=2&page=3").json()
    assert len(p1["items"]) == 2 and len(p3["items"]) == 1 and p1["total"] == 5


def test_sort_by_relevance(client):
    r = client.get("/api/news?sort=relevance&only_analyzed=true").json()["items"]
    scores = [i["analysis"]["relevance_score"] for i in r]
    assert scores == sorted(scores, reverse=True) and len(scores) == 4


def test_invalid_params_rejected(client):
    assert client.get("/api/news?relevance_min=9").status_code == 422
    assert client.get("/api/news?impact=bom").status_code == 422
    assert client.get("/api/news?sort=hack").status_code == 422


def test_detail_and_404(client):
    d = client.get("/api/news/1").json()
    assert d["analysis"]["strategic_reason"] and d["analysis"]["model_used"] == "fake"
    assert d["competitor"] == "Docol" and [x["id"] for x in d["duplicates"]] == []
    assert client.get("/api/news/999").status_code == 404
    assert client.get("/api/news/4").json()["analysis"] is None


def test_kpis(ctx):
    with session_scope(ctx.session_factory) as s:
        k = kpis(s, now=NOW)
    assert k["collected"] == 5 and k["relevant"] == 3 and k["high_relevance"] == 2
    assert k["competitors_monitored"] == 7
    assert k["last_24h"] == 3 and k["last_7d"] == 5   # exclui a duplicata e conta por data de publicação
    assert k["pending_analysis"] == 1


def test_facets_and_stats(client, ctx):
    f = client.get("/api/filters").json()
    assert "Docol" in f["competitors"] and "Produto" in f["categories"] and set(f["sources"]) >= {"valor", "exame"}
    with session_scope(ctx.session_factory) as s:
        st = stats(s, 30, now=NOW)
    assert st["total"] == 5 and st["analyzed"] == 4
    assert st["by_competitor"][0] == {"label": "Docol", "count": 2}
    assert sum(d["count"] for d in st["timeline"]) == 5 and len(st["timeline"]) == 31
    assert [r["count"] for r in st["relevance"]] == [1, 0, 1, 1, 1]
    assert client.get("/api/stats").status_code == 200 and client.get("/api/kpis").status_code == 200


def test_no_secrets_in_responses(client):
    for url in ("/api/kpis", "/api/filters", "/api/news", "/api/openapi.json"):
        assert "api_key" not in client.get(url).text.lower()
