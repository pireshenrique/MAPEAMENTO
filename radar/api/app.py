"""API JSON + páginas HTML (Jinja2/HTMX). Nenhum segredo é exposto ao navegador."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session

from radar.api.schemas import NewsDetailOut, NewsOut, Page, to_out
from radar.bootstrap import Context, build_context
from radar.db import queries
from radar.db.queries import NewsFilters
from radar.settings import load_config


def get_session(request: Request) -> Iterator[Session]:
    s = request.app.state.ctx.session_factory()
    try:
        yield s
    finally:
        s.close()


SessionDep = Annotated[Session, Depends(get_session)]


def _day(d: date | None, end: bool = False) -> datetime | None:
    if d is None:
        return None
    from datetime import timedelta
    start = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return start + timedelta(days=1) if end else start


def filters_dep(
    competitor: str | None = None, days: Annotated[int | None, Query(ge=1, le=3650)] = None,
    date_from: date | None = None, date_to: date | None = None, category: str | None = None,
    relevance_min: Annotated[int | None, Query(ge=1, le=5)] = None,
    impact: Annotated[str | None, Query(pattern="^(positive|neutral|negative)$")] = None,
    source: str | None = None, q: Annotated[str | None, Query(max_length=200)] = None,
    include_duplicates: bool = False, only_analyzed: bool = False,
    sort: Annotated[str, Query(pattern="^(date|relevance)$")] = "date",
) -> NewsFilters:
    return NewsFilters(competitor=competitor or None, days=days, date_from=_day(date_from),
                       date_to=_day(date_to, end=True), category=category or None, relevance_min=relevance_min,
                       impact=impact or None, source=source or None, q=q, include_duplicates=include_duplicates,
                       only_analyzed=only_analyzed, sort=sort)


FiltersDep = Annotated[NewsFilters, Depends(filters_dep)]
api = APIRouter(prefix="/api")


@api.get("/news", response_model=Page)
def list_news(request: Request, s: SessionDep, f: FiltersDep, page: Annotated[int, Query(ge=1)] = 1,
              page_size: Annotated[int | None, Query(ge=1, le=100)] = None):
    size = page_size or request.app.state.ctx.cfg.settings.ui.page_size
    rows, total = queries.search_news(s, f, page, size)
    return Page(items=[to_out(n) for n in rows], total=total, page=page, page_size=size)


@api.get("/news/{news_id}", response_model=NewsDetailOut)
def news_detail(news_id: int, s: SessionDep):
    n = queries.get_news(s, news_id)
    if n is None:
        raise HTTPException(404, "Notícia não encontrada")
    dups = [to_out(d_, NewsOut) for d_ in queries.duplicates_of(s, news_id)]
    return to_out(n, NewsDetailOut, duplicates=[d_ for d_ in dups])


@api.get("/kpis")
def get_kpis(s: SessionDep):
    return queries.kpis(s)


@api.get("/filters")
def get_filters(s: SessionDep):
    return queries.facets(s)


@api.get("/stats")
def get_stats(s: SessionDep, days: Annotated[int, Query(ge=1, le=365)] = 30):
    return queries.stats(s, days)


def create_app(ctx: Context | None = None) -> FastAPI:
    ctx = ctx or build_context(load_config())
    app = FastAPI(title="Competitive Intelligence Radar", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = ctx
    app.include_router(api)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    from radar.api import pages  # páginas HTML (Etapa 7)
    app.include_router(pages.router)
    return app
