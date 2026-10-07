"""Orquestra COLLECT -> NORMALIZE -> VALIDATE -> MATCH -> DEDUP -> STORE (a análise por IA é separada)."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radar.collectors.base import CollectorError, SourceCollector
from radar.db.repositories import CompetitorRepository, NewsRepository, RunRepository, SourceRepository
from radar.dedup.service import Action, Deduplicator
from radar.domain.models import Article, DupStatus
from radar.pipeline.match import match_all
from radar.pipeline.normalize import normalize
from radar.pipeline.validate import validate
from radar.settings import AppConfig

log = logging.getLogger(__name__)
_FATAL_CODES = {"apiKeyInvalid", "apiKeyMissing", "apiKeyDisabled", "apiKeyExhausted", "missingApiKey"}


@dataclass
class CollectStats:
    found: int = 0
    new: int = 0
    duplicates: int = 0          # pulados (mesma URL/ID) + armazenadas como `duplicate`
    possible_duplicates: int = 0
    discarded: Counter = field(default_factory=Counter)  # motivo -> quantidade
    errors: list[str] = field(default_factory=list)
    by_source: dict = field(default_factory=dict)   # source_id -> {seen, matched, stored}
    source_detail: dict = field(default_factory=dict)  # source_id -> {status, errors, discarded, reasons} (relatório operacional)

    @property
    def discarded_total(self) -> int:
        return sum(self.discarded.values())


def _detail(stats: CollectStats, key: str) -> dict:
    return stats.source_detail.setdefault(key, {"status": None, "errors": [], "discarded": 0, "reasons": {}})


def compute_since(session: Session, cfg: AppConfig, now: datetime, days: int | None = None) -> datetime:
    """Primeira coleta: backfill. Depois: desde a última execução (com sobreposição segura)."""
    if days is not None:
        return now - timedelta(days=days)
    last = RunRepository(session).last("collect")
    if last is None:
        return now - timedelta(days=cfg.settings.collection.backfill_days)
    return last.started_at - timedelta(hours=cfg.settings.collection.incremental_overlap_hours)


def run_collection(session: Session, collectors: Sequence[SourceCollector], cfg: AppConfig,
                   now: datetime | None = None, days: int | None = None) -> CollectStats:
    now = now or datetime.now(timezone.utc)
    stats = CollectStats()
    runs = RunRepository(session)
    since = compute_since(session, cfg, now, days)
    run = runs.start("collect", ",".join(c.name for c in collectors), started_at=now)
    session.commit()
    log.info("coleta iniciada: fontes=%s desde=%s", run.source or "(nenhuma)", since.isoformat())
    if not collectors:
        stats.errors.append("nenhuma fonte habilitada (veja config/sources.yaml)")
        log.error(stats.errors[-1])

    comp_rows = {c.name: c for c in CompetitorRepository(session).list(only_active=True)}
    active_cfgs = [c for c in cfg.competitors if c.active and c.name in comp_rows]
    repo = NewsRepository(session)
    dedup = Deduplicator(repo, cfg.settings.dedup)

    srepo = SourceRepository(session)
    for collector in collectors:
        sid = getattr(collector, "source_id", None) or collector.name
        row = srepo.get(sid) if hasattr(collector, "load_state") else None
        if row is not None:
            collector.load_state(row.etag, row.last_modified)   # cache condicional (ETag / If-Modified-Since)
        _detail(stats, sid)                              # toda fonte consultada fica registrada, mesmo sem itens
        targets = [None] if getattr(collector, "scope", "per_competitor") == "feed" else active_cfgs
        for comp in targets:
            label = f"{sid}/{comp.name if comp else 'feed'}"
            try:
                raws = collector.fetch(comp, since, now)
            except CollectorError as e:
                msg = f"{label}: {e}"
                log.error("erro de coleta: %s", msg)
                stats.errors.append(msg)
                d = _detail(stats, sid)
                d["status"] = e.code or "error"
                d["errors"].append(str(e)[:300])
                srepo.record_fetch(sid, ok=False, status=e.code or "error", error=str(e), now=now)
                session.commit()
                if e.code in _FATAL_CODES:
                    log.error("erro fatal de credencial/cota em %s; interrompendo a fonte", sid)
                    break
                continue
            state = getattr(collector, "last_status", "ok")
            if _detail(stats, sid)["status"] is None:     # uma falha anterior (outro alvo da mesma fonte) prevalece
                _detail(stats, sid)["status"] = state
            srepo.record_fetch(sid, ok=True, status=state, etag=getattr(collector, "etag", None),
                               last_modified=getattr(collector, "last_modified", None), now=now)
            stats.found += len(raws)
            for raw in raws:
                key = raw.source_id or sid
                bucket = stats.by_source.setdefault(key, {"seen": 0, "matched": 0, "stored": 0})
                bucket["seen"] += 1
                try:
                    _process(session, repo, dedup, raw, cfg, comp_rows, active_cfgs, now, stats, bucket, _detail(stats, key))
                except Exception as e:  # um artigo problemático não derruba o lote
                    session.rollback()
                    msg = f"erro ao processar artigo '{(raw.title or '')[:60]}': {type(e).__name__}: {e}"
                    log.exception(msg)
                    stats.errors.append(msg)
            session.commit()
    for key, b in stats.by_source.items():
        srepo.add_counts(key, seen=b["seen"], matched=b["matched"], stored=b["stored"])
    session.commit()

    run = session.get(type(run), run.id)
    run.found, run.new, run.duplicates = stats.found, stats.new, stats.duplicates + stats.possible_duplicates
    run.discarded, run.errors = stats.discarded_total, stats.errors
    run.by_source = {k: {"seen": 0, "matched": 0, "stored": 0, **stats.by_source.get(k, {}), **d}
                     for k, d in stats.source_detail.items()}
    runs.finish(run)
    session.commit()
    log.info("coleta concluída: encontradas=%d novas=%d duplicadas=%d possíveis_duplicatas=%d descartadas=%d erros=%d",
             stats.found, stats.new, stats.duplicates, stats.possible_duplicates, stats.discarded_total, len(stats.errors))
    if stats.discarded:
        log.info("descartes por motivo: %s", dict(stats.discarded))
    return stats


def _process(session, repo, dedup, raw, cfg, comp_rows, active_cfgs, now, stats, bucket, detail) -> None:  # noqa: ANN001
    def discard(reason: str) -> None:
        stats.discarded[reason] += 1
        detail["discarded"] += 1
        detail["reasons"][reason] = detail["reasons"].get(reason, 0) + 1

    n = normalize(raw, now)
    if (reason := validate(n, now, cfg.settings.validation, cfg.settings.collection)):
        discard(reason)
        return
    matches = match_all(n, active_cfgs, cfg.settings.matching)
    if not matches:
        discard("sem_concorrente")
        return
    bucket["matched"] += 1
    for m in matches:
        article = Article(**n.model_dump(), competitor_name=m.competitor,
                          match_confidence=m.confidence, match_evidence=m.evidence)
        comp_id = comp_rows[m.competitor].id
        res = dedup.check(article, comp_id)
        if res.action == Action.SKIP:
            stats.duplicates += 1
            continue
        try:
            with session.begin_nested():
                repo.add(article, comp_id, dup_status=res.status, dup_of_id=res.dup_of_id, dup_score=res.score)
        except IntegrityError:  # corrida/duplicata exata não detectada antes
            stats.duplicates += 1
            continue
        bucket["stored"] += 1
        if res.status == DupStatus.DUPLICATE:
            stats.duplicates += 1
        else:
            stats.new += 1
            if res.status == DupStatus.POSSIBLE:
                stats.possible_duplicates += 1
