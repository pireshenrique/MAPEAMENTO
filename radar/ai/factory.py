from __future__ import annotations

from radar.ai.anthropic import AnthropicProvider
from radar.ai.base import LLMError, LLMProvider
from radar.settings import AppConfig


def build_provider(cfg: AppConfig) -> LLMProvider:
    p = cfg.env.ai_provider
    if p == "anthropic":
        return AnthropicProvider(cfg.env.ai_api_key, timeout=cfg.settings.ai.request_timeout_seconds)
    raise LLMError(f"provedor de IA '{p}' ainda não implementado (veja README: como adicionar um provedor)")
