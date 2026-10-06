from __future__ import annotations

import json
import re

from pydantic import ValidationError

from radar.ai.schema import AnalysisResult

OTHER = "Outro"
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


class ParseError(Exception):
    pass


def extract_json(text: str) -> dict:
    """Aceita JSON puro, cercado por markdown ou com texto ao redor."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ParseError("nenhum objeto JSON válido encontrado na resposta")


def normalize_category(value: str, known: list[str]) -> tuple[str, str | None]:
    """Mapeia para categoria conhecida (sem diferenciar caixa); desconhecida -> 'Outro' + valor original."""
    lookup = {k.lower(): k for k in known}
    hit = lookup.get(value.strip().lower())
    if hit:
        return hit, None
    return (OTHER if OTHER in known or not known else OTHER), value.strip()


def parse_analysis(text: str, known_categories: list[str]) -> AnalysisResult:
    data = extract_json(text)
    try:
        result = AnalysisResult.model_validate(data)
    except ValidationError as e:
        raise ParseError("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from e
    category, original = normalize_category(result.category, known_categories)
    if original:
        result.subcategory = result.subcategory or original
    result.category = category
    return result
