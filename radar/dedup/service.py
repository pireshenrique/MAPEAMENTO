"""Etapa DEDUPLICATE: quatro camadas, estratégia conservadora (nada é apagado).

1. URL normalizada igual            -> SKIP (mesmo registro; não insere de novo)
2. external_id + coletor iguais     -> SKIP
3. título normalizado/hash iguais   -> STORE como `duplicate` (republicação; não vai para a IA)
4. similaridade textual alta        -> STORE como `possible_duplicate` (continua sendo analisada)
A comparação é sempre dentro do mesmo concorrente e de uma janela de datas.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rapidfuzz import fuzz

from radar.db.repositories import NewsRepository
from radar.db.tables import News
from radar.domain.models import Article, DupStatus
from radar.settings import DedupConfig


class Action(StrEnum):
    STORE = "store"
    SKIP = "skip"


@dataclass(frozen=True)
class DedupResult:
    action: Action
    status: DupStatus = DupStatus.UNIQUE
    dup_of_id: int | None = None
    score: float | None = None
    layer: str = "none"


def _root(row: News, repo: NewsRepository) -> int:
    """Aponta sempre para a notícia original, não para outra cópia."""
    seen = set()
    while row.dup_of_id and row.id not in seen:
        seen.add(row.id)
        parent = repo.get(row.dup_of_id)
        if parent is None:
            break
        row = parent
    return row.id


def similarity(a: str, b: str) -> float:
    """token_set_ratio com trava: títulos de tamanhos muito diferentes não são 'quase iguais'."""
    ta, tb = a.split(), b.split()
    if not ta or not tb or min(len(ta), len(tb)) / max(len(ta), len(tb)) < 0.6:
        return 0.0
    return fuzz.token_set_ratio(a, b)


class Deduplicator:
    def __init__(self, repo: NewsRepository, cfg: DedupConfig):
        self.repo, self.cfg = repo, cfg

    def check(self, article: Article, competitor_id: int) -> DedupResult:
        repo = self.repo
        if (row := repo.find_by_url(competitor_id, article.url_normalized)):
            return DedupResult(Action.SKIP, DupStatus.DUPLICATE, _root(row, repo), 100.0, "url")
        if article.external_id and (row := repo.find_by_external_id(
                competitor_id, article.source_collector, article.external_id)):
            return DedupResult(Action.SKIP, DupStatus.DUPLICATE, _root(row, repo), 100.0, "external_id")

        candidates = repo.dedup_candidates(competitor_id, article.published_at, self.cfg.window_days)
        for row in candidates:  # mais antigas primeiro => aponta para a original
            if row.title_normalized == article.title_normalized or row.content_hash == article.content_hash:
                return DedupResult(Action.STORE, DupStatus.DUPLICATE, _root(row, repo), 100.0, "title")

        best: tuple[float, News] | None = None
        for row in candidates:
            score = similarity(article.title_normalized, row.title_normalized)
            if score >= self.cfg.similarity_threshold and (best is None or score > best[0]):
                best = (score, row)
        if best:
            return DedupResult(Action.STORE, DupStatus.POSSIBLE, _root(best[1], repo), best[0], "similarity")
        return DedupResult(Action.STORE)
