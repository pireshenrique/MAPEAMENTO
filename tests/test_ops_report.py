"""Relatório operacional: detalhe por fonte por execução, alertas e cobertura parcial (docs/relatorio-diario-spec.md, seção 9)."""
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from radar import cli
from radar.collectors.base import CollectorError
from radar.db.engine import session_scope
from radar.db.repositories import CategoryRepository, CompetitorRepository, RunRepository, SourceRepository
from radar.db.tables import CollectionRun, News
from radar.domain.models import RawArticle
from radar.ops_report import build_ops_report, render_ops_report
from radar.pipeline.runner import run_collection
from radar.settings import SourceConfig
from tests.conftest import NOW


class FeedCollector:
    name, scope = "rss", "feed"

    def __init__(self, source_id, items=None, error=None, body_status="feed"):
        self.source_id, self.items, self.error, self.body_status = source_id, items or [], error, body_status
        self.last_status = "ok"

    def fetch(self, competitor, since, until=None):
        if self.error:
            raise self.error
        return [RawArticle(source_collector="rss", source_id=self.source_id, source_type="rss", title=t, url=u,
                           description=d, source_name="Portal", body_status=self.body_status,
                           published_at=NOW - timedelta(hours=2)) for t, u, d in self.items]


MATCH = ("Docol lança nova linha de metais sanitários", "https://a.com/1", "")
NOISE = ("Prefeitura anuncia obras de asfalto na capital", "https://a.com/2", "")
SHORT = ("curto", "https://a.com/3", "")


@pytest.fixture
def cfg(config):
    c = config.model_copy(deep=True)
    c.sources = [SourceConfig(id="alfa", type="rss", url="https://alfa.example/feed", tier=3, enabled=True, verified=True),
                 SourceConfig(id="beta", type="rss", url="https://beta.example/feed", tier=3, enabled=True, verified=True),
                 SourceConfig(id="off", type="rss", url="https://off.example/feed", tier=3)]
    return c


@pytest.fixture
def db(session_factory, cfg):
    with session_scope(session_factory) as s:
        CompetitorRepository(s).sync(cfg.competitors); CategoryRepository(s).sync(cfg.categories)
        SourceRepository(s).sync(cfg.sources)
    return session_factory


def collect(db, cfg, collectors, now=NOW):
    with session_scope(db) as s:
        return run_collection(s, collectors, cfg, now=now)


def report(db, cfg, now=NOW + timedelta(minutes=5), **kw):
    with session_scope(db) as s:
        return build_ops_report(s, cfg, now=now, **kw)


def test_run_persists_per_source_detail_and_discard_reasons(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH, NOISE, SHORT]), FeedCollector("beta", [NOISE])])
    with session_scope(db) as s:
        d = RunRepository(s).last("collect").by_source
    assert d["alfa"]["seen"] == 3 and d["alfa"]["matched"] == 1 and d["alfa"]["stored"] == 1
    assert d["alfa"]["discarded"] == 2 and d["alfa"]["reasons"] == {"sem_concorrente": 1, "titulo_curto": 1}
    assert d["alfa"]["status"] == "ok" and d["alfa"]["errors"] == []
    assert d["beta"]["seen"] == 1 and d["beta"]["discarded"] == 1 and d["beta"]["stored"] == 0


def test_failed_source_is_recorded_even_without_items(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH]), FeedCollector("beta", error=CollectorError("HTTP 503", code="http_503"))])
    with session_scope(db) as s:
        d = RunRepository(s).last("collect").by_source
    assert d["beta"]["status"] == "http_503" and d["beta"]["errors"] == ["HTTP 503"] and d["beta"]["seen"] == 0


def test_report_per_source_totals_and_body_status(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH, NOISE]), FeedCollector("beta", [NOISE])])
    r = report(db, cfg)
    assert [s.source_id for s in r.sources] == ["alfa", "beta"]          # fonte desabilitada fora do relatório
    alfa = next(s for s in r.sources if s.source_id == "alfa")
    assert (alfa.window.seen, alfa.window.discarded, alfa.window.matched, alfa.window.stored) == (2, 1, 1, 1)
    assert alfa.enabled and alfa.verified and alfa.body == {"feed": 1}
    assert (r.totals.seen, r.totals.discarded, r.totals.stored) == (3, 2, 1)
    assert r.stored_by_competitor == {"Docol": 1}
    assert not r.partial_coverage and not [a for a in r.alerts if a.level == "ALERTA"]
    txt = render_ops_report(r)
    assert "Cobertura: 2 de 2" in txt and "alfa (rss) enabled=True verified=True" in txt and "off" not in txt.replace("coletados", "")


