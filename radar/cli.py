"""CLI: collect | analyze | run | reprocess | serve."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from sqlalchemy import update

from radar.ai.analyzer import Analyzer
from radar.ai.base import LLMError
from radar.ai.factory import build_provider
from radar.ai.service import AnalysisStats, analyze_pending
from radar.bootstrap import Context, build_context
from radar.collectors.registry import build_collectors
from radar.db.engine import session_scope
from radar.db.repositories import CategoryRepository, RunRepository, SourceRepository
from radar.db.tables import News
from radar.logging_setup import setup_logging
from radar.pipeline.runner import CollectStats, run_collection
from radar.settings import load_config

app = typer.Typer(help="Competitive Intelligence Radar", no_args_is_help=True, add_completion=False)
sources_app = typer.Typer(help="Fontes: lista, relatório de qualidade, descoberta", no_args_is_help=True)
app.add_typer(sources_app, name="sources")
log = logging.getLogger("radar.cli")


def _ctx() -> Context:
    cfg = load_config()
    setup_logging(cfg.env.log_level, cfg.env.log_format)
    return build_context(cfg)


def do_collect(ctx: Context, days: int | None = None) -> CollectStats:
    with session_scope(ctx.session_factory) as s:
        return run_collection(s, build_collectors(ctx.cfg), ctx.cfg, days=days)


def do_analyze(ctx: Context, limit: int | None = None) -> AnalysisStats:
    """IA indisponível/sem chave não derruba nada: notícias seguem armazenadas e pendentes."""
    stats = AnalysisStats()
    with session_scope(ctx.session_factory) as s:
        runs = RunRepository(s)
        run = runs.start("analyze", ctx.cfg.env.ai_provider)
        s.commit()
        try:
            provider = build_provider(ctx.cfg)
            analyzer = Analyzer(provider, ctx.cfg.settings.ai, ctx.cfg.profile, CategoryRepository(s).names())
            stats = analyze_pending(s, analyzer, ctx.cfg, limit)
        except LLMError as e:
            log.error("IA indisponível: %s (notícias permanecem pendentes)", e)
            stats.errors.append(str(e))
        run.analyzed, run.failed, run.errors = stats.analyzed, stats.failed, stats.errors
        runs.finish(run)
    return stats


@app.command()
def collect(days: Optional[int] = typer.Option(None, help="Janela em dias (padrão: backfill na 1ª vez, depois incremental)")):
    """Coleta e armazena notícias (sem IA)."""
    st = do_collect(_ctx(), days)
    typer.echo(f"encontradas={st.found} novas={st.new} duplicadas={st.duplicates} "
               f"possíveis_duplicatas={st.possible_duplicates} descartadas={st.discarded_total} erros={len(st.errors)}")
    raise typer.Exit(1 if st.errors else 0)


@app.command()
def analyze(limit: Optional[int] = typer.Option(None, help="Máximo de notícias nesta execução")):
    """Analisa notícias pendentes (e falhas com tentativas restantes) com IA."""
    st = do_analyze(_ctx(), limit)
    typer.echo(f"analisadas={st.analyzed} falhas={st.failed}")
    raise typer.Exit(1 if st.errors else 0)


@app.command()
def run(days: Optional[int] = typer.Option(None)):
    """Pipeline completo: coleta e, depois, análise. Falha da IA não afeta o que foi coletado."""
    ctx = _ctx()
    c = do_collect(ctx, days)
    a = do_analyze(ctx)
    typer.echo(f"coleta: encontradas={c.found} novas={c.new} duplicadas={c.duplicates} descartadas={c.discarded_total} "
               f"| análise: analisadas={a.analyzed} falhas={a.failed}")
    raise typer.Exit(1 if (c.errors or a.errors) else 0)


@app.command()
def reprocess(all_: bool = typer.Option(False, "--all", help="Reanalisa também as já analisadas (ex.: prompt novo)"),
              limit: Optional[int] = typer.Option(None)):
    """Zera tentativas das falhas (e, com --all, de tudo) e roda a análise de novo."""
    ctx = _ctx()
    states = ["failed", "done"] if all_ else ["failed"]
    with session_scope(ctx.session_factory) as s:
        res = s.execute(update(News).where(News.analysis_status.in_(states), News.dup_status != "duplicate")
                        .values(analysis_status="pending", analysis_attempts=0))
        typer.echo(f"{res.rowcount} notícias marcadas para reprocessamento")
    st = do_analyze(ctx, limit)
    typer.echo(f"analisadas={st.analyzed} falhas={st.failed}")
    raise typer.Exit(1 if st.errors else 0)


@app.command()
def serve(host: Optional[str] = None, port: Optional[int] = None):
    """Inicia a API e a interface web."""
    import uvicorn
    cfg = load_config()
    setup_logging(cfg.env.log_level, cfg.env.log_format)
    build_context(cfg)  # garante migrations
    uvicorn.run("radar.api.app:create_app", factory=True, host=host or cfg.env.app_host, port=port or cfg.env.app_port)


@sources_app.command("list")
def sources_list():
    """Fontes configuradas e seu estado."""
    ctx = _ctx()
    with session_scope(ctx.session_factory) as s:
        for r in SourceRepository(s).list():
            typer.echo(f"{r.source_id:18} {r.type:8} tier={r.tier} {'ON ' if r.enabled else 'off'} "
                       f"ok={r.fetches_ok} falhas={r.fetches_failed} último={r.last_status or '-'} {r.url[:60]}")


@sources_app.command("report")
def sources_report(sample: Optional[Path] = typer.Option(None, help="CSV de amostra para auditoria manual de precisão")):
    """Relatório de qualidade por fonte, pelos critérios objetivos de config/settings.yaml."""
    from radar.sources_report import build_report, export_audit_sample
    ctx = _ctx()
    with session_scope(ctx.session_factory) as s:
        for r in build_report(s, ctx.cfg):
            fmt = lambda v, f="{:.2f}": "-" if v is None else f.format(v)  # noqa: E731
            typer.echo(f"{r.source_id:18} tier={r.tier} {'ON ' if r.enabled else 'off'} disp={fmt(r.availability)} "
                       f"lag_med_h={fmt(r.median_lag_hours, '{:.1f}')} vistos={r.items_seen} match={r.items_matched} "
                       f"gravados={r.stored} únicos={r.unique} corpo={fmt(r.body_rate)} match/sem={fmt(r.matched_per_week, '{:.1f}')} "
                       + " ".join(f"{k}={v}" for k, v in r.checks.items()))
        if sample:
            typer.echo(f"{export_audit_sample(s, ctx.cfg, sample)} itens exportados para {sample}")


@sources_app.command("discover")
def sources_discover(domain: list[str] = typer.Option(None, "--domain", "-d", help="Domínio(s); padrão: concorrentes + fontes candidatas"),
                     out: Path = typer.Option(Path("reports/phase10/discovery.csv"))):
    """Descobre feeds RSS, sitemaps e páginas de imprensa (somente leitura; respeita robots.txt)."""
    import csv
    from urllib.parse import urlsplit
    from radar.collectors.discovery import discover
    from radar.collectors.http import PoliteHttp
    cfg = load_config()
    setup_logging(cfg.env.log_level, cfg.env.log_format)
    domains = list(domain or [])
    if not domains:
        domains = [d for c in cfg.competitors for d in c.domains]
        domains += [urlsplit(s.url).hostname for s in cfg.sources if s.url and "{year}" not in s.url]
    http = PoliteHttp(cfg.settings.http)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dominio", "acessivel", "robots", "feeds", "sitemaps", "newsroom", "erros"])
        for d in dict.fromkeys(x for x in domains if x):
            r = discover(d, http)
            w.writerow([r.domain, r.reachable, r.robots, " | ".join(r.feeds), " | ".join(r.sitemaps),
                        " | ".join(r.newsroom), " | ".join(r.errors)[:300]])
            typer.echo(f"{r.domain:28} acessível={r.reachable} feeds={len(r.feeds)} sitemaps={len(r.sitemaps)} newsroom={len(r.newsroom)} erros={len(r.errors)}")
    typer.echo(f"relatório: {out}")


if __name__ == "__main__":
    app()
