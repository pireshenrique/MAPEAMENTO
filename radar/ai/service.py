"""Etapa CLASSIFY + SAVE ANALYSIS sobre notícias já armazenadas. Falha de IA nunca perde notícia."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from radar.ai.analyzer import AnalysisError, Analyzer
from radar.ai.base import LLMError
from radar.ai.prompts import ArticleInput
from radar.db.repositories import NewsRepository
from radar.db.tables import News
from radar.domain.models import AnalysisStatus
from radar.settings import AIConfig, AppConfig

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3


@dataclass
class AnalysisStats:
    analyzed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def to_input(n: News, priority: list[str]) -> ArticleInput:
    return ArticleInput(title=n.title, description=n.description, content=n.raw_content, source_name=n.source_name,
                        published_at=n.published_at, competitor_name=n.competitor.name, priority_categories=priority)


def analyze_pending(session: Session, analyzer: Analyzer, cfg: AppConfig, limit: int | None = None) -> AnalysisStats:
    ai: AIConfig = cfg.settings.ai
    repo = NewsRepository(session)
    stats = AnalysisStats()
    pending = repo.pending_analysis(limit or ai.max_analyses_per_run, ai.max_attempts, ai.min_match_confidence)
    log.info("análise iniciada: %d notícias pendentes", len(pending))
    consecutive_provider_errors = 0
    for news in pending:
        priority = next((c.priority_categories for c in cfg.competitors if c.name == news.competitor.name), [])
        try:
            out = analyzer.analyze(to_input(news, priority))
        except AnalysisError as e:
            log.error("análise falhou (news_id=%s): %s", news.id, e)
            repo.mark_attempt(news, AnalysisStatus.FAILED)
            stats.failed += 1; stats.errors.append(f"news {news.id}: {e}")
        except LLMError as e:
            log.error("erro do provedor de IA (news_id=%s): %s", news.id, e)
            repo.mark_attempt(news, AnalysisStatus.FAILED)
            stats.failed += 1; stats.errors.append(f"news {news.id}: {e}")
            consecutive_provider_errors += 1
            session.commit()
            if consecutive_provider_errors >= MAX_CONSECUTIVE_PROVIDER_ERRORS:
                log.error("provedor de IA indisponível; interrompendo a análise (restante segue pendente)")
                break
            continue
        else:
            consecutive_provider_errors = 0
            r = out.result
            repo.save_analysis(news, is_relevant=r.is_relevant, relevance_score=r.relevance_score,
                               competitive_impact=r.competitive_impact.value, sentiment=r.sentiment.value,
                               category=r.category, subcategory=r.subcategory, summary=r.summary,
                               key_points=r.key_points, strategic_reason=r.strategic_reason,
                               model_used=out.model, prompt_version=out.prompt_version, raw_response=out.raw_response)
            news.analysis_attempts += 1
            stats.analyzed += 1
        session.commit()  # progresso persistido item a item
    log.info("análise concluída: analisadas=%d falhas=%d", stats.analyzed, stats.failed)
    return stats
