"""Unified issue and critic schemas per spec §14.2 and §14.3.

IssueCandidate is the canonical output of the Review agent.  CriticResult
is the output of the Critic agent.  Both are validated by Pydantic.

Fields have aliases for common LLM naming variations so DeepSeek's
output passes validation even when field names differ from the spec.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _coerce_to_int_list(value: Any) -> list[int]:
    """Accept a single int and wrap it, or pass a list through."""
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        return [int(v) for v in value]
    raise ValueError(f"Expected int or list, got {type(value).__name__}")


class IssueCandidate(BaseModel):
    """One issue proposed by the Review agent — §14.2."""

    model_config = {"populate_by_name": True}

    relative_path: str = ""
    start_line: int = Field(default=1, gt=0, alias="line_start", validation_alias="start_line")
    end_line: int = Field(default=1, gt=0, alias="line_end", validation_alias="end_line")
    evidence: str = Field(default="")
    source_chunk_ids: list[int] = Field(default_factory=list)

    category: Literal["security", "bug", "performance", "maintainability"] = "bug"
    issue_type: str = Field(default="", alias="type", validation_alias="issue_type")
    risk_level: Literal["High", "Medium", "Low"] = Field(
        default="Medium",
        alias="severity",
        validation_alias="risk_level",
    )
    rule_id: str = Field(default="", alias="rule", validation_alias="rule_id")
    cwe_id: str | None = None

    title: str = Field(default="", max_length=256)
    description: str = ""
    reason: str = Field(default="", alias="explanation", validation_alias="reason")
    suggestion: str = Field(default="", alias="fix", validation_alias="suggestion")
    fixed_example: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)

    # Set by deterministic nodes after Review agent runs.
    evidence_status: str | None = None
    fingerprint: str | None = None
    critic_decision: str | None = None
    critic_reason: str | None = None
    needs_human_review: bool = False
    review_round: int = 1

    @field_validator("source_chunk_ids", mode="before")
    @classmethod
    def _ids_coercion(cls, v: Any) -> list[int]:
        return _coerce_to_int_list(v)

    @model_validator(mode="after")
    def validate_issue(self) -> "IssueCandidate":
        if self.category == "security" and not self.cwe_id:
            raise ValueError("Security issue requires cwe_id")
        if self.end_line < self.start_line:
            self.end_line = self.start_line
        return self


class ReviewOutput(BaseModel):
    """Wrapper returned by the Review agent node."""

    issues: list[IssueCandidate]


class CriticResult(BaseModel):
    """One Critic decision per §14.3."""

    fingerprint: str
    decision: Literal["pass", "fail", "uncertain"]
    adjusted_risk_level: Literal["High", "Medium", "Low"] | None = None
    reason: str


class CriticOutput(BaseModel):
    """Wrapper returned by the Critic agent node."""

    decisions: list[CriticResult]
