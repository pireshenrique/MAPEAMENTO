from __future__ import annotations

import logging
from dataclasses import dataclass

from radar.ai.base import LLMProvider
from radar.ai.parser import ParseError, parse_analysis
from radar.ai.prompts import PROMPT_VERSION, ArticleInput, build_repair, build_system, build_user
from radar.ai.schema import AnalysisResult
from radar.settings import AIConfig, CompanyProfile

log = logging.getLogger(__name__)


class AnalysisError(Exception):
    """JSON continuou inválido após recuperação. Carrega a resposta bruta para auditoria."""

    def __init__(self, message: str, raw_response: str):
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class AnalysisOutcome:
    result: AnalysisResult
    raw_response: str
    model: str
    prompt_version: str = PROMPT_VERSION


class Analyzer:
    """Provider + prompt + parser. Uma chamada normal; no máximo uma de recuperação se o JSON for inválido.
    Erros do provedor (LLMError) propagam para quem chama decidir (marcar failed e seguir)."""

    def __init__(self, provider: LLMProvider, cfg: AIConfig, profile: CompanyProfile, categories: list[str]):
        self.provider, self.cfg, self.categories = provider, cfg, categories
        self._system = build_system(profile, categories)

    def analyze(self, article: ArticleInput) -> AnalysisOutcome:
        kw = dict(model=self.cfg.model, max_tokens=self.cfg.max_tokens, temperature=self.cfg.temperature)
        raw = self.provider.complete(self._system, build_user(article), **kw)
        try:
            result = parse_analysis(raw, self.categories)
        except ParseError as first:
            log.warning("JSON inválido da IA (%s); tentando recuperação", first)
            raw2 = self.provider.complete(self._system, build_user(article) + "\n\n" + build_repair(raw, str(first)), **kw)
            try:
                result = parse_analysis(raw2, self.categories)
                raw = raw2
            except ParseError as second:
                raise AnalysisError(f"JSON inválido após recuperação: {second}", raw2) from second
        return AnalysisOutcome(result, raw, self.cfg.model)
