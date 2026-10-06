"""Consultas de leitura (feed, filtros, KPIs, estatísticas). Usadas pela API e pela interface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from radar.db.tables import Category, CollectionRun, Competitor, News, NewsAnalysis

SORTS = {"date": News.published_at.desc(), "relevance": NewsAnalysis.relevance_score.desc().nulls_last()}


@dataclass
class NewsFilters:
    competitor: str | None = None
    days: int | None = None            # período relativo (últimos N dias)
    date_from: datetime | None = None
    date_to: datetime | None = None
    category: str | None = None
    relevance_min: int | None = None   # 1..5
    impact: str | None = None
    source: str | None = None          # nome ou domínio da fonte
    q: str | None = None
    include_duplicates: bool = False   # `duplicate` fica oculto por padrão; `possible_duplicate` aparece
    only_analyzed: bool = False
    sort: str = "date"


def _like(term: str) -> str:
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc.lower()}%"


def _apply(stmt: Select, f: NewsFilters, now: datetime | None = None) -> Select:
    now = now or datetime.now(timezone.utc)
    if not f.include_duplicates:
        stmt = stmt.where(News.dup_status != "duplicate")
    if f.competitor:
        stmt = stmt.where(Competitor.name == f.competitor)
    if f.days:
        stmt = stmt.where(News.published_at >= now - timedelta(days=f.days))
    if f.date_from:
        stmt = stmt.where(News.published_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(News.published_at < f.date_to)
    if f.category:
        stmt = stmt.where(NewsAnalysis.category == f.category)
    if f.relevance_min:
        stmt = stmt.where(NewsAnalysis.relevance_score >= f.relevance_min)
    if f.impact:
        stmt = stmt.where(NewsAnalysis.competitive_impact == f.impact)
    if f.source:
        stmt = stmt.where(or_(News.source_name == f.source, News.source_domain == f.source))
    if f.only_analyzed:
        stmt = stmt.where(NewsAnalysis.news_id.is_not(None))
    if f.q and f.q.strip():
        pat = _like(f.q.strip())
        stmt = stmt.where(or_(func.lower(News.title).like(pat, escape="\\"),
                              func.lower(func.coalesce(News.description, "")).like(pat, escape="\\"),
                              func.lower(func.coalesce(NewsAnalysis.summary, "")).like(pat, escape="\\")))
    return stmt


def _base() -> Select:
    return (select(News).join(Competitor, News.competitor_id == Competitor.id)
            .outerjoin(NewsAnalysis, NewsAnalysis.news_id == News.id))


def search_news(s: Session, f: NewsFilters, page: int = 1, page_size: int = 25, now: datetime | None = None
                ) -> tuple[list[News], int]:
    page, page_size = max(page, 1), min(max(page_size, 1), 100)
    total = s.scalar(_apply(select(func.count(News.id)).select_from(News)
                            .join(Competitor, News.competitor_id == Competitor.id)
                            .outerjoin(NewsAnalysis, NewsAnalysis.news_id == News.id), f, now)) or 0
    order = [SORTS.get(f.sort, SORTS["date"])]
    if f.sort == "relevance":
        order.append(News.published_at.desc())
    order.append(News.id.desc())
    stmt = (_apply(_base(), f, now).options(joinedload(News.competitor), joinedload(News.analysis))
            .order_by(*order).limit(page_size).offset((page - 1) * page_size))
    return list(s.scalars(stmt).unique()), total


def get_news(s: Session, news_id: int) -> News | None:
    return s.scalar(select(News).where(News.id == news_id)
                    .options(joinedload(News.competitor), joinedload(News.analysis)))


def duplicates_of(s: Session, news_id: int) -> list[News]:
    return list(s.scalars(select(News).where(News.dup_of_id == news_id).order_by(News.published_at)))


def kpis(s: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    visible = News.dup_status != "duplicate"

    def count(*conds, analysis=False) -> int:
        q = select(func.count(News.id)).select_from(News)
        if analysis:
            q = q.join(NewsAnalysis, NewsAnalysis.news_id == News.id)
        return s.scalar(q.where(visible, *conds)) or 0

    last_run = s.scalar(select(CollectionRun).where(CollectionRun.kind == "collect", CollectionRun.finished_at.is_not(None))
                        .order_by(CollectionRun.id.desc()).limit(1))
    return {
        "collected": count(),
        "relevant": count(NewsAnalysis.is_relevant.is_(True), analysis=True),
        "high_relevance": count(NewsAnalysis.relevance_score >= 4, analysis=True),
        "competitors_monitored": s.scalar(select(func.count(Competitor.id)).where(Competitor.active.is_(True))) or 0,
        "last_24h": count(News.published_at >= now - timedelta(hours=24)),
        "last_7d": count(News.published_at >= now - timedelta(days=7)),
        "pending_analysis": count(News.analysis_status.in_(["pending", "failed"])),
        "analyzed": count(News.analysis_status == "done"),
        "last_collection_at": last_run.finished_at if last_run else None,
    }


def facets(s: Session) -> dict:
    """Valores disponíveis para os filtros (somente o que existe nos dados)."""
    sources = s.execute(select(News.source_name, func.count(News.id)).where(News.source_name.is_not(None))
                        .group_by(News.source_name).order_by(func.count(News.id).desc()).limit(100)).all()
    return {
        "competitors": list(s.scalars(select(Competitor.name).where(Competitor.active.is_(True)).order_by(Competitor.name))),
        "categories": list(s.scalars(select(Category.name).where(Category.active.is_(True)).order_by(Category.sort_order))),
        "sources": [name for name, _ in sources],
        "impacts": ["positive", "neutral", "negative"],
        "relevance_levels": [1, 2, 3, 4, 5],
    }


def stats(s: Session, days: int = 30, now: datetime | None = None) -> dict:
    """Agregações para a área de inteligência. Cada bloco informa o tamanho da amostra (`n`)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    vis = [News.dup_status != "duplicate", News.published_at >= since]

    by_comp = s.execute(select(Competitor.name, func.count(News.id)).join(News, News.competitor_id == Competitor.id)
                        .where(*vis).group_by(Competitor.name).order_by(func.count(News.id).desc())).all()
    per_day: dict[str, int] = {}
    for (d,) in s.execute(select(News.published_at).where(*vis)):
        per_day[d.date().isoformat()] = per_day.get(d.date().isoformat(), 0) + 1
    timeline = [{"date": (since.date() + timedelta(days=i)).isoformat(),
                 "count": per_day.get((since.date() + timedelta(days=i)).isoformat(), 0)} for i in range(days + 1)]

    def dist(col):
        rows = s.execute(select(col, func.count(News.id)).select_from(News)
                         .join(NewsAnalysis, NewsAnalysis.news_id == News.id).where(*vis)
                         .group_by(col).order_by(func.count(News.id).desc())).all()
        return [{"label": str(k), "count": v} for k, v in rows]

    analyzed = s.scalar(select(func.count(News.id)).select_from(News)
                        .join(NewsAnalysis, NewsAnalysis.news_id == News.id).where(*vis)) or 0
    rel = {r["label"]: r["count"] for r in dist(NewsAnalysis.relevance_score)}
    return {
        "days": days,
        "total": sum(c for _, c in by_comp),
        "analyzed": analyzed,
        "by_competitor": [{"label": n, "count": c} for n, c in by_comp],
        "timeline": timeline,
        "relevance": [{"label": str(i), "count": rel.get(str(i), 0)} for i in range(1, 6)],
        "impact": dist(NewsAnalysis.competitive_impact),
        "categories": dist(NewsAnalysis.category)[:10],
    }
