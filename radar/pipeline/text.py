from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """minúsculas, sem acentos."""
    return strip_accents(text).lower()


def has_term(text: str, term: str, *, case_sensitive: bool = False) -> bool:
    """Busca o termo como palavra/expressão inteira (sem acento)."""
    t, w = strip_accents(text), strip_accents(term)
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t, flags) is not None
