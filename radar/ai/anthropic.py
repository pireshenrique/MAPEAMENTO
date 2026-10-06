from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from radar.ai.base import LLMError

log = logging.getLogger(__name__)
URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, *, timeout: float = 60, max_retries: int = 2,
                 client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise LLMError("AI_API_KEY não configurada")
        self._key, self._retries, self._sleep = api_key, max_retries, sleep
        self._client = client or httpx.Client(timeout=timeout)

    def complete(self, system: str, user: str, *, model: str, max_tokens: int, temperature: float = 0.0) -> str:
        body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        attempt = 0
        while True:
            try:
                return self._once(body, headers)
            except LLMError as e:
                if not e.retryable or attempt >= self._retries:
                    raise
                log.warning("anthropic: erro retentável (%s); nova tentativa em %ss", e, 2 ** attempt)
                self._sleep(2 ** attempt)
                attempt += 1

    def _once(self, body: dict, headers: dict) -> str:
        try:
            resp = self._client.post(URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"falha de rede: {type(e).__name__}", retryable=True) from e
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
            raise LLMError(f"Anthropic HTTP {resp.status_code}: {msg}",
                           retryable=resp.status_code in (408, 429, 500, 502, 503, 504, 529))
        try:
            blocks = resp.json()["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, KeyError, TypeError) as e:
            raise LLMError("resposta da Anthropic em formato inesperado") from e
        if not text.strip():
            raise LLMError("resposta vazia da Anthropic")
        return text
