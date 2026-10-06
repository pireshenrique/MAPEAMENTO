"""Contratos de coleta. Novas fontes (RSS, sites oficiais, outras APIs) implementam SourceCollector."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from radar.domain.models import RawArticle
from radar.settings import CompetitorConfig


class CollectorError(Exception):
    """Falha de coleta (API, rede, autenticação). Sempre propagada e registrada, nunca engolida."""

    def __init__(self, message: str, *, retryable: bool = False, code: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


@runtime_checkable
class SourceCollector(Protocol):
    name: str

    def fetch(self, competitor: CompetitorConfig, since: datetime, until: datetime | None = None) -> list[RawArticle]:
        """Busca artigos publicados desde `since` para o concorrente. Levanta CollectorError em falha."""
        ...


class QueryStrategy(Protocol):
    """Define quais consultas são feitas por concorrente (permite estratégias distintas por empresa)."""

    def build(self, competitor: CompetitorConfig) -> list[str]: ...
