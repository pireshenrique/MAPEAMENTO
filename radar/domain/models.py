"""Modelos de domínio (independentes de banco, API e fornecedor)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DupStatus(StrEnum):
    UNIQUE = "unique"
    POSSIBLE = "possible_duplicate"
    DUPLICATE = "duplicate"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Impact(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class RawArticle(BaseModel):
    """Saída bruta e já tipada de um coletor, antes de normalização/validação."""

    source_collector: str
    external_id: str | None = None
    title: str | None = None
    description: str | None = None
    url: str | None = None
    source_name: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    content: str | None = None
    query: str | None = None  # consulta que originou o artigo (auditoria)


class Article(BaseModel):
    """Artigo normalizado e validado, atribuído a um concorrente."""

    source_collector: str
    external_id: str | None = None
    competitor_name: str
    title: str
    description: str | None = None
    url: str
    url_normalized: str
    title_normalized: str
    content_hash: str
    source_name: str | None = None
    source_domain: str | None = None
    author: str | None = None
    published_at: datetime
    image_url: str | None = None
    raw_content: str | None = None
    match_confidence: float = 1.0
    match_evidence: list[str] = Field(default_factory=list)
    collected_at: datetime
