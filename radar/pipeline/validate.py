"""Etapa VALIDATE: devolve o motivo de rejeição (ou None se válido). Nada é descartado em silêncio."""
from __future__ import annotations

from datetime import datetime, timedelta

from radar.domain.models import NormalizedArticle
from radar.settings import CollectionConfig, ValidationConfig

_REMOVED = {"[removed]", "removed"}


def validate(n: NormalizedArticle, now: datetime, vcfg: ValidationConfig, ccfg: CollectionConfig) -> str | None:
    if not n.title or n.title.lower() in _REMOVED:
        return "sem_titulo_ou_removido"
    if len(n.title) < vcfg.min_title_length:
        return "titulo_curto"
    if not n.url.lower().startswith(("http://", "https://")) or not n.source_domain:
        return "url_invalida"
    if n.published_at is None:
        return "sem_data"
    if n.published_at > now + timedelta(days=1):
        return "data_futura"
    if n.published_at < now - timedelta(days=vcfg.max_age_days):
        return "muito_antiga"
    blocked = {d.lower().removeprefix("www.") for d in ccfg.blocked_domains}
    if any(n.source_domain == d or n.source_domain.endswith("." + d) for d in blocked):
        return "dominio_bloqueado"
    return None
