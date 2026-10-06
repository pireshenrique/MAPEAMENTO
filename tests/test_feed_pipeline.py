import csv
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from radar.collectors.base import CollectorError
from radar.collectors.http import PoliteHttp
from radar.collectors.rss import RSSCollector
from radar.db.engine import session_scope
from radar.db.repositories import CategoryRepository, CompetitorRepository, NewsRepository, SourceRepository
from radar.db.tables import News
from radar.pipeline.runner import run_collection
from radar.settings import HttpConfig, SourceConfig
from radar.sources_report import build_report, export_audit_sample
from sqlalchemy import select
from tests.conftest import NOW

FEED = Path("tests/fixtures/feed_sample.xml").read_bytes()


def collector(handler):
    cfg = SourceConfig(id="portal", type="rss", url="https://portal-ficticio.example/feed", tier=3)
    h = PoliteHttp(HttpConfig(min_delay_seconds=0, respect_robots=False),
                   client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    return RSSCollector(cfg, h)


@pytest.fixture
def db(session_factory, config):
    with session_scope(session_factory) as s:
        CompetitorRepository(s).sync(config.competitors); CategoryRepository(s).sync(config.categories)
        SourceRepository(s).sync(config.sources + [SourceConfig(id="portal", type="rss", url="https://portal-ficticio.example/feed", tier=3)])
    return session_factory


def run(db, config, col, **kw):
    with session_scope(db) as s:
        return run_collection(s, [col], config, now=NOW, days=7, **kw)


OK = lambda r: httpx.Response(200, content=FEED, headers={"etag": '"e1"'})  # noqa: E731


def test_feed_scope_fetches_once_and_matches_across_competitors(db, config):
    calls = []
    col = collector(lambda r: (calls.append(1), OK(r))[1])
    st = run(db, config, col)
    assert len(calls) == 1                                   # feed: UMA chamada, não uma por concorrente
    assert st.found == 2 and st.new == 1                     # Docol aceito; Tigre/futebol sem match
    assert st.by_source["portal"] == {"seen": 2, "matched": 1, "stored": 1}
    with session_scope(db) as s:
        n = s.scalar(select(News))
        assert (n.source_id, n.source_type, n.body_status, n.external_id) == ("portal", "rss", "feed", "guid-001")
        assert n.tags == ["Indústria", "Lançamentos"] and "Texto completo" in n.raw_content
        src = SourceRepository(s).get("portal")
        assert (src.fetches_ok, src.items_seen, src.items_matched, src.items_stored, src.etag) == (1, 2, 1, 1, '"e1"')


def test_second_run_uses_etag_and_external_id_dedup(db, config):
    seen = []

    def h(req):
        seen.append(req.headers.get("if-none-match"))
        return httpx.Response(304) if req.headers.get("if-none-match") == '"e1"' else OK(req)

    run(db, config, collector(h))
    st = run(db, config, collector(h))                       # nova instância: o ETag vem da tabela sources
    assert seen == [None, '"e1"'] and st.found == 0 and st.new == 0
    with session_scope(db) as s:
        assert SourceRepository(s).get("portal").fetches_ok == 2


def test_external_id_layer_activated_for_feeds(db, config):
    run(db, config, collector(OK))
    from radar.dedup.service import Action, Deduplicator
    from radar.domain.models import Article
    from radar.pipeline.normalize import normalize
    from radar.domain.models import RawArticle
    with session_scope(db) as s:
        repo = NewsRepository(s); comp = CompetitorRepository(s).by_name("Docol")
        raw = RawArticle(source_collector="rss", source_id="portal", external_id="guid-001", title="Título totalmente diferente aqui",
                         url="https://outro.example/x", published_at=NOW - timedelta(hours=1))
        art = Article(**normalize(raw, NOW).model_dump(), competitor_name="Docol")
        assert Deduplicator(repo, config.settings.dedup).check(art, comp.id).layer == "external_id"


def test_failed_fetch_is_recorded_not_swallowed(db, config):
    st = run(db, config, collector(lambda r: httpx.Response(404)))
    assert st.errors and "portal/feed" in st.errors[0]
    with session_scope(db) as s:
        src = SourceRepository(s).get("portal")
        assert (src.fetches_failed, src.consecutive_failures, src.last_status) == (1, 1, "http404")


def test_quality_report_and_audit_sample(db, config, tmp_path):
    run(db, config, collector(OK))
    with session_scope(db) as s:
        rep = {r.source_id: r for r in build_report(s, config, now=NOW)}
        p = rep["portal"]
        assert p.availability == 1.0 and p.stored == 1 and p.unique == 1 and p.body_rate == 1.0
        assert p.checks["disponibilidade"] == "pass" and p.checks["corpo"] == "pass"
        assert rep["infomoney"].checks["disponibilidade"] == "n/a"   # sem dados => não avalia
        path = tmp_path / "sample.csv"
        assert export_audit_sample(s, config, path) == 1
    row = list(csv.DictReader(path.open(encoding="utf-8")))[0]
    assert row["source_id"] == "portal" and row["concorrente"] == "Docol" and row["relevante? (s/n)"] == ""
