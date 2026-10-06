from datetime import timedelta

import pytest

from radar.db.repositories import CompetitorRepository, NewsRepository
from radar.dedup.service import Action, Deduplicator, similarity
from radar.domain.models import AnalysisStatus, DupStatus, RawArticle
from radar.pipeline.normalize import normalize
from radar.domain.models import Article
from tests.conftest import NOW


def art(title, url, source="Portal A", hours=0, desc="d", ext=None, comp="Docol"):
    n = normalize(RawArticle(source_collector="newsapi", title=title, url=url, source_name=source,
                             published_at=NOW - timedelta(hours=hours), description=desc, external_id=ext), NOW)
    return Article(**n.model_dump(), competitor_name=comp)


@pytest.fixture
def env(session, config):
    comps = CompetitorRepository(session).sync(config.competitors)
    repo = NewsRepository(session)
    return repo, Deduplicator(repo, config.settings.dedup), comps


def store(env, a, comp="Docol"):
    repo, dd, comps = env
    r = dd.check(a, comps[comp].id)
    if r.action == Action.STORE:
        row = repo.add(a, comps[comp].id, dup_status=r.status, dup_of_id=r.dup_of_id, dup_score=r.score)
        return r, row
    return r, None


def test_first_article_is_unique(env):
    r, row = store(env, art("Docol lança nova linha de torneiras", "https://a.com/1"))
    assert r.status == DupStatus.UNIQUE and row.analysis_status == "pending"


def test_layer1_same_url_skipped_even_with_tracking(env):
    store(env, art("Docol lança nova linha de torneiras", "https://a.com/1"))
    r, row = store(env, art("Título totalmente diferente aqui", "https://www.a.com/1/?utm_source=x"))
    assert r.action == Action.SKIP and r.layer == "url" and row is None


def test_layer2_external_id(env):
    store(env, art("Docol lança nova linha de torneiras", "https://a.com/1", ext="id-9"))
    r, _ = store(env, art("Outro título qualquer sobre isso", "https://b.com/2", ext="id-9"))
    assert r.action == Action.SKIP and r.layer == "external_id"


def test_layer3_same_title_other_portal_is_stored_as_duplicate(env):
    _, first = store(env, art("Docol lança nova linha de torneiras", "https://a.com/1"))
    r, row = store(env, art("Docol lança nova linha de torneiras - Portal B", "https://b.com/9", source="Portal B"))
    assert r.layer == "title" and row.dup_status == "duplicate" and row.dup_of_id == first.id
    assert row.analysis_status == AnalysisStatus.SKIPPED.value  # não gasta IA
    assert env[0].count() == 2  # nada foi apagado


def test_layer4_similar_is_only_possible_duplicate(env):
    _, first = store(env, art("Docol lança nova linha de torneiras para banheiros", "https://a.com/1"))
    r, row = store(env, art("Docol lança nova linha de torneiras para banheiro", "https://c.com/3", hours=2))
    assert r.layer == "similarity" and row.dup_status == "possible_duplicate"
    assert row.dup_of_id == first.id and row.dup_score >= 90
    assert row.analysis_status == "pending"  # continua sendo analisada


def test_chain_points_to_root(env):
    _, a = store(env, art("Docol lança nova linha de torneiras para banheiros", "https://a.com/1"))
    _, b = store(env, art("Docol lança nova linha de torneiras para banheiro", "https://c.com/3", hours=1))
    _, c = store(env, art("Docol lança nova linha de torneiras para banheiros hoje", "https://d.com/4", hours=2))
    assert b.dup_of_id == a.id and c.dup_of_id == a.id


def test_different_stories_stay_unique(env):
    store(env, art("Docol lança nova linha de torneiras para banheiros", "https://a.com/1"))
    r, row = store(env, art("Docol anuncia investimento em fábrica de Joinville", "https://a.com/2"))
    assert r.status == DupStatus.UNIQUE


def test_outside_window_not_compared(env):
    store(env, art("Docol lança nova linha de torneiras para banheiros", "https://a.com/1", hours=24 * 10))
    r, _ = store(env, art("Docol lança nova linha de torneiras para banheiros", "https://z.com/1"))
    assert r.status == DupStatus.UNIQUE


def test_other_competitor_not_deduped(env):
    store(env, art("Dexco e Docol disputam mercado de metais", "https://a.com/1"), comp="Docol")
    r, row = store(env, art("Dexco e Docol disputam mercado de metais", "https://a.com/1", comp="Dexco"), comp="Dexco")
    assert r.status == DupStatus.UNIQUE and row is not None


def test_similarity_guards_length_mismatch():
    assert similarity("docol lanca linha", "docol lanca linha de torneiras premium para todo o brasil hoje") == 0.0
    assert similarity("a b c d", "a b c d") == 100
