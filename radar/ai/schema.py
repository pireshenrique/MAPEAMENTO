from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.domain.models import Impact, Sentiment


class AnalysisResult(BaseModel):
    """Contrato JSON validado da resposta do LLM."""

    model_config = ConfigDict(extra="ignore")

    is_relevant: bool = False
    relevance_score: int = Field(ge=1, le=5)
    competitive_impact: Impact = Impact.NEUTRAL
    sentiment: Sentiment = Sentiment.NEUTRAL
    category: str = Field(min_length=1, max_length=80)
    subcategory: str | None = Field(default=None, max_length=120)
    summary: str = Field(min_length=10, max_length=1200)
    key_points: list[str] = Field(default_factory=list, max_length=6)
    strategic_reason: str = Field(min_length=5, max_length=1200)

    @field_validator("competitive_impact", "sentiment", mode="before")
    @classmethod
    def _lower(cls, v):  # noqa: ANN001
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _score(cls, v):  # noqa: ANN001
        if isinstance(v, str) and v.strip().isdigit():
            return int(v)
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v

    @field_validator("key_points", mode="before")
    @classmethod
    def _points(cls, v):  # noqa: ANN001
        if isinstance(v, str):
            return [v]
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else v

    @model_validator(mode="after")
    def _consistent(self) -> "AnalysisResult":
        self.is_relevant = self.relevance_score >= 3  # a nota manda; evita contradição
        return self
