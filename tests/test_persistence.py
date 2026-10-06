from datetime import timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from radar.db.engine import make_engine, session_scope
from radar.db.migrate import upgrade_to_head
from radar.db.repositories import CategoryRepository, CompetitorRepository, NewsRepository, RunRepository
from radar.db.tables import Base
from radar.domain.models import AnalysisStatus, Article, DupStatus
from tests.conftest import NOW


def make_article(url="https://x.com/a", title="Docol lança nova linha de metais", **kw):
    base = dict(source_collector="newsapi", competitor_name="Docol", title=title, url=url,
                url_normalized=url, title_normalized=title.lower(), content_hash="h", published_at=NOW,
                collected_at=NOW)
    return Article(**{**base, **kw})


def test_sync_competitors_and_deactivate(session, config):
    repo = CompetitorRepository(session)
    rows = repo.sync(config.competitors)
    assert len(rows) == 7 and all(r.active for r in rows.values())
    assert "Roca" in rows["Roca"].aliases
    repo.sync(config.competitors[:2])  # os demais saem do YAML
    assert [c.name for c in repo.list(only_active=True)] == ["Deca", "Roca"]
    assert len(repo.list()) == 7  # histórico preservado


def test_sync_categories(session, config):
    repo = CategoryRepository(session)
    repo.sync(config.categories)
    repo.sync(config.categories)  # idempotente
    assert len(repo.names()) == 19
    assert repo.names()[0] == "Produto"


def test_news_add_and_unique_constraint(session, config):
    comp = CompetitorRepository(session).sync(config.competitors)["Docol"]
    repo = NewsRepository(session)
    n = repo.add(make_article(), comp.id)
    assert n.id and n.published_at.tzinfo is not None
    assert repo.exists_url(comp.id, "https://x.com/a")
    with pytest.raises(IntegrityError):
        repo.add(make_article(), comp.id)


def test_pending_analysis_and_status_flow(session, config):
    comp = CompetitorRepository(session).sync(config.competitors)["Docol"]
    repo = NewsRepository(session)
    a = repo.add(make_article("https://x.com/1", "Titulo número um aqui"), comp.id)
    d = repo.add(make_article("https://x.com/2", "Titulo número dois aqui"), comp.id, dup_status=DupStatus.DUPLICATE)
    assert d.analysis_status == "skipped"
    assert [n.id for n in repo.pending_analysis(10, 3)] == [a.id]
    repo.mark_attempt(a, AnalysisStatus.FAILED)
    assert repo.pending_analysis(10, 3)[0].id == a.id  # falhas são reprocessáveis
    repo.mark_attempt(a, AnalysisStatus.FAILED); repo.mark_attempt(a, AnalysisStatus.FAILED)
    assert repo.pending_analysis(10, 3) == []  # esgotou tentativas


def test_save_analysis(session, config):
    comp = CompetitorRepository(session).sync(config.competitors)["Docol"]
    repo = NewsRepository(session)
    n = repo.add(make_article(), comp.id)
    repo.save_analysis(n, is_relevant=True, relevance_score=4, competitive_impact="negative",
                       sentiment="neutral", category="Produto", subcategory=None, summary="s",
                       key_points=["a"], strategic_reason="r", model_used="fake", prompt_version="v1",
                       raw_response="{}")
    session.commit()
    assert n.analysis_status == "done" and n.analysis.relevance_score == 4 and n.analysis.analyzed_at.tzinfo


def test_latest_published_and_runs(session, config):
    comp = CompetitorRepository(session).sync(config.competitors)["Docol"]
    repo = NewsRepository(session)
    repo.add(make_article("https://x.com/1", "Titulo número um aqui"), comp.id)
    repo.add(make_article("https://x.com/2", "Titulo número dois aqui", published_at=NOW - timedelta(days=2)), comp.id)
    assert repo.latest_published() == NOW
    runs = RunRepository(session)
    assert runs.last() is None
    r = runs.start("collect", "newsapi"); runs.finish(r)
    assert runs.last().id == r.id


def test_naive_datetime_rejected(session, config):
    from datetime import datetime
    comp = CompetitorRepository(session).sync(config.competitors)["Docol"]
    a = make_article().model_copy(update={"published_at": datetime(2026, 1, 1)})
    with pytest.raises(Exception):
        NewsRepository(session).add(a, comp.id)


def test_session_scope_rolls_back(session_factory, config):
    with pytest.raises(RuntimeError):
        with session_scope(session_factory) as s:
            CompetitorRepository(s).sync(config.competitors)
            raise RuntimeError("boom")
    with session_scope(session_factory) as s:
        assert CompetitorRepository(s).list() == []


def test_alembic_migration_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    upgrade_to_head(url)
    engine = make_engine(url)
    assert {"competitors", "news", "news_analysis", "categories", "collection_runs"} <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
