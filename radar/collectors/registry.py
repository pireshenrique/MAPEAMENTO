"""Registro de coletores. Para adicionar uma fonte: implemente SourceCollector e registre aqui."""
from __future__ import annotations

from radar.collectors.base import SourceCollector
from radar.collectors.newsapi import NewsApiCollector
from radar.settings import AppConfig


def build_collectors(cfg: AppConfig) -> list[SourceCollector]:
    collectors: list[SourceCollector] = []
    if cfg.env.news_api_key:
        collectors.append(NewsApiCollector(cfg.env.news_api_key, cfg.settings.collection))
    return collectors