def test_unavailable_source_marks_partial_coverage(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH]), FeedCollector("beta", error=CollectorError("HTTP 503", code="http_503"))])
    r = report(db, cfg)
    assert r.partial_coverage == ["beta"]
    assert any(a.level == "ALERTA" and a.source_id == "beta" and "indisponível" in a.message for a in r.alerts)
    assert "COBERTURA PARCIAL: beta" in render_ops_report(r)


def test_consecutive_failures_alert(db, cfg):
    for i in range(3):
        collect(db, cfg, [FeedCollector("alfa", [MATCH]), FeedCollector("beta", error=CollectorError("fora", code="http_500"))],
                now=NOW + timedelta(hours=i))
    r = report(db, cfg, now=NOW + timedelta(hours=2, minutes=5))
    assert any(a.source_id == "beta" and "3 falhas consecutivas" in a.message for a in r.alerts)


def test_enabled_source_never_consulted(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH])])            # beta habilitada, mas fora da execução
    r = report(db, cfg)
    assert r.partial_coverage == ["beta"]
    assert any(a.source_id == "beta" and "nunca consultada" in a.message for a in r.alerts)


def test_no_run_or_stale_run_alerts(db, cfg):
    assert any(a.message == "nenhuma coleta registrada" for a in report(db, cfg).alerts)
    collect(db, cfg, [FeedCollector("alfa", [MATCH]), FeedCollector("beta", [NOISE])])
    r = report(db, cfg, now=NOW + timedelta(hours=30))
    assert any("ausência de coleta" in a.message for a in r.alerts)
    assert any(a.source_id == "alfa" and "sem coleta com sucesso" in a.message for a in r.alerts)


def test_source_without_items_warns(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH]), FeedCollector("beta", [])])
    r = report(db, cfg)
    assert any(a.level == "AVISO" and a.source_id == "beta" and "0 itens" in a.message for a in r.alerts)
    assert not r.partial_coverage                                   # sem itens não é indisponibilidade


def test_body_status_warning_for_source_without_body(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [MATCH], body_status="none"), FeedCollector("beta", [NOISE])])
    r = report(db, cfg)
    assert any(a.level == "AVISO" and a.source_id == "alfa" and "corpo do artigo ausente" in a.message for a in r.alerts)
    assert next(s for s in r.sources if s.source_id == "alfa").body == {"none": 1}


def test_no_match_alert_needs_enough_history(db, cfg):
    collect(db, cfg, [FeedCollector("alfa", [NOISE]), FeedCollector("beta", [NOISE])])
    early = report(db, cfg, now=NOW + timedelta(days=2))
    assert not any("nenhum item casado" in a.message for a in early.alerts)       # só 2 dias de histórico
    assert "só se aplica após 7 dias" in render_ops_report(early)
    late = report(db, cfg, now=NOW + timedelta(days=8))
    assert any(a.level == "ALERTA" and "nenhum item casado nos últimos 7 dias" in a.message for a in late.alerts)


def test_runs_before_by_source_are_flagged_not_invented(db, cfg):
    with session_scope(db) as s:
        run = RunRepository(s).start("collect", "rss", started_at=NOW)
        run.found = 30
        RunRepository(s).finish(run)
    r = report(db, cfg)
    assert r.runs_without_detail == 1
    assert all(s.window.seen == 0 and s.last_run is None for s in r.sources)
    assert "sem detalhe por fonte" in render_ops_report(r)


def test_cli_ops_report_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'r.db'}")
    out = CliRunner().invoke(cli.app, ["ops-report"])
    assert out.exit_code == 0 and "RELATÓRIO OPERACIONAL" in out.stdout and "nenhuma coleta registrada" in out.stdout
