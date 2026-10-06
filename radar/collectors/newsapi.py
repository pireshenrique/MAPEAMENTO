"""Coletor News API (https://newsapi.org, endpoint /v2/everything). Único módulo que conhece o formato dela."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable

import httpx

from radar.collectors.base import CollectorError, QueryStrategy
from radar.collectors.queries import DefaultQueryStrategy
from radar.domain.models import RawArticle
from radar.settings import CollectionConfig, CompetitorConfig

log = logging.getLogger(__name__)
BASE_URL = "https://newsapi.org/v2/everything"
_RETRYABLE_CODES = {"rateLimited"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class NewsApiCollector:
    name = "newsapi"

    def __init__(self, api_key: str, cfg: CollectionConfig, strategy: QueryStrategy | None = None,
                 client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise CollectorError("NEWS_API_KEY não configurada", code="missingApiKey")
        self._key = api_key
        self.cfg = cfg
        self.strategy = strategy or DefaultQueryStrategy()
        self._client = client or httpx.Client(timeout=cfg.request_timeout_seconds)
        self._sleep = sleep

    def fetch(self, competitor: CompetitorConfig, since: datetime, until: datetime | None = None) -> list[RawArticle]:
        articles: list[RawArticle] = []
        for query in self.strategy.build(competitor):
            for page in range(1, self.cfg.max_pages_per_query + 1):
                payload = self._request(query, since, until, page)
                items = payload.get("articles", [])
                articles.extend(self._parse(i, query) for i in items)
                if len(items) < self.cfg.page_size:
                    break
        log.info("newsapi: %s -> %d artigos brutos", competitor.name, len(articles))
        return articles

    # -- HTTP -----------------------------------------------------------------
    def _request(self, query: str, since: datetime, until: datetime | None, page: int) -> dict:
        params = {
            "q": query, "language": self.cfg.language, "sortBy": "publishedAt",
            "pageSize": self.cfg.page_size, "page": page,
            "from": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "searchIn": "title,description,content",
        }
        if until:
            params["to"] = until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        attempt = 0
        while True:
            try:
                return self._once(params)
            except CollectorError as e:
                if not e.retryable or attempt >= self.cfg.max_retries:
                    raise
                delay = 2 ** attempt
                log.warning("newsapi: erro retentável (%s); tentativa %d em %ss", e, attempt + 1, delay)
                self._sleep(delay)
                attempt += 1

    def _once(self, params: dict) -> dict:
        try:
            resp = self._client.get(BASE_URL, params=params, headers={"X-Api-Key": self._key})
        except httpx.HTTPError as e:  # rede/timeout
            raise CollectorError(f"falha de rede: {type(e).__name__}", retryable=True) from e
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code == 200 and data.get("status") == "ok":
            return data
        code = data.get("code") or f"http{resp.status_code}"
        msg = data.get("message") or resp.reason_phrase
        retryable = resp.status_code in (429, 500, 502, 503, 504) or code in _RETRYABLE_CODES
        raise CollectorError(f"News API {resp.status_code} {code}: {msg}", retryable=retryable, code=code)

    # -- parsing --------------------------------------------------------------
    def _parse(self, item: dict, query: str) -> RawArticle:
        src = item.get("source") or {}
        return RawArticle(
            source_collector=self.name,
            external_id=None,  # a News API não fornece ID estável
            title=item.get("title"), description=item.get("description"), url=item.get("url"),
            source_name=src.get("name"), author=item.get("author"),
            published_at=_parse_dt(item.get("publishedAt")), image_url=item.get("urlToImage"),
            content=item.get("content"), query=query,
        )
