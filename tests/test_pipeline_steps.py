import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from radar.domain.models import RawArticle
from radar.pipeline.match import match_all, match_competitor
from radar.pipeline.normalize import clean_text, normalize, normalize_title, normalize_url
from radar.pipeline.validate import validate
from tests.conftest import NOW

FIX = json.loads(Path("tests/fixtures/newsapi_ok.json").read_text(encoding="utf-8"))["articles"]


def raw(**kw):
    base = dict(source_collector="newsapi", title="Docol lança nova linha de metais", url="https://a.com/x",
                source_name="Portal", published_at=NOW - timedelta(hours=3), description="d")
    return RawArticle(**{**base, **kw})


# ---- normalize ----
def test_normalize_url_removes_tracking_and_fragments():
    assert normalize_url("http://WWW.Valor.com.br/a/b/?utm_source=x&id=2&fbclid=z#top") == "https://valor.com.br/a/b?id=2"
    assert normalize_url("https://x.com/a//b/") == "https://x.com/a/b"
    assert normalize_url("https://x.com/p?b=2&a=1") == normalize_url("https://x.com/p?a=1&b=2")


def test_normalize_title_strips_source_suffix_and_accents():
    t = normalize_title("Docol lança nova linha! - Valor Econômico", "Valor Econômico", "valor.com.br")
    assert t == "docol lanca nova linha"
    # sufixo que não é a fonte permanece
    assert "outra coisa" in normalize_title("Docol e outra coisa - Parte 2 do caso", "Exame", "exame.com")


def test_clean_text_html_and_truncation():
    assert clean_text("A <b>Docol</b>  anunciou &amp; mais [+1200 chars]") == "A Docol anunciou & mais"
    assert clean_text("   ") is None and clean_text(None) is None


def test_normalize_fills_fields():
    n = normalize(raw(url="https://www.portal.com/x?utm_a=1", published_at=datetime(2026, 10, 5, 7, 0)), NOW)
    assert n.source_domain == "portal.com" and n.url_normalized == "https://portal.com/x"
    assert n.published_at.tzinfo is not None and len(n.content_hash) == 64


# ---- validate ----
def check(cfg, **kw):
    n = normalize(raw(**kw), NOW)
    return validate(n, NOW, cfg.settings.validation, cfg.settings.collection)


@pytest.mark.parametrize("kw,reason", [
    ({}, None),
    ({"title": "[Removed]"}, "sem_titulo_ou_removido"),
    ({"title": "Curto"}, "titulo_curto"),
    ({"url": "ftp://x"}, "url_invalida"),
    ({"url": None}, "url_invalida"),
    ({"published_at": None}, "sem_data"),
    ({"published_at": NOW + timedelta(days=5)}, "data_futura"),
    ({"published_at": NOW - timedelta(days=90)}, "muito_antiga"),
])
def test_validate(config, kw, reason):
    assert check(config, **kw) == reason


def test_validate_blocked_domain(config):
    cfg = config.model_copy(deep=True)
    cfg.settings.collection.blocked_domains = ["spam.com"]
    assert check(cfg, url="https://sub.spam.com/a") == "dominio_bloqueado"


# ---- match ----
def norm(title, desc="", url="https://portal.com/n", **kw):
    return normalize(raw(title=title, description=desc, url=url, **kw), NOW)


def best(config, n):
    return [(r.competitor, round(r.confidence, 2)) for r in match_all(n, config.competitors, config.settings.matching)]


def test_strong_alias_matches(config):
    r = best(config, norm("Docol lança nova linha de metais sanitários"))
    assert r[0][0] == "Docol" and r[0][1] >= 0.9


def test_ambiguous_alias_with_context_matches(config):
    r = best(config, norm("Roca amplia fábrica de louças sanitárias em Pernambuco", "Investimento em banheiros."))
    assert r[0][0] == "Roca"


def test_ambiguous_alias_without_context_rejected(config):
    assert best(config, norm("Roca anuncia acordo corporativo importante")) == []


def test_lowercase_common_word_not_a_match(config):
    assert best(config, norm("Arqueólogos encontram uma roca antiga com louça e torneira")) == []


def test_exclude_terms_reject_football_tigre(config):
    n = norm("Tigre vence campeonato e garante vaga na final", "Time de futebol venceu o jogo.")
    assert best(config, n) == []


def test_tigre_company_with_context(config):
    r = best(config, norm("Tigre lança tubos e conexões para construção civil", "Nova linha hidráulica."))
    assert r[0][0] == "Tigre"


def test_official_domain_is_evidence(config):
    r = best(config, norm("Novidades da empresa no setor de construção", url="https://www.docol.com.br/noticias/1"))
    assert r and r[0][0] == "Docol"


def test_same_article_can_match_two_competitors(config):
    r = best(config, norm("Dexco e Docol disputam mercado de metais sanitários", "Concorrência no setor."))
    assert {c for c, _ in r} >= {"Dexco", "Docol"}


def test_fixture_end_to_end_steps(config):
    """fixture da News API -> normalize -> validate -> match"""
    from radar.collectors.newsapi import _parse_dt
    out = []
    for item in FIX:
        r = RawArticle(source_collector="newsapi", title=item["title"], description=item["description"],
                       url=item["url"], source_name=item["source"]["name"],
                       published_at=_parse_dt(item["publishedAt"]), content=item["content"])
        n = normalize(r, NOW)
        reason = validate(n, NOW, config.settings.validation, config.settings.collection)
        out.append((item["title"][:10], reason, [m.competitor for m in match_all(n, config.competitors, config.settings.matching)] if not reason else []))
    assert out[0][1:] == (None, ["Docol"])
    assert out[1][1:] == (None, ["Roca"])
    assert out[2][1:] == (None, [])               # Tigre futebol: válido, mas sem match
    assert out[3][1] == "sem_titulo_ou_removido"
    assert out[4][1] == "sem_data"
