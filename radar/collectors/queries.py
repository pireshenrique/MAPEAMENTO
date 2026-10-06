"""Estratégias de consulta. A padrão evita termos ambíguos isolados."""
from __future__ import annotations

from radar.settings import CompetitorConfig

MAX_QUERY_LEN = 480  # limite da News API é 500


def _quote(term: str) -> str:
    return '"' + term.replace('"', "") + '"'


def _or(terms: list[str]) -> str:
    return "(" + " OR ".join(_quote(t) for t in terms) + ")"


def _fit(terms: list[str], budget: int) -> list[str]:
    out, used = [], 0
    for t in terms:
        used += len(t) + 8
        if used > budget:
            break
        out.append(t)
    return out


class DefaultQueryStrategy:
    """1) aliases fortes em OR; 2) alias ambíguo AND termos de contexto; 3) palavras-chave em OR."""

    def __init__(self, max_context_terms: int = 6):
        self.max_context_terms = max_context_terms

    def build(self, c: CompetitorConfig) -> list[str]:
        queries: list[str] = []
        if c.aliases:
            queries.append(_or(_fit(c.aliases, MAX_QUERY_LEN)))
        if c.ambiguous_aliases:
            ctx = [t for t in c.context_terms if len(t) > 3][: self.max_context_terms]
            if ctx:
                queries.append(f"{_or(c.ambiguous_aliases)} AND {_or(ctx)}"[:MAX_QUERY_LEN])
        if c.keywords:
            queries.append(_or(_fit(c.keywords, MAX_QUERY_LEN)))
        # remove vazias/duplicadas preservando ordem
        return list(dict.fromkeys(q for q in queries if q.strip("() ")))
