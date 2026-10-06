"""Etapa MATCH: confirma, por contexto, a qual concorrente a notícia pertence."""
from __future__ import annotations

from dataclasses import dataclass, field

from radar.domain.models import NormalizedArticle
from radar.settings import CompetitorConfig, MatchingConfig


@dataclass
class MatchResult:
    competitor: str
    confidence: float
    evidence: list[str] = field(default_factory=list)


def _domain_hit(article_domain: str | None, domains: list[str]) -> str | None:
    if not article_domain:
        return None
    for d in domains:
        if article_domain == d or article_domain.endswith("." + d):
            return d
    return None


def match_competitor(n: NormalizedArticle, c: CompetitorConfig, cfg: MatchingConfig) -> MatchResult:
    from radar.pipeline.text import has_term

    title = n.title
    body = " ".join(filter(None, [n.description, n.raw_content]))
    full = f"{title} {body}"
    evidence: list[str] = []
    conf = 0.0

    if d := _domain_hit(n.source_domain, c.domains):
        evidence.append(f"domínio oficial:{d}")
        conf = max(conf, 0.9)

    for alias in c.aliases:
        if has_term(title, alias):
            evidence.append(f"alias no título:{alias}")
            conf = max(conf, 0.95)
        elif has_term(body, alias):
            evidence.append(f"alias no texto:{alias}")
            conf = max(conf, 0.8)

    strong = conf >= 0.8
    # exclusão só vale se não houver evidência forte
    excl = [t for t in c.exclude_terms if has_term(full, t)]
    if excl and not strong:
        return MatchResult(c.name, 0.0, [f"termo de exclusão:{t}" for t in excl])

    if not strong:
        for alias in c.ambiguous_aliases:
            in_title = has_term(title, alias, case_sensitive=True)
            if not (in_title or has_term(body, alias, case_sensitive=True)):
                continue  # "roca" minúsculo ou ausente não conta
            ctx = [t for t in c.context_terms if has_term(full, t)]
            score = len(ctx) + (1 if in_title else 0)
            if score >= cfg.ambiguous_min_context_hits:
                evidence.append(f"alias ambíguo:{alias} + contexto:{','.join(ctx[:4])}")
                conf = max(conf, 0.9 if in_title and len(ctx) >= 2 else 0.75)
            else:
                evidence.append(f"alias ambíguo sem contexto suficiente:{alias}")
                conf = max(conf, 0.3)
    return MatchResult(c.name, conf, evidence)


def match_all(n: NormalizedArticle, competitors: list[CompetitorConfig], cfg: MatchingConfig) -> list[MatchResult]:
    """Resultados aceitos (confiança >= mínimo), do mais para o menos confiante."""
    results = [match_competitor(n, c, cfg) for c in competitors if c.active]
    return sorted((r for r in results if r.confidence >= cfg.min_confidence), key=lambda r: -r.confidence)
