"""Configuração: segredos/ambiente via .env (pydantic-settings) e regras de negócio via YAML."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(BaseSettings):
    """Variáveis de ambiente. Segredos ficam apenas aqui (nunca no YAML/banco/frontend)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    news_api_key: str = ""
    ai_provider: Literal["anthropic", "openai_compat"] = "anthropic"
    ai_api_key: str = ""
    ai_base_url: str = ""
    database_url: str = "sqlite:///data/radar.db"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    config_dir: Path = Path("config")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionConfig(_Strict):
    backfill_days: int = Field(7, ge=1)
    incremental_overlap_hours: int = Field(6, ge=0)
    language: str = "pt"
    page_size: int = Field(50, ge=1, le=100)
    max_pages_per_query: int = Field(1, ge=1)
    request_timeout_seconds: float = 20
    max_retries: int = Field(3, ge=0)
    interval_hours: int = Field(6, ge=1)
    blocked_domains: list[str] = []


class ValidationConfig(_Strict):
    min_title_length: int = 15
    max_age_days: int = 30


class MatchingConfig(_Strict):
    min_confidence: float = Field(0.5, ge=0, le=1)
    ambiguous_min_context_hits: int = Field(2, ge=1)


class DedupConfig(_Strict):
    similarity_threshold: float = Field(90, ge=0, le=100)
    window_days: int = Field(3, ge=0)


class AIConfig(_Strict):
    model: str
    max_tokens: int = 700
    temperature: float = 0.0
    max_analyses_per_run: int = 100
    max_attempts: int = 3
    request_timeout_seconds: float = 60
    min_match_confidence: float = 0.6


class HttpConfig(_Strict):
    user_agent: str = "CompetitiveIntelligenceRadar/0.1 (monitoramento competitivo interno)"
    respect_robots: bool = True
    min_delay_seconds: float = Field(1.0, ge=0)       # intervalo mínimo entre requisições ao mesmo host
    timeout_seconds: float = 20
    robots_ttl_seconds: int = 3600


class SourceQualityConfig(_Strict):
    """Critérios objetivos (Fase 10, seção J) para avaliar uma fonte."""

    min_availability: float = 0.95
    max_median_lag_hours: float = 6
    min_matched_per_week_general: float = 3
    min_matched_per_week_official: float = 1
    min_body_rate: float = 0.7
    sample_size: int = 30


class OpsReportConfig(_Strict):
    """Limiares dos alertas do relatório operacional (docs/relatorio-diario-spec.md, seção 9)."""

    window_days: int = 7                # janela do resumo por fonte e do alerta "sem casamentos"
    stale_hours: float = 24             # sem coleta com sucesso há mais que isso => ausência de coleta
    max_consecutive_failures: int = 3   # falhas seguidas => alerta
    no_match_days: int = 7              # sem nenhum casamento nesse período => alerta (só com histórico suficiente)
    min_body_items: int = 1             # amostra mínima para avaliar body_status de uma fonte


class UIConfig(_Strict):
    page_size: int = 25
    min_chart_sample: int = 10
    timezone: str = "America/Sao_Paulo"


class AppSettings(_Strict):
    collection: CollectionConfig = CollectionConfig()
    validation: ValidationConfig = ValidationConfig()
    matching: MatchingConfig = MatchingConfig()
    dedup: DedupConfig = DedupConfig()
    ai: AIConfig
    http: HttpConfig = HttpConfig()
    source_quality: SourceQualityConfig = SourceQualityConfig()
    ops_report: OpsReportConfig = OpsReportConfig()
    ui: UIConfig = UIConfig()


class CompetitorConfig(_Strict):
    name: str
    aliases: list[str] = []
    ambiguous_aliases: list[str] = []
    domains: list[str] = []
    keywords: list[str] = []
    context_terms: list[str] = []
    exclude_terms: list[str] = []
    priority_categories: list[str] = []
    weight: float = Field(1.0, gt=0)
    active: bool = True

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name vazio")
        return v.strip()

    @field_validator("domains")
    @classmethod
    def _lower_domains(cls, v: list[str]) -> list[str]:
        return [d.strip().lower().removeprefix("www.") for d in v if d.strip()]

    @model_validator(mode="after")
    def _needs_identity(self) -> "CompetitorConfig":
        if not (self.aliases or self.ambiguous_aliases):
            raise ValueError(f"{self.name}: informe ao menos um alias")
        return self


