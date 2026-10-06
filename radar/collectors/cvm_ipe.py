"""CVM / IPE (dados abertos): fatos relevantes e comunicados de companhias abertas (ex.: Dexco).

O arquivo anual é um ZIP com CSV (latin-1, separador ';'). O URL em sources.yaml usa o marcador {year}.
Opções (sources.yaml -> options): company_name_contains (obrigatória), include_categories (opcional)."""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone

from radar.collectors.base import CollectorError
from radar.collectors.http import PoliteHttp
from radar.domain.models import BodyStatus, RawArticle
from radar.settings import SourceConfig

log = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value[:19] if "%S" in fmt else value[:16] if "%H" in fmt else value[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class CvmIpeCollector:
    name = "cvm_ipe"
    scope = "feed"

    def __init__(self, cfg: SourceConfig, http: PoliteHttp):
        self.cfg, self.http, self.source_id = cfg, http, cfg.id
        self.company = (cfg.options.get("company_name_contains") or "").strip().upper()
        if not self.company:
            raise CollectorError(f"fonte {cfg.id}: options.company_name_contains é obrigatório", code="badConfig")
        self.categories = {c.lower() for c in cfg.options.get("include_categories", [])}
        self.etag = self.last_modified = None
        self.last_status, self.not_modified = "never", False

    def load_state(self, etag, last_modified) -> None:  # noqa: ANN001
        self.etag, self.last_modified = etag, last_modified

    def fetch(self, competitor, since: datetime, until: datetime | None = None) -> list[RawArticle]:  # noqa: ANN001
        until = until or datetime.now(timezone.utc)
        out: list[RawArticle] = []
        years = sorted({since.year, until.year})
        for year in years:
            current = year == until.year
            res = self.http.get(self.cfg.url.format(year=year), self.etag if current else None,
                                self.last_modified if current else None)
            if current:
                self.etag, self.last_modified, self.not_modified = res.etag, res.last_modified, res.not_modified
                self.last_status = "not_modified" if res.not_modified else "ok"
            if res.not_modified:
                continue
            out.extend(self._parse(res.content, since))
        log.info("cvm_ipe %s: %d documentos", self.cfg.id, len(out))
        return out

    def _parse(self, blob: bytes, since: datetime) -> list[RawArticle]:
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                text = z.read(name).decode("latin-1")
        except (zipfile.BadZipFile, StopIteration) as e:
            raise CollectorError(f"arquivo IPE inválido: {type(e).__name__}", code="invalidIpe") from e
        rows = csv.DictReader(io.StringIO(text), delimiter=";")
        out: list[RawArticle] = []
        for raw in rows:
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if self.company not in r.get("nome_companhia", "").upper():
                continue
            cat = r.get("categoria", "")
            if self.categories and cat.lower() not in self.categories:
                continue
            published = _parse_date(r.get("data_entrega", "")) or _parse_date(r.get("data_referencia", ""))
            if published and published < since:
                continue
            link = r.get("link_download") or None
            subject = r.get("assunto", "")
            out.append(RawArticle(
                source_collector=self.name, source_id=self.cfg.id, source_type="cvm_ipe",
                external_id=r.get("protocolo_entrega") or link,
                title=f"{r.get('nome_companhia', '')}: {cat}" + (f" - {subject}" if subject else ""),
                description=" · ".join(x for x in (r.get("tipo"), r.get("especie")) if x) or None,
                url=link, published_at=published, source_name="CVM (dados abertos)",
                body_status=BodyStatus.NONE.value, tags=[x for x in (cat, r.get("tipo")) if x]))
        return out
