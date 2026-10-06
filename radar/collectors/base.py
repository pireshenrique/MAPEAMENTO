"""Contratos de coleta. Novas fontes (RSS, sites oficiais, outras APIs) implementam SourceCollector."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from radar.domain.models import RawArticle
from radar.settings import CompetitorConfig


class CollectorError(Exception):
    """Falha de coleta (API, rede, autenticação, robots). Sempre propagada e registrada, nunca engolida."""

    def __init__(self, message: str, *, retryable: bool = False, code: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


@runtime_checkable
class SourceCollector(Protocol):
    """Contrato único de fontes.

    scope = "per_competitor": o runner chama fetch() uma vez por concorrente (ex.: News API).
    scope = "feed": o runner chama fetch(None, ...) uma vez; o MATCH testa cada item contra todos os concorrentes.
    Coletores podem expor opcionalmente `source_id`, `load_state(etag, last_modified)` e `state`
    (etag/last_modified/status) para cache condicional e métricas por fonte.
    """

    name: str
    scope: str

    def fetch(self, competitor: CompetitorConfig | None, since: datetime, until: datetime | None = None) -> list[RawArticle]:
        """Busca artigos publicados desde `since`. Levanta CollectorError em falha."""
        ...


class QueryStrategy(Protocol):
    """Define quais consultas são feitas por concorrente (permite estratégias distintas por empresa)."""

    def build(self, competitor: CompetitorConfig) -> list[str]: ...
