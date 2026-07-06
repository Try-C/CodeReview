"""Unified issue and critic schemas per spec §14.2 and §14.3.

IssueCandidate is the canonical output of the Review agent.  CriticResult
is the output of the Critic agent.  Both are validated by Pydantic.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IssueCandidate(BaseModel):
    """One issue proposed by the Review agent — §14.2."""

    relative_path: str
    start_line: int = Field(gt=0)
    end_line: int = Field(gt=0)
    evidence: str = Field(min_length=1)
    source_chunk_ids: list[int] = Field(min_length=1)

    category: Literal[
        "security",
        "bug",
        "performance",
        "maintainability",
    ]
    issue_type: str
    risk_level: Literal["High", "Medium", "Low"]
    rule_id: str = Field(min_length=1)
    cwe_id: str | None = None

    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    fixed_example: str | None = None
    confidence: float = Field(ge=0, le=1)

    # Set by deterministic nodes after Review agent runs.
    evidence_status: str | None = None
    fingerprint: str | None = None
    critic_decision: str | None = None
    critic_reason: str | None = None
    needs_human_review: bool = False
    review_round: int = 1

    @model_validator(mode="after")
    def validate_issue(self) -> "IssueCandidate":
        if self.category == "security" and not self.cwe_id:
            raise ValueError("Security issue requires cwe_id")
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
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
