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


class BodyStatus(StrEnum):
    NONE = "none"            # só título/resumo disponíveis
    FEED = "feed"            # corpo completo veio na própria fonte (ex.: content:encoded)
    FETCHED = "fetched"      # corpo obtido pelo Enricher (P1)
    PAYWALLED = "paywalled"
    FAILED = "failed"


class RawArticle(BaseModel):
    """Saída bruta e já tipada de um coletor, antes de normalização/validação."""

    source_collector: str
    source_id: str | None = None       # id em sources.yaml
    source_type: str | None = None     # newsapi | rss | cvm_ipe | ...
    body: str | None = None            # corpo completo, quando a fonte fornece
    body_status: str = BodyStatus.NONE.value
    tags: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
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


class NormalizedArticle(BaseModel):
    """Saída da etapa NORMALIZE (campos essenciais ainda podem faltar; VALIDATE decide)."""

    source_collector: str
    source_id: str | None = None
    source_type: str | None = None
    body_status: str = "none"
    tags: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
    external_id: str | None = None
    title: str = ""
    description: str | None = None
    url: str = ""
    url_normalized: str = ""
    title_normalized: str = ""
    content_hash: str = ""
    source_name: str | None = None
    source_domain: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    raw_content: str | None = None
    collected_at: datetime


class Article(NormalizedArticle):
    """Artigo validado e atribuído a um concorrente (pronto para deduplicação/armazenamento)."""

    competitor_name: str
    published_at: datetime
    match_confidence: float = 1.0
    match_evidence: list[str] = Field(default_factory=list)
