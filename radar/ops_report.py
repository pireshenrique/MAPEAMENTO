"""Relatório operacional (docs/relatorio-diario-spec.md, seção 9): o Radar está funcionando e dá para confiar na cobertura?

Somente leitura e só com dados que o banco já tem: `sources` (estado), `collection_runs` (totais e detalhe por fonte por execução)
e `news` (itens armazenados, `body_status`). Execuções anteriores à coluna `by_source` não têm detalhe por fonte e são sinalizadas.
Contagens são somas por execução; como as janelas de coleta se sobrepõem, o mesmo item pode ser contado em mais de uma execução.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.db.tables import Competitor, CollectionRun, News, Source
from radar.settings import AppConfig

_OK_STATUS = {"ok", "not_modified"}


@dataclass
class Counts:
    seen: int = 0
    discarded: int = 0
    matched: int = 0
    stored: int = 0
    errors: int = 0

    def add(self, d: dict) -> None:
        self.seen += d.get("seen", 0)
        self.discarded += d.get("discarded", 0)
        self.matched += d.get("matched", 0)
        self.stored += d.get("stored", 0)
        self.errors += len(d.get("errors", []))


@dataclass
class SourceOps:
    source_id: str
    type: str
    enabled: bool
    verified: bool
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_run: dict | None = None            # detalhe desta fonte na execução mais recente que a consultou
    last_run_at: datetime | None = None
    window: Counts = field(default_factory=Counts)
    runs_in_window: int = 0
    body: dict = field(default_factory=dict)  # body_status -> itens armazenados na janela
    discard_reasons: dict = field(default_factory=dict)

    @property
    def failing(self) -> bool:
        return self.consecutive_failures > 0


@dataclass
class Alert:
    level: str          # ALERTA | AVISO
    source_id: str | None
    message: str


@dataclass
class OpsReport:
    generated_at: datetime
    window_days: int
    sources: list[SourceOps]
    alerts: list[Alert]
    partial_coverage: list[str]
    runs_in_window: int
    runs_without_detail: int
    last_run: CollectionRun | None
    totals: Counts
    stored_by_competitor: dict
    first_run_at: datetime | None


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_ops_report(s: Session, cfg: AppConfig, now: datetime | None = None, days: int | None = None) -> OpsReport:
    now = now or datetime.now(timezone.utc)
    ops, q = cfg.settings.ops_report, cfg.settings.source_quality
    days = days or ops.window_days
    since = now - timedelta(days=days)
    runs = list(s.scalars(select(CollectionRun).where(CollectionRun.kind == "collect", CollectionRun.finished_at.is_not(None))
                          .order_by(CollectionRun.id.desc())))
    in_window = [r for r in runs if _aware(r.started_at) >= since]
    rows = {r.source_id: r for r in s.scalars(select(Source))}
    body_rows = s.execute(select(News.source_id, News.body_status, func.count()).where(News.collected_at >= since)
                          .group_by(News.source_id, News.body_status)).all()
    body: dict[str, dict] = {}
    for sid, st, n in body_rows:
        body.setdefault(sid, {})[st] = n

    sources: list[SourceOps] = []
    for c in sorted(cfg.sources, key=lambda x: (x.tier, x.id)):
        if not c.enabled:
            continue                                   # fontes desabilitadas não fazem parte da cobertura
        row = rows.get(c.id)
        so = SourceOps(c.id, c.type, c.enabled, c.verified, body=body.get(c.id, {}))
        if row:
            so.last_fetch_at, so.last_success_at = _aware(row.last_fetch_at), _aware(row.last_success_at)
            so.last_status, so.last_error, so.consecutive_failures = row.last_status, row.last_error, row.consecutive_failures
        for r in runs:                                 # execução mais recente com detalhe desta fonte
            if r.by_source and c.id in r.by_source:
                so.last_run, so.last_run_at = r.by_source[c.id], _aware(r.started_at)
                break
        reasons: Counter = Counter()
        for r in in_window:
            d = (r.by_source or {}).get(c.id)
            if d is not None:
                so.window.add(d)
                so.runs_in_window += 1
                reasons.update(d.get("reasons", {}))
        so.discard_reasons = dict(reasons)
        sources.append(so)

    totals = Counts()
    for so in sources:
        totals.seen += so.window.seen; totals.discarded += so.window.discarded
        totals.matched += so.window.matched; totals.stored += so.window.stored; totals.errors += so.window.errors
    by_comp = dict(s.execute(select(Competitor.name, func.count()).join(News, News.competitor_id == Competitor.id)
                             .where(News.collected_at >= since).group_by(Competitor.name)).all())
    first_run = _aware(min((r.started_at for r in runs), default=None))
    report = OpsReport(now, days, sources, [], [], len(in_window), sum(1 for r in in_window if r.by_source is None),
                       runs[0] if runs else None, totals, by_comp, first_run)
    _alerts(report, s, cfg, since)
    return report


def _hours(now: datetime, dt: datetime) -> str:
    return f"{(now - dt).total_seconds() / 3600:.1f}h"


def _alerts(rep: OpsReport, s: Session, cfg: AppConfig, since: datetime) -> None:
    ops, q, now = cfg.settings.ops_report, cfg.settings.source_quality, rep.generated_at
    A, partial = rep.alerts, rep.partial_coverage

    def alert(level: str, sid: str | None, msg: str, degraded: bool = False) -> None:
        A.append(Alert(level, sid, msg))
        if degraded and sid and sid not in partial:
            partial.append(sid)

    if rep.last_run is None:
        A.append(Alert("ALERTA", None, "nenhuma coleta registrada"))
    else:
        age = now - _aware(rep.last_run.started_at)
        if age > timedelta(hours=ops.stale_hours):
            A.append(Alert("ALERTA", None, f"ausência de coleta: última execução há {age.total_seconds() / 3600:.1f}h (limite {ops.stale_hours:g}h)"))
    if not rep.sources:
        A.append(Alert("ALERTA", None, "nenhuma fonte habilitada"))

    for so in rep.sources:
        sid = so.source_id
        if so.last_fetch_at is None:
            alert("ALERTA", sid, "habilitada, mas nunca consultada", degraded=True)
            continue
        if so.failing:
            detail = (so.last_error or so.last_status or "erro")[:160]
            alert("ALERTA", sid, f"indisponível na última consulta ({so.last_status}): {detail}", degraded=True)
            if so.consecutive_failures >= ops.max_consecutive_failures:
                alert("ALERTA", sid, f"{so.consecutive_failures} falhas consecutivas (limite {ops.max_consecutive_failures})", degraded=True)
        elif so.last_success_at is None or now - so.last_success_at > timedelta(hours=ops.stale_hours):
            alert("ALERTA", sid, "sem coleta com sucesso há "
                  + (_hours(now, so.last_success_at) if so.last_success_at else "—") + f" (limite {ops.stale_hours:g}h)", degraded=True)
        if (so.last_run and not so.failing and so.last_run.get("status") in _OK_STATUS and so.last_run.get("seen", 0) == 0
                and so.last_run.get("status") != "not_modified"):
            alert("AVISO", sid, "habilitada e consultada com sucesso, mas a última execução trouxe 0 itens")
        stored = sum(so.body.values())
        if stored >= ops.min_body_items:
            with_body = so.body.get("feed", 0) + so.body.get("fetched", 0)
            if with_body / stored < q.min_body_rate:
                alert("AVISO", sid, f"corpo do artigo ausente em {stored - with_body} de {stored} itens armazenados "
                      f"(body_status: {_fmt_body(so.body)}; mínimo {q.min_body_rate:.0%} com corpo)")
        bad = so.body.get("failed", 0) + so.body.get("paywalled", 0)
        if bad:
            alert("AVISO", sid, f"{bad} itens com body_status failed/paywalled")

    # ausência prolongada de casamentos (só quando há histórico suficiente para a afirmação ser verdadeira)
    nm = timedelta(days=ops.no_match_days)
    if rep.first_run_at is not None and rep.sources:
        if now - rep.first_run_at >= nm:
            recent = s.scalar(select(func.count()).select_from(News).where(News.collected_at >= now - nm)) or 0
            if recent == 0:
                A.append(Alert("ALERTA", None, f"nenhum item casado nos últimos {ops.no_match_days} dias (revisar aliases/fontes)"))
    rep.alerts.sort(key=lambda a: (a.level != "ALERTA", a.source_id or ""))


def _fmt_body(body: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(body.items())) or "—"


def _dt(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if dt else "—"


def render_ops_report(rep: OpsReport) -> str:
    L: list[str] = []
    L.append(f"RELATÓRIO OPERACIONAL — {_dt(rep.generated_at)} — janela: {rep.window_days} dias")
    L.append("")
    n = len(rep.sources)
    if rep.partial_coverage:
        L.append(f"COBERTURA PARCIAL: {', '.join(rep.partial_coverage)} indisponível/sem coleta — "
                 f"ausência de notícias NÃO significa dia calmo para essas fontes ({n - len(rep.partial_coverage)} de {n} fontes OK).")
    else:
        L.append(f"Cobertura: {n} de {n} fontes habilitadas com consulta recente bem-sucedida." if n else "Cobertura: nenhuma fonte habilitada.")
    lr = rep.last_run
    L.append(f"Última coleta: {_dt(_aware(lr.started_at)) if lr else '—'}"
             + (f" (encontradas={lr.found} novas={lr.new} duplicadas={lr.duplicates} descartadas={lr.discarded} erros={len(lr.errors or [])})" if lr else ""))
    L.append(f"Execuções na janela: {rep.runs_in_window}"
             + (f" ({rep.runs_without_detail} sem detalhe por fonte: anteriores ao relatório operacional)" if rep.runs_without_detail else ""))
    L.append("")
    L.append("ALERTAS")
    if rep.alerts:
        for a in rep.alerts:
            L.append(f"  [{a.level}] {a.source_id + ': ' if a.source_id else ''}{a.message}")
    else:
        L.append("  nenhum")
    if rep.first_run_at is not None and (rep.generated_at - rep.first_run_at).days < 7:
        L.append(f"  (info) histórico de {(rep.generated_at - rep.first_run_at).total_seconds() / 86400:.1f} dia(s): "
                 "o alerta de 7 dias sem casamentos só se aplica após 7 dias de coleta")
    L.append("")
    L.append("FONTES")
    for so in rep.sources:
        L.append(f"  {so.source_id} ({so.type}) enabled={so.enabled} verified={so.verified}")
        L.append(f"    última consulta: {_dt(so.last_fetch_at)} status={so.last_status or '—'} "
                 f"última com sucesso: {_dt(so.last_success_at)} falhas consecutivas={so.consecutive_failures}")
        if so.last_run:
            d = so.last_run
            L.append(f"    última execução ({_dt(so.last_run_at)}): coletados={d.get('seen', 0)} descartados={d.get('discarded', 0)} "
                     f"casados={d.get('matched', 0)} armazenados={d.get('stored', 0)} erros={len(d.get('errors', []))}")
        else:
            L.append("    última execução: sem detalhe por fonte")
        w = so.window
        L.append(f"    janela ({so.runs_in_window} exec.): coletados={w.seen} descartados={w.discarded} casados={w.matched} "
                 f"armazenados={w.stored} erros={w.errors}"
                 + (f" | descartes: {', '.join(f'{k}={v}' for k, v in sorted(so.discard_reasons.items()))}" if so.discard_reasons else ""))
        L.append(f"    body_status (armazenados na janela): {_fmt_body(so.body)}")
        if so.last_error:
            L.append(f"    último erro: {so.last_error[:200]}")
    L.append("")
    t = rep.totals
    L.append(f"TOTAIS (janela, soma das execuções; itens podem repetir entre execuções por causa da sobreposição): "
             f"coletados={t.seen} descartados={t.discarded} casados={t.matched} armazenados={t.stored} erros={t.errors}")
    L.append("Armazenados por concorrente (janela): "
             + (", ".join(f"{k}={v}" for k, v in sorted(rep.stored_by_competitor.items())) or "nenhum"))
    return "\n".join(L)
