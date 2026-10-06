"""Contrato de provedor de LLM. Trocar de fornecedor = nova classe + AI_PROVIDER."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Falha do provedor (rede, autenticação, cota, resposta vazia)."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str:
        """Devolve o texto bruto da resposta. Levanta LLMError em falha."""
        ...
