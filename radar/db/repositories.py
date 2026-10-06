"""Única porta de acesso ao banco. Recebe Session; quem chama controla a transação."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.domain.models import AnalysisStatus, Article, DupStatus
from radar.db.tables import Category, CollectionRun, Competitor, News, NewsAnalysis, utcnow
from radar.settings import CategoryConfig, CompetitorConfig


class CompetitorRepository:
    def __init__(self, s: Session):
        self.s = s

    def sync(self, configs: Sequence[CompetitorConfig]) -> dict[str, Competitor]:
        """Upsert por nome. Quem sai do YAML fica inativo (histórico é preservado)."""
        existing = {c.name: c for c in self.s.scalars(select(Competitor))}
        cfg_names = set()
        for cfg in configs:
            cfg_names.add(cfg.name)
            aliases = list(dict.fromkeys(cfg.aliases + cfg.ambiguous_aliases))
            row = existing.get(cfg.name)
            if row is None:
                row = Competitor(name=cfg.name)
                self.s.add(row)
                existing[cfg.name] = row
            row.aliases, row.domains, row.active = aliases, cfg.domains, cfg.active
        for name, row in existing.items():
            if name not in cfg_names:
                row.active = False
        self.s.flush()
        return existing

    def by_name(self, name: str) -> Competitor | None:
        return self.s.scalar(select(Competitor).where(Competitor.name == name))

    def list(self, only_active: bool = False) -> list[Competitor]:
        q = select(Competitor).order_by(Competitor.name)
        if only_active:
            q = q.where(Competitor.active.is_(True))
        return list(self.s.scalars(q))


class CategoryRepository:
    def __init__(self, s: Session):
        self.s = s

    def sync(self, configs: Sequence[CategoryConfig]) -> None:
        existing = {c.name: c for c in self.s.scalars(select(Category))}
        names = set()
        for i, cfg in enumerate(configs):
            names.add(cfg.name)
            row = existing.get(cfg.name) or Category(name=cfg.name)
            if cfg.name not in existing:
                self.s.add(row)
            row.description, row.sort_order, row.active = cfg.description, i, True
        for name, row in existing.items():
            if name not in names:
                row.active = False
        self.s.flush()

    def names(self, only_active: bool = True) -> list[str]:
        q = select(Category.name).order_by(Category.sort_order)
        if only_active:
            q = q.where(Category.active.is_(True))
        return list(self.s.scalars(q))


class NewsRepository:
    def __init__(self, s: Session):
        self.s = s

    def add(self, article: Article, competitor_id: int, *, dup_status: DupStatus = DupStatus.UNIQUE,
            dup_of_id: int | None = None, dup_score: float | None = None) -> News:
        row = News(
            source_collector=article.source_collector, external_id=article.external_id,
            competitor_id=competitor_id, title=article.title, description=article.description,
            url=article.url, url_normalized=article.url_normalized,
            title_normalized=article.title_normalized, content_hash=article.content_hash,
            source_name=article.source_name, source_domain=article.source_domain,
            author=article.author, published_at=article.published_at, image_url=article.image_url,
            raw_content=article.raw_content, match_confidence=article.match_confidence,
            match_evidence=article.match_evidence, collected_at=article.collected_at,
            dup_status=dup_status.value, dup_of_id=dup_of_id, dup_score=dup_score,
            # duplicatas certas não consomem IA
            analysis_status=(AnalysisStatus.SKIPPED if dup_status == DupStatus.DUPLICATE
                             else AnalysisStatus.PENDING).value,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def get(self, news_id: int) -> News | None:
        return self.s.get(News, news_id)

    def count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(News)) or 0

    def exists_url(self, competitor_id: int, url_normalized: str) -> bool:
        return self.s.scalar(select(News.id).where(
            News.competitor_id == competitor_id, News.url_normalized == url_normalized)) is not None

    def find_by_url(self, competitor_id: int, url_normalized: str) -> News | None:
        return self.s.scalar(select(News).where(News.competitor_id == competitor_id,
                                                News.url_normalized == url_normalized))

    def find_by_external_id(self, competitor_id: int, collector: str, external_id: str) -> News | None:
        return self.s.scalar(select(News).where(
            News.competitor_id == competitor_id, News.source_collector == collector,
            News.external_id == external_id).limit(1))

    def dedup_candidates(self, competitor_id: int, around: datetime, window_days: int) -> list[News]:
        """Notícias do mesmo concorrente publicadas em ±window_days (mais antigas primeiro)."""
        return list(self.s.scalars(select(News).where(
            News.competitor_id == competitor_id,
            News.published_at >= around - timedelta(days=window_days),
            News.published_at <= around + timedelta(days=window_days)).order_by(News.published_at, News.id)))

    def latest_published(self, competitor_id: int | None = None) -> datetime | None:
        q = select(func.max(News.published_at))
        if competitor_id is not None:
            q = q.where(News.competitor_id == competitor_id)
        return self.s.scalar(q)

    def pending_analysis(self, limit: int, max_attempts: int, min_match_confidence: float = 0.0) -> list[News]:
        """Pendentes e falhas ainda com tentativas sobrando (base do `reprocess`)."""
        q = (select(News)
             .where(News.analysis_status.in_([AnalysisStatus.PENDING.value, AnalysisStatus.FAILED.value]),
                    News.analysis_attempts < max_attempts,
                    News.dup_status != DupStatus.DUPLICATE.value,
                    News.match_confidence >= min_match_confidence)
             .order_by(News.published_at.desc()).limit(limit))
        return list(self.s.scalars(q))

    def mark_attempt(self, news: News, status: AnalysisStatus) -> None:
        news.analysis_attempts += 1
        news.analysis_status = status.value
        self.s.flush()

    def save_analysis(self, news: News, **fields) -> NewsAnalysis:  # noqa: ANN003
        row = news.analysis or NewsAnalysis(news_id=news.id)
        for k, v in fields.items():
            setattr(row, k, v)
        row.analyzed_at = fields.get("analyzed_at") or utcnow()
        news.analysis = row
        self.s.add(row)
        news.analysis_status = AnalysisStatus.DONE.value
        self.s.flush()
        return row


class RunRepository:
    def __init__(self, s: Session):
        self.s = s

    def start(self, kind: str, source: str = "") -> CollectionRun:
        run = CollectionRun(kind=kind, source=source, errors=[])
        self.s.add(run)
        self.s.flush()
        return run

    def finish(self, run: CollectionRun) -> None:
        run.finished_at = utcnow()
        self.s.flush()

    def last(self, kind: str = "collect") -> CollectionRun | None:
        return self.s.scalar(select(CollectionRun).where(CollectionRun.kind == kind,
                                                         CollectionRun.finished_at.is_not(None))
                             .order_by(CollectionRun.id.desc()).limit(1))
