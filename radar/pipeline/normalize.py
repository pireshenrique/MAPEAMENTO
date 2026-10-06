"""Etapa NORMALIZE: limpa e padroniza campos. Não descarta nada (isso é a etapa VALIDATE)."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from radar.domain.models import NormalizedArticle, RawArticle
from radar.pipeline.text import fold

_TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "utm", "cmpid", "ocid", "spm"}
_TAGS = re.compile(r"<[^>]+>")
_TRUNC = re.compile(r"\s*\[\+\d+ chars\]\s*$")
_WS = re.compile(r"\s+")
_SEP = re.compile(r"\s+[-–—|]\s+")


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = _TRUNC.sub("", html.unescape(_TAGS.sub(" ", value)))
    text = _WS.sub(" ", text).strip()
    return text or None


def domain_of(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower().removeprefix("www.") if host else None


def normalize_url(url: str) -> str:
    """Esquema https, host sem www, sem fragmento/trackers, query ordenada, sem barra final."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not p.hostname:
        return url.strip()
    query = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in _TRACKING)
    host = p.hostname.lower().removeprefix("www.")
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    path = re.sub(r"/{2,}", "/", p.path).rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))


def normalize_title(title: str, source_name: str | None = None, source_domain: str | None = None) -> str:
    """Sem acentos/pontuação/caixa; remove sufixo ' - Nome do Portal' quando identifica a fonte."""
    parts = _SEP.split(title)
    if len(parts) > 1:
        suffix = fold(parts[-1])
        suffix_tokens = re.sub(r"[^a-z0-9]", "", suffix)
        candidates = {re.sub(r"[^a-z0-9]", "", fold(source_name or ""))}
        if source_domain:
            candidates.add(re.sub(r"[^a-z0-9]", "", source_domain.split(".")[0]))
        candidates.discard("")
        if suffix_tokens and any(suffix_tokens == c or suffix_tokens in c or c in suffix_tokens for c in candidates):
            title = " - ".join(parts[:-1])
    text = re.sub(r"[^a-z0-9\s]", " ", fold(title))
    return _WS.sub(" ", text).strip()


def _content_hash(title_norm: str, description: str | None) -> str:
    base = title_norm + "|" + re.sub(r"[^a-z0-9]", "", fold(description or ""))[:300]
    return hashlib.sha256(base.encode()).hexdigest()


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def normalize(raw: RawArticle, collected_at: datetime) -> NormalizedArticle:
    title = clean_text(raw.title) or ""
    url = (raw.url or "").strip()
    domain = domain_of(url) if url else None
    source_name = clean_text(raw.source_name)
    description = clean_text(raw.description)
    title_norm = normalize_title(title, source_name, domain) if title else ""
    return NormalizedArticle(
        source_collector=raw.source_collector,
        external_id=(raw.external_id or None),
        title=title, description=description, url=url,
        url_normalized=normalize_url(url) if url else "",
        title_normalized=title_norm,
        content_hash=_content_hash(title_norm, description),
        source_name=source_name, source_domain=domain,
        author=clean_text(raw.author), published_at=_utc(raw.published_at),
        image_url=(raw.image_url or None), raw_content=clean_text(raw.content),
        collected_at=collected_at,
    )
