import json
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from radar import cli
from radar.ai.fake import FakeLLMProvider
from radar.bootstrap import build_context
from radar.collectors.base import CollectorError
from radar.db.engine import session_scope
from radar.db.repositories import NewsRepository, RunRepository
from radar.domain.models import RawArticle
from radar.pipeline.runner import run_collection
from radar.settings import EnvSettings, load_config
from tests.conftest import NOW
from tests.test_ai import j

FIX = json.loads(Path("tests/fixtures/newsapi_ok.json").read_text(encoding="utf-8"))["articles"]


class FakeCollector:
    name = "fake"

    def __init__(self, per_competitor=None, error=None):
        self.per, self.error, self.calls = per_competitor or {}, error, []

    def fetch(self, competitor, since, until=None):
        self.calls.append((competitor.name, since))
        if self.error and competitor.name in self.error:
            raise self.error[competitor.name]
        return self.per.get(competitor.name, [])


def raw(title, url, desc="", hours=2, **kw):
    return RawArticle(source_collector="fake", title=title, url=url, description=desc, source_name="Portal",
                      published_at=NOW - timedelta(hours=hours), **kw)


@pytest.fixture
def ctx_db(session_factory, config):
    from radar.db.repositories import CategoryRepository, CompetitorRepository
    with session_scope(session_factory) as s:
        CompetitorRepository(s).sync(config.competitors); CategoryRepository(s).sync(config.categories)
    return session_factory


def collect(factory, config, collector, **kw):
    with session_scope(factory) as s:
        return run_collection(s, [collector], config, now=NOW, **kw)


def test_full_collect_stats(ctx_db, config):
    col = FakeCollector({"Docol": [
        raw("Docol lança nova linha de metais sanitários", "https://a.com/1"),
        raw("Docol lança nova linha de metais sanitários", "https://a.com/1?utm_source=z"),   # mesma URL
        raw("Docol lança nova linha de metais sanitários - Portal B", "https://b.com/2"),        # título igual
        raw("Docol lança nova linha de metais sanitário", "https://c.com/3"),                    # similar
        raw("[Removed]", "https://r.com"),                                                       # descartada
        raw("Tigre vence campeonato e garante vaga", "https://e.com/4", "futebol"),              # sem concorrente
    ]})
    st = collect(ctx_db, config, col)
    assert st.found == 6 and st.new == 2 and st.duplicates == 2 and st.possible_duplicates == 1
    assert st.discarded["sem_titulo_ou_removido"] == 1 and st.discarded["sem_concorrente"] == 1 and not st.errors
    with session_scope(ctx_db) as s:
        assert NewsRepository(s).count() == 3  # a URL repetida não é inserida de novo
        last = RunRepository(s).last("collect")
        assert (last.found, last.new, last.discarded) == (6, 2, 2)


def test_idempotent_second_run(ctx_db, config):
    arts = [raw("Docol lança nova linha de metais sanitários", "https://a.com/1")]
    collect(ctx_db, config, FakeCollector({"Docol": arts}))
    st = collect(ctx_db, config, FakeCollector({"Docol": arts}))
    assert st.new == 0 and st.duplicates == 1


def test_backfill_then_incremental_since(ctx_db, config):
    c1 = FakeCollector(); collect(ctx_db, config, c1)
    assert c1.calls[0][1] == NOW - timedelta(days=7)
    c2 = FakeCollector(); collect(ctx_db, config, c2)
    assert c2.calls[0][1] == NOW - timedelta(hours=config.settings.collection.incremental_overlap_hours)


def test_collector_error_is_logged_and_does_not_stop_others(ctx_db, config):
    col = FakeCollector({"Docol": [raw("Docol lança nova linha de metais sanitários", "https://a.com/1")]},
                        error={"Deca": CollectorError("boom", retryable=True), "Roca": CollectorError("x")})
    st = collect(ctx_db, config, col)
    assert st.new == 1 and len(st.errors) == 2 and "Deca" in st.errors[0]
    with session_scope(ctx_db) as s:
        assert len(RunRepository(s).last("collect").errors) == 2


def test_fatal_credential_error_stops_source(ctx_db, config):
    col = FakeCollector(error={c.name: CollectorError("bad key", code="apiKeyInvalid") for c in config.competitors})
    st = collect(ctx_db, config, col)
    assert len(col.calls) == 1 and len(st.errors) == 1


def test_no_collectors_reports_error(ctx_db, config):
    with session_scope(ctx_db) as s:
        assert "nenhuma fonte" in run_collection(s, [], config, now=NOW).errors[0]


def test_article_matching_two_competitors_stored_twice(ctx_db, config):
    col = FakeCollector({"Docol": [raw("Dexco e Docol disputam mercado de metais sanitários", "https://a.com/1")]})
    st = collect(ctx_db, config, col)
    assert st.new == 2


# ---- CLI ponta a ponta com banco em arquivo, coletor e IA falsos ----
@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("NEWS_API_KEY", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.chdir(Path(__file__).parent.parent)
    return tmp_path


def patch(monkeypatch, collector, provider):
    monkeypatch.setattr(cli, "build_collectors", lambda cfg: [collector])
    monkeypatch.setattr(cli, "build_provider", lambda cfg: provider if not isinstance(provider, Exception) else (_ for _ in ()).throw(provider))


def test_cli_run_ai_down_keeps_news_then_reprocess(cli_env, monkeypatch):
    from radar.ai.base import LLMError
    col = FakeCollector({"Docol": [raw("Docol lança nova linha de metais sanitários", "https://a.com/1", hours=1)]})
    # `now` real no CLI: usa data atual, então publica "agora"
    from datetime import datetime, timezone
    col.per["Docol"][0].published_at = datetime.now(timezone.utc) - timedelta(hours=1)
    patch(monkeypatch, col, LLMError("sem chave"))
    r = CliRunner().invoke(cli.app, ["run"])
    assert r.exit_code == 1 and "novas=1" in r.output and "analisadas=0" in r.output
    ctx = build_context(load_config())
    with session_scope(ctx.session_factory) as s:
        n = NewsRepository(s).pending_analysis(10, 3)
        assert len(n) == 1 and n[0].analysis_status == "pending"   # notícia não foi perdida

    patch(monkeypatch, col, FakeLLMProvider([j()]))
    r = CliRunner().invoke(cli.app, ["analyze"])
    assert r.exit_code == 0 and "analisadas=1" in r.output
    r = CliRunner().invoke(cli.app, ["reprocess", "--all"])
    assert r.exit_code == 0 and "1 notícias marcadas" in r.output and "analisadas=1" in r.output
