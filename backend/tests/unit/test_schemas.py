"""Schema validation tests per spec §14 and §19.1."""

import pytest
from pydantic import ValidationError

from app.schemas.issue import CriticOutput, CriticResult, IssueCandidate, ReviewOutput
from app.schemas.review_plan import ReviewItem, ReviewPlan


class TestReviewPlan:
    def test_valid_plan(self) -> None:
        plan = ReviewPlan(
            items=[
                ReviewItem(
                    key="auth-check",
                    review_type="security",
                    target_paths=["src/auth/"],
                    keywords=["authentication", "authorization"],
                    risk_focus=["CWE-862", "CWE-863"],
                    priority="high",
                    top_k=10,
                )
            ]
        )
        assert len(plan.items) == 1
        assert plan.items[0].key == "auth-check"

    def test_max_10_items(self) -> None:
        items = [
            ReviewItem(
                key=f"item-{i}",
                review_type="security",
                target_paths=[f"src/{i}/"],
                keywords=[f"kw{i}"],
                risk_focus=["CWE-89"],
                priority="medium",
                top_k=10,
            )
            for i in range(11)
        ]
        with pytest.raises(ValidationError):
            ReviewPlan(items=items)

    def test_top_k_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ReviewItem(
                key="x", review_type="bug", target_paths=["src/"],
                keywords=["k"], risk_focus=["r"], priority="low", top_k=0,
            )
        with pytest.raises(ValidationError):
            ReviewItem(
                key="x", review_type="bug", target_paths=["src/"],
                keywords=["k"], risk_focus=["r"], priority="low", top_k=31,
            )


class TestIssueCandidate:
    def test_valid_security_issue(self) -> None:
        issue = IssueCandidate(
            relative_path="src/Foo.java",
            start_line=10,
            end_line=12,
            evidence="String sql = \"SELECT * FROM users WHERE id = '\" + uid + \"'\";",
            source_chunk_ids=[1],
            category="security",
            issue_type="SQL Injection",
            risk_level="High",
            rule_id="JAVA-SQL-001",
            cwe_id="CWE-89",
            title="JDBC SQL Injection",
            description="User input concatenated into SQL.",
            reason="No parameter binding.",
            suggestion="Use PreparedStatement.",
            confidence=0.95,
        )
        assert issue.cwe_id == "CWE-89"
        assert issue.risk_level == "High"

    def test_security_requires_cwe(self) -> None:
        with pytest.raises(ValidationError):
            IssueCandidate(
                relative_path="src/Foo.java",
                start_line=10,
                end_line=12,
                evidence="x",
                source_chunk_ids=[1],
                category="security",
                issue_type="X",
                risk_level="High",
                rule_id="R-1",
                cwe_id=None,
                title="T",
                description="D",
                reason="R",
                suggestion="S",
                confidence=0.8,
            )

    def test_non_security_no_cwe_ok(self) -> None:
        issue = IssueCandidate(
            relative_path="src/Foo.java",
            start_line=10,
            end_line=12,
            evidence="x",
            source_chunk_ids=[1],
            category="bug",
            issue_type="NullPointer",
            risk_level="Medium",
            rule_id="JAVA-NPE-001",
            cwe_id=None,
            title="Potential NPE",
            description="Null may be dereferenced.",
            reason="No null check.",
            suggestion="Add null guard.",
            confidence=0.7,
        )
        assert issue.cwe_id is None

    def test_end_line_before_start_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IssueCandidate(
                relative_path="src/Foo.java",
                start_line=10,
                end_line=5,
                evidence="x",
                source_chunk_ids=[1],
                category="bug",
                issue_type="X",
                risk_level="Low",
                rule_id="R-1",
                title="T",
                description="D",
                reason="R",
                suggestion="S",
                confidence=0.5,
            )

    def test_empty_evidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IssueCandidate(
                relative_path="src/Foo.java",
                start_line=10,
                end_line=12,
                evidence="",
                source_chunk_ids=[1],
                category="bug",
                issue_type="X",
                risk_level="Low",
                rule_id="R-1",
                title="T",
                description="D",
                reason="R",
                suggestion="S",
                confidence=0.5,
            )

    def test_empty_source_chunks_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IssueCandidate(
                relative_path="src/Foo.java",
                start_line=10,
                end_line=12,
                evidence="x",
                source_chunk_ids=[],
                category="bug",
                issue_type="X",
                risk_level="Low",
                rule_id="R-1",
                title="T",
                description="D",
                reason="R",
                suggestion="S",
                confidence=0.5,
            )

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            IssueCandidate(
                relative_path="src/Foo.java",
                start_line=10,
                end_line=12,
                evidence="x",
                source_chunk_ids=[1],
                category="bug",
                issue_type="X",
                risk_level="Low",
                rule_id="R-1",
                title="T",
                description="D",
                reason="R",
                suggestion="S",
                confidence=1.5,
            )


class TestCriticSchemas:
    def test_critic_result(self) -> None:
        cr = CriticResult(
            fingerprint="abc123",
            decision="pass",
            reason="Evidence is solid.",
        )
        assert cr.decision == "pass"
        assert cr.adjusted_risk_level is None

    def test_critic_result_fail_with_adjustment(self) -> None:
        cr = CriticResult(
            fingerprint="abc123",
            decision="fail",
            adjusted_risk_level="Low",
            reason="False positive — the code is safe.",
        )
        assert cr.adjusted_risk_level == "Low"

    def test_critic_output(self) -> None:
        co = CriticOutput(
            decisions=[
                CriticResult(fingerprint="a", decision="pass", reason="ok"),
                CriticResult(fingerprint="b", decision="fail", reason="fp"),
            ]
        )
        assert len(co.decisions) == 2


class TestReviewOutput:
    def test_review_output(self) -> None:
        ro = ReviewOutput(issues=[])
        assert ro.issues == []

    def test_review_output_with_issues(self) -> None:
        ro = ReviewOutput(
            issues=[
                IssueCandidate(
                    relative_path="src/a.py",
                    start_line=1,
                    end_line=2,
                    evidence="bad code",
                    source_chunk_ids=[1],
                    category="bug",
                    issue_type="test",
                    risk_level="Low",
                    rule_id="T-1",
                    title="T",
                    description="D",
                    reason="R",
                    suggestion="S",
                    confidence=0.5,
                )
            ]
        )
        assert len(ro.issues) == 1
