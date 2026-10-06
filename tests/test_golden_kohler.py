"""Golden test (Fase 10): a matéria 'Gigante de louças fecha única fábrica no Brasil e encerra marca' é sobre a Kohler,
mas o título não cita a empresa e o corpo menciona Dexco/Deca como comparação.

ATENÇÃO: a fixture é SINTÉTICA, reconstruída a partir da descrição do caso (o ambiente não alcança o iG).
Fase 10 garante a INFRAESTRUTURA: o corpo completo chega ao banco. A atribuição EXCLUSIVA à Kohler depende de
mudanças de matching (fora do escopo desta fase) e está registrada como xfail estrito."""
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from radar.collectors.http import PoliteHttp
from radar.collectors.rss import RSSCollector
from radar.db.engine import session_scope
from radar.db.repositories import CategoryRepository, CompetitorRepository
from radar.db.tables import Competitor, News
from radar.pipeline.runner import run_collection
from radar.settings import HttpConfig, SourceConfig
from tests.conftest import NOW

FEED = Path("tests/fixtures/golden_kohler_feed.xml").read_bytes()
TITLE = "Gigante de louças fecha única fábrica no Brasil e encerra marca"


@pytest.fixture
def stored(session_factory, config):
    with session_scope(session_factory) as s:
        CompetitorRepository(s).sync(config.competitors); CategoryRepository(s).sync(config.categories)
    cfg = SourceConfig(id="ig-economia", type="rss", url="https://economia.ig.com.br/feed", tier=3)
    http = PoliteHttp(HttpConfig(min_delay_seconds=0, respect_robots=False),
                      client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=FEED))), sleep=lambda s: None)
    with session_scope(session_factory) as s:
        run_collection(s, [RSSCollector(cfg, http)], config, now=NOW.replace(month=9, day=7), days=7)
    with session_scope(session_factory) as s:
        return {n.competitor.name: n for n in s.scalars(select(News))}


def test_title_has_no_company_name():
    assert not any(w in TITLE for w in ("Kohler", "Dexco", "Deca", "Roca"))


def test_infrastructure_preserves_full_body(stored):
    assert stored, "a matéria deveria ter sido armazenada"
    n = next(iter(stored.values()))
    assert n.title == TITLE and n.source_id == "ig-economia" and n.source_type == "rss" and n.body_status == "feed"
    assert n.external_id == "ig-golden-kohler-001"
    # corpo completo (não os ~200 caracteres da News API): termos do fim do texto estão preservados
    assert len(n.raw_content) > 600
    for term in ("Fiori", "premium e de luxo", "importação", "Dexco", "Deca", "única fábrica"):
        assert term in n.raw_content
    assert n.raw_content.index("Fiori") > 200 and n.raw_content.index("Dexco") > 400


def test_kohler_is_identified_from_body(stored):
    assert "Kohler" in stored                      # título genérico não impede a identificação quando o corpo existe
    ev = stored["Kohler"].match_evidence
    assert ev and stored["Kohler"].match_confidence >= 0.5


@pytest.mark.xfail(strict=True, reason="Atribuição exclusiva exige mudança de matching (proeminência/grupo econômico): "
                                       "fora do escopo da Fase 10. Hoje Dexco/Deca também casam por menção no corpo.")
def test_only_kohler_is_attributed(stored):
    assert set(stored) == {"Kohler"}
