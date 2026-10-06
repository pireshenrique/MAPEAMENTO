from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    is_relevant: bool
    relevance_score: int
    competitive_impact: str
    sentiment: str
    category: str
    subcategory: str | None
    summary: str
    key_points: list[str]
    strategic_reason: str
    analyzed_at: datetime
    model_used: str


class NewsOut(BaseModel):
    id: int
    competitor: str
    title: str
    description: str | None
    url: str
    source_name: str | None
    source_domain: str | None
    published_at: datetime
    image_url: str | None
    dup_status: str
    analysis_status: str
    analysis: AnalysisOut | None


class NewsDetailOut(NewsOut):
    author: str | None
    collected_at: datetime
    match_confidence: float
    dup_of_id: int | None
    dup_score: float | None
    duplicates: list[NewsOut] = []


class Page(BaseModel):
    items: list[NewsOut]
    total: int
    page: int
    page_size: int


def to_out(n, cls=NewsOut, **extra):  # noqa: ANN001
    return cls(id=n.id, competitor=n.competitor.name, title=n.title, description=n.description, url=n.url,
               source_name=n.source_name, source_domain=n.source_domain, published_at=n.published_at,
               image_url=n.image_url, dup_status=n.dup_status, analysis_status=n.analysis_status,
               analysis=AnalysisOut.model_validate(n.analysis) if n.analysis else None,
               **({k: getattr(n, k) for k in ("author", "collected_at", "match_confidence", "dup_of_id", "dup_score")}
                  if cls is NewsDetailOut else {}), **extra)
