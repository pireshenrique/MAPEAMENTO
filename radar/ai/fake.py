"""Provedor falso para testes/desenvolvimento: não consome créditos."""
from __future__ import annotations

from typing import Callable, Sequence

from radar.ai.base import LLMError


class FakeLLMProvider:
    name = "fake"

    def __init__(self, responses: Sequence[str | Exception] | Callable[[str, str], str] = ()):
        self._responses = responses
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str:
        self.calls.append({"system": system, "user": user, "model": model})
        if callable(self._responses):
            return self._responses(system, user)
        if not self._responses:
            raise LLMError("FakeLLMProvider sem respostas configuradas")
        item = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