class SourceConfig(_Strict):
    """Uma fonte de notícias. `scope`: per_competitor (busca por empresa) ou feed (lista tudo; match global)."""

    id: str
    type: Literal["newsapi", "rss", "cvm_ipe"]
    url: str | None = None
    enabled: bool = False
    tier: int = Field(2, ge=1, le=3)               # 1 = primária/oficial, 2 = especializada, 3 = geral
    scope: Literal["per_competitor", "feed"] | None = None
    competitor_hint: str | None = None             # fonte dedicada a um concorrente (informativo)
    verified: bool = False                         # URL confirmada pela descoberta (Fase 10.1)
    notes: str = ""
    options: dict = {}                             # opções específicas do tipo (ex.: cnpj, company_name)

    @model_validator(mode="after")
    def _defaults(self) -> "SourceConfig":
        if self.scope is None:
            self.scope = "per_competitor" if self.type == "newsapi" else "feed"
        if self.type in ("rss", "cvm_ipe") and not self.url:
            raise ValueError(f"fonte {self.id}: 'url' é obrigatória para o tipo {self.type}")
        return self


class CategoryConfig(_Strict):
    name: str
    description: str = ""


class CompanyProfile(_Strict):
    name: str
    segments: list[str] = []
    products: list[str] = []
    brands: list[str] = []
    categories: list[str] = []
    technologies: list[str] = []
    markets: list[str] = []
    competitors_by_category: dict[str, list[str]] = {}
    keywords: list[str] = []
    strategic_terms: list[str] = []


class AppConfig(BaseModel):
    """Configuração completa carregada de .env + YAML."""

    env: EnvSettings
    settings: AppSettings
    competitors: list[CompetitorConfig]
    categories: list[CategoryConfig]
    profile: CompanyProfile
    sources: list[SourceConfig] = []

    def competitor(self, name: str) -> CompetitorConfig:
        for c in self.competitors:
            if c.name == name:
                return c
        raise KeyError(name)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: conteúdo YAML deve ser um mapeamento")
    return data


def load_config(config_dir: Path | str | None = None, env: EnvSettings | None = None) -> AppConfig:
    env = env or EnvSettings()
    base = Path(config_dir) if config_dir is not None else env.config_dir

    settings = AppSettings.model_validate(_read_yaml(base / "settings.yaml"))

    comp_raw = _read_yaml(base / "competitors.yaml")
    defaults = comp_raw.get("defaults", {}) or {}
    competitors: list[CompetitorConfig] = []
    for item in comp_raw.get("competitors", []):
        merged = {**defaults, **item}  # valores do concorrente prevalecem sobre os defaults
        competitors.append(CompetitorConfig.model_validate(merged))
    names = [c.name.lower() for c in competitors]
    if len(names) != len(set(names)):
        raise ValueError("competitors.yaml: nomes de concorrentes duplicados")
    if not competitors:
        raise ValueError("competitors.yaml: nenhum concorrente configurado")

    cats = [CategoryConfig.model_validate(c) for c in _read_yaml(base / "categories.yaml").get("categories", [])]
    if not cats:
        raise ValueError("categories.yaml: nenhuma categoria configurada")
    if len({c.name for c in cats}) != len(cats):
        raise ValueError("categories.yaml: categorias duplicadas")

    profile = CompanyProfile.model_validate(_read_yaml(base / "company_profile.yaml").get("company", {}))
    sources: list[SourceConfig] = []
    src_path = base / "sources.yaml"
    if src_path.exists():
        sources = [SourceConfig.model_validate(x) for x in _read_yaml(src_path).get("sources", [])]
        ids = [x.id for x in sources]
        if len(ids) != len(set(ids)):
            raise ValueError("sources.yaml: ids de fontes duplicados")
    return AppConfig(env=env, settings=settings, competitors=competitors, categories=cats, profile=profile,
                     sources=sources)


@lru_cache
def get_config() -> AppConfig:
    return load_config()
