"""Páginas HTML (server-side, Jinja2 + HTMX). Sem JavaScript próprio e sem segredos no navegador."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from radar.db import queries
from radar.db.queries import NewsFilters

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "ui" / "templates")

IMPACT_LABEL = {"negative": "Negativo", "neutral": "Neutro", "positive": "Positivo"}
IMPACT_HINT = {"negative": "desfavorável à Lorenzetti", "neutral": "neutro/incerto", "positive": "favorável à Lorenzetti"}
RELEVANCE_LABEL = {1: "Irrelevante", 2: "Baixa", 3: "Relevante", 4: "Alta", 5: "Crítica"}
PERIODS = [(1, "Últimas 24h"), (7, "Últimos 7 dias"), (30, "Últimos 30 dias"), (90, "Últimos 90 dias")]


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except Exception:  # tzdata ausente
        return timezone(timedelta(hours=-3))


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def parse_filters(p: Mapping[str, str]) -> NewsFilters:
    """Tolerante a campos vazios do formulário (diferente da API, que valida estritamente)."""
    rel = _int(p.get("relevance_min"))
    return NewsFilters(
        competitor=p.get("competitor") or None, days=_int(p.get("days")), category=p.get("category") or None,
        relevance_min=rel if rel in (1, 2, 3, 4, 5) else None,
        impact=p.get("impact") if p.get("impact") in IMPACT_LABEL else None,
        source=p.get("source") or None, q=(p.get("q") or "")[:200] or None,
        include_duplicates=p.get("include_duplicates") in ("1", "true", "on"),
        sort=p.get("sort") if p.get("sort") in ("date", "relevance") else "date")


def _env(request: Request) -> dict:
    tz = _tz(request.app.state.ctx.cfg.settings.ui.timezone)

    def fmt_dt(d: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
        return d.astimezone(tz).strftime(fmt) if d else "—"

    def safe_url(u: str | None) -> str:
        return u if u and urlsplit(u).scheme in ("http", "https") else "#"

    def qs(**over) -> str:
        params = {k: v for k, v in request.query_params.items() if v != ""}
        params.update({k: v for k, v in over.items() if v is not None})
        return urlencode(params)

    return {"request": request, "fmt_dt": fmt_dt, "safe_url": safe_url, "qs": qs, "IMPACT_LABEL": IMPACT_LABEL,
            "IMPACT_HINT": IMPACT_HINT, "RELEVANCE_LABEL": RELEVANCE_LABEL, "PERIODS": PERIODS}


def _render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {**_env(request), **ctx})


@router.get("/")
def index(request: Request):
    app_ctx = request.app.state.ctx
    f = parse_filters(request.query_params)
    page = max(_int(request.query_params.get("page")) or 1, 1)
    size = app_ctx.cfg.settings.ui.page_size
    s = app_ctx.session_factory()
    try:
        now = request.app.state.now()
        rows, total = queries.search_news(s, f, page, size, now)
        data = dict(news=rows, total=total, page=page, pages=max((total + size - 1) // size, 1), f=f,
                    kpis=queries.kpis(s, now), facets=queries.facets(s), params=dict(request.query_params))
        return _render(request, "index.html", **data)
    finally:
        s.close()


@router.get("/news/{news_id}")
def detail(request: Request, news_id: int):
    s = request.app.state.ctx.session_factory()
    try:
        n = queries.get_news(s, news_id)
        if n is None:
            raise HTTPException(404, "Notícia não encontrada")
        original = queries.get_news(s, n.dup_of_id) if n.dup_of_id else None
        return _render(request, "detail.html", n=n, duplicates=queries.duplicates_of(s, n.id), original=original)
    finally:
        s.close()


@router.get("/intelligence")
def intelligence(request: Request):
    app_ctx = request.app.state.ctx
    days = _int(request.query_params.get("days")) or 30
    days = days if days in (7, 30, 90) else 30
    s = app_ctx.session_factory()
    try:
        now = request.app.state.now()
        st = queries.stats(s, days, now)
        return _render(request, "intelligence.html", st=st, days=days,
                       min_sample=app_ctx.cfg.settings.ui.min_chart_sample, kpis=queries.kpis(s, now))
    finally:
        s.close()
