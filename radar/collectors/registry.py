"""Registro de coletores a partir de config/sources.yaml. Para adicionar um tipo: implemente SourceCollector
e inclua-o em _BUILDERS."""
from __future__ import annotations

import logging

from radar.collectors.base import SourceCollector
from radar.collectors.cvm_ipe import CvmIpeCollector
from radar.collectors.http import PoliteHttp
from radar.collectors.newsapi import NewsApiCollector
from radar.collectors.rss import RSSCollector
from radar.settings import AppConfig, SourceConfig

log = logging.getLogger(__name__)


def build_collectors(cfg: AppConfig, http: PoliteHttp | None = None) -> list[SourceCollector]:
    http = http or PoliteHttp(cfg.settings.http)
    out: list[SourceCollector] = []
    for src in cfg.sources:
        if not src.enabled:
            continue
        c = _build(src, cfg, http)
        if c is not None:
            out.append(c)
    if not cfg.sources and cfg.env.news_api_key:  # configuração antiga, sem sources.yaml
        out.append(NewsApiCollector(cfg.env.news_api_key, cfg.settings.collection))
    return out


def _build(src: SourceConfig, cfg: AppConfig, http: PoliteHttp) -> SourceCollector | None:
    if src.type == "newsapi":
        if not cfg.env.news_api_key:
            log.warning("fonte %s habilitada, mas NEWS_API_KEY não está definida; ignorada", src.id)
            return None
        return NewsApiCollector(cfg.env.news_api_key, cfg.settings.collection)
    if src.type == "rss":
        return RSSCollector(src, http)
    if src.type == "cvm_ipe":
        return CvmIpeCollector(src, http)
    return None
