import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from radar.collectors.base import CollectorError, SourceCollector
from radar.collectors.newsapi import NewsApiCollector
from radar.collectors.queries import DefaultQueryStrategy
from tests.conftest import NOW

FIX = json.loads(Path("tests/fixtures/newsapi_ok.json").read_text(encoding="utf-8"))
SINCE = datetime(2026, 9, 29, tzinfo=timezone.utc)


def collector(handler, config, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = config.settings.collection.model_copy(update={"max_retries": 2})
    return NewsApiCollector("secret-key", cfg, client=client, sleep=lambda s: None, **kw)


def test_implements_contract(config):
    c = collector(lambda r: httpx.Response(200, json=FIX), config)
    assert isinstance(c, SourceCollector)


def test_requires_api_key(config):
    with pytest.raises(CollectorError):
        NewsApiCollector("", config.settings.collection)


def test_fetch_parses_and_sends_key_in_header_not_url(config):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=FIX)

    arts = collector(handler, config).fetch(config.competitor("Docol"), SINCE)
    assert all("secret-key" not in str(r.url) for r in seen)
    assert seen[0].headers["X-Api-Key"] == "secret-key"
    assert seen[0].url.params["language"] == "pt"
    assert seen[0].url.params["from"] == "2026-09-29T00:00:00"
    first = arts[0]
    assert first.title.startswith("Docol lança") and first.source_name == "Valor Econômico"
    assert first.published_at == datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
    assert first.external_id is None and first.query
    assert any(a.published_at is None for a in arts)  # data inválida vira None, validação decide


def test_retries_on_429_then_succeeds(config):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"status": "error", "code": "rateLimited", "message": "slow"})
        return httpx.Response(200, json={"status": "ok", "articles": []})

    assert collector(handler, config).fetch(config.competitor("Celite"), SINCE) == []
    assert calls["n"] >= 3


def test_invalid_key_not_retried(config):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, json={"status": "error", "code": "apiKeyInvalid", "message": "bad"})

    with pytest.raises(CollectorError) as e:
        collector(handler, config).fetch(config.competitor("Celite"), SINCE)
    assert e.value.code == "apiKeyInvalid" and not e.value.retryable and calls["n"] == 1


def test_network_error_retries_then_raises(config):
    def handler(req):
        raise httpx.ConnectError("down")

    with pytest.raises(CollectorError) as e:
        collector(handler, config).fetch(config.competitor("Celite"), SINCE)
    assert e.value.retryable


def test_query_strategy(config):
    s = DefaultQueryStrategy()
    roca = s.build(config.competitor("Roca"))
    assert any(q.startswith('("Roca")') and " AND " in q for q in roca)  # ambíguo exige contexto
    assert not any(q == '("Roca")' for q in roca)  # nunca isolado
    docol = s.build(config.competitor("Docol"))
    assert '"Docol Metais"' in docol[0]
    assert all(len(q) <= 500 for q in roca + docol)
