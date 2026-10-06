"""Relatório de qualidade por fonte (critérios objetivos da Fase 10)."""
from __future__ import annotations

import csv
import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.tables import News, Source
from radar.settings import AppConfig


@dataclass
class SourceQuality:
    source_id: str
    type: str
    tier: int
    enabled: bool
    fetches: int
    availability: float | None
    consecutive_failures: int
    last_success_at: datetime | None
    items_seen: int
    items_matched: int
    stored: int
    unique: int
    median_lag_hours: float | None
    body_rate: float | None
    matched_per_week: float | None
    checks: dict[str, str] = field(default_factory=dict)   # critério -> pass | fail | n/a


def build_report(s: Session, cfg: AppConfig, now: datetime | None = None) -> list[SourceQuality]:
    now = now or datetime.now(timezone.utc)
    q = cfg.settings.source_quality
    rows: list[SourceQuality] = []
    for src in s.scalars(select(Source).order_by(Source.tier, Source.source_id)):
        news = list(s.scalars(select(News).where(News.source_id == src.source_id)))
        lags = [(n.collected_at - n.published_at).total_seconds() / 3600 for n in news]
        fetches = src.fetches_ok + src.fetches_failed
        avail = src.fetches_ok / fetches if fetches else None
        with_body = [n for n in news if n.body_status in ("feed", "fetched")]
        first = min((n.collected_at for n in news), default=None)
        weeks = max(((now - first).total_seconds() / 604800), 1 / 7) if first else None
        matched_pw = (src.items_matched / weeks) if weeks else None
        r = SourceQuality(
            src.source_id, src.type, src.tier, src.enabled, fetches, avail, src.consecutive_failures,
            src.last_success_at, src.items_seen, src.items_matched, len(news),
            sum(1 for n in news if n.dup_status == "unique"),
            statistics.median(lags) if lags else None,
            (len(with_body) / len(news)) if news else None, matched_pw)
        need = q.min_matched_per_week_general if src.tier == 3 else q.min_matched_per_week_official
        r.checks = {
            "disponibilidade": "n/a" if avail is None else ("pass" if avail >= q.min_availability else "fail"),
            "atualidade": "n/a" if r.median_lag_hours is None else ("pass" if r.median_lag_hours <= q.max_median_lag_hours else "fail"),
            "rendimento": "n/a" if matched_pw is None else ("pass" if matched_pw >= need else "fail"),
            "corpo": "n/a" if r.body_rate is None else ("pass" if r.body_rate >= q.min_body_rate else "fail"),
        }
        rows.append(r)
    return rows


def export_audit_sample(s: Session, cfg: AppConfig, path: Path, seed: int = 7) -> int:
    """CSV com amostra de itens com match por fonte, para auditoria manual de precisão (coluna 'relevante?')."""
    rng = random.Random(seed)
    size = cfg.settings.source_quality.sample_size
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_id", "news_id", "concorrente", "titulo", "match_confidence", "match_evidence", "url", "relevante? (s/n)"])
        for sid in s.scalars(select(News.source_id).where(News.source_id.is_not(None)).distinct()):
            items = list(s.scalars(select(News).where(News.source_id == sid)))
            for n in rng.sample(items, min(size, len(items))):
                w.writerow([sid, n.id, n.competitor.name, n.title, n.match_confidence, "; ".join(n.match_evidence), n.url, ""])
                total += 1
    return total
