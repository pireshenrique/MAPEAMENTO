"""Tabelas SQLAlchemy 2.0 (tipos portáveis SQLite/PostgreSQL)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Guarda UTC e sempre devolve datetime com tzinfo (SQLite descarta tz)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem timezone não é permitido")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return None if value is None else value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Competitor(Base):
    __tablename__ = "competitors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    domains: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class News(Base):
    __tablename__ = "news"
    __table_args__ = (
        UniqueConstraint("competitor_id", "url_normalized", name="uq_news_competitor_url"),
        Index("ix_news_external", "source_collector", "external_id"),
        Index("ix_news_published_at", "published_at"),
        Index("ix_news_title_norm", "title_normalized"),
        Index("ix_news_analysis_status", "analysis_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_collector: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str | None] = mapped_column(String(255))
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    url_normalized: Mapped[str] = mapped_column(String(1000))
    title_normalized: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_domain: Mapped[str | None] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    image_url: Mapped[str | None] = mapped_column(Text)
    raw_content: Mapped[str | None] = mapped_column(Text)
    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    match_evidence: Mapped[list] = mapped_column(JSON, default=list)
    source_id: Mapped[str | None] = mapped_column(String(80))
    source_type: Mapped[str | None] = mapped_column(String(30))
    body_status: Mapped[str] = mapped_column(String(12), default="none")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    dup_status: Mapped[str] = mapped_column(String(20), default="unique")
    dup_of_id: Mapped[int | None] = mapped_column(ForeignKey("news.id"))
    dup_score: Mapped[float | None] = mapped_column(Float)
    analysis_status: Mapped[str] = mapped_column(String(10), default="pending")
    analysis_attempts: Mapped[int] = mapped_column(Integer, default=0)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    competitor: Mapped[Competitor] = relationship()
    analysis: Mapped["NewsAnalysis | None"] = relationship(back_populates="news", uselist=False)


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"
    __table_args__ = (Index("ix_analysis_relevance", "relevance_score"),)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), primary_key=True)
    is_relevant: Mapped[bool] = mapped_column(Boolean)
    relevance_score: Mapped[int] = mapped_column(Integer)
    competitive_impact: Mapped[str] = mapped_column(String(10))
    sentiment: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(80))
    subcategory: Mapped[str | None] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    strategic_reason: Mapped[str] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    model_used: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(20))
    raw_response: Mapped[str | None] = mapped_column(Text)

    news: Mapped[News] = relationship(back_populates="analysis")


class Source(Base):
    """Estado e métricas operacionais de cada fonte configurada em sources.yaml."""

    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80), unique=True)
    type: Mapped[str] = mapped_column(String(30))
    url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tier: Mapped[int] = mapped_column(Integer, default=2)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(80))
    last_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    fetches_ok: Mapped[int] = mapped_column(Integer, default=0)
    fetches_failed: Mapped[int] = mapped_column(Integer, default=0)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_matched: Mapped[int] = mapped_column(Integer, default=0)
    items_stored: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="collect")
    source: Mapped[str] = mapped_column(String(40), default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    found: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    discarded: Mapped[int] = mapped_column(Integer, default=0)
    analyzed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    # detalhe por fonte desta execução: {source_id: {status, errors, seen, discarded, reasons, matched, stored}}; NULL em execuções antigas
    by_source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
