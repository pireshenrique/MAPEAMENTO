"""Coletor RSS/Atom (feedparser). scope=feed: lista tudo o que a fonte publicou; o MATCH decide o concorrente."""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone

import feedparser

from radar.collectors.base import CollectorError
from radar.collectors.http import PoliteHttp
from radar.domain.models import BodyStatus, RawArticle
from radar.settings import SourceConfig

log = logging.getLogger(__name__)


def _dt(entry) -> datetime | None:  # noqa: ANN001
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def _image(entry) -> str | None:  # noqa: ANN001
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key, []) or []:
            if m.get("url"):
                return m["url"]
    for e in entry.get("enclosures", []) or []:
        if str(e.get("type", "")).startswith("image") and e.get("href"):
            return e["href"]
    return None


class RSSCollector:
    name = "rss"
    scope = "feed"

    def __init__(self, cfg: SourceConfig, http: PoliteHttp):
        self.cfg, self.http = cfg, http
        self.source_id = cfg.id
        self.etag: str | None = None
        self.last_modified: str | None = None
        self.last_status = "never"
        self.not_modified = False

    def load_state(self, etag: str | None, last_modified: str | None) -> None:
        self.etag, self.last_modified = etag, last_modified

    def fetch(self, competitor, since: datetime, until: datetime | None = None) -> list[RawArticle]:  # noqa: ANN001
        res = self.http.get(self.cfg.url, self.etag, self.last_modified)
        self.etag, self.last_modified = res.etag, res.last_modified
        self.not_modified = res.not_modified
        self.last_status = "not_modified" if res.not_modified else "ok"
        if res.not_modified:
            log.info("rss %s: 304 não modificado", self.cfg.id)
            return []
        parsed = feedparser.parse(res.content)
        if not parsed.get("version") or (parsed.bozo and not parsed.entries):
            self.last_status = "invalid_feed"
            raise CollectorError(f"feed inválido em {self.cfg.url}: {parsed.get('bozo_exception')}", code="invalidFeed")
        out: list[RawArticle] = []
        for e in parsed.entries:
            published = _dt(e)
            if published and published < since:
                continue
            body = None
            contents = [c.get("value", "") for c in e.get("content", []) or [] if c.get("value")]
            if contents:
                body = max(contents, key=len)
            link = e.get("link")
            out.append(RawArticle(
                source_collector=self.name, source_id=self.cfg.id, source_type="rss",
                external_id=e.get("id") or e.get("guid") or None,
                title=e.get("title"), description=e.get("summary"), url=link, canonical_url=None,
                author=e.get("author"), published_at=published, image_url=_image(e),
                content=e.get("summary"), body=body,
                body_status=(BodyStatus.FEED if body else BodyStatus.NONE).value,
                tags=[t.get("term") for t in e.get("tags", []) or [] if t.get("term")],
                source_name=(parsed.feed.get("title") or self.cfg.id), query=None))
        log.info("rss %s: %d itens (de %d no feed)", self.cfg.id, len(out), len(parsed.entries))
        return out
