"""Monta o contexto da aplicação: engine, migrations e sincronização da configuração."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from radar.db.engine import make_engine, make_session_factory, session_scope
from radar.db.migrate import upgrade_to_head
from radar.db.repositories import CategoryRepository, CompetitorRepository, SourceRepository
from radar.settings import AppConfig


@dataclass
class Context:
    cfg: AppConfig
    engine: Engine
    session_factory: sessionmaker[Session]


def build_context(cfg: AppConfig) -> Context:
    url = cfg.env.database_url
    upgrade_to_head(url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    with session_scope(factory) as s:  # YAML é a fonte de verdade de concorrentes e categorias
        CompetitorRepository(s).sync(cfg.competitors)
        CategoryRepository(s).sync(cfg.categories)
        SourceRepository(s).sync(cfg.sources)
    return Context(cfg, engine, factory)
