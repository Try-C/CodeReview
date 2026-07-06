"""LLM layer unit tests — usage, client, and structured output per §12.5 and §19.1."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.llm.client import FakeLLMClient
from app.llm.structured import StructuredLLM, StructuredOutputError
from app.llm.usage import (
    LLMCallResult,
    PricingSnapshot,
    calculate_estimated_cost,
)
from app.services.evidence_service import EvidenceService

# ── Usage / cost tests ──────────────────────────────────────────────────────


class TestPricingSnapshot:
    def test_snapshot_immutable_in_concept(self) -> None:
        ps = PricingSnapshot(
            model="deepseek-v4",
            input_price_per_million=Decimal("0.14"),
            output_price_per_million=Decimal("0.28"),
            currency="USD",
            version="2026-07",
        )
        assert ps.model == "deepseek-v4"
        assert ps.input_price_per_million == Decimal("0.14")
        assert ps.currency == "USD"


class TestCalculateEstimatedCost:
    def test_basic_calculation(self) -> None:
        pricing = PricingSnapshot(
            model="test",
            input_price_per_million=Decimal("0.14"),
            output_price_per_million=Decimal("0.28"),
            version="v1",
        )
        cost = calculate_estimated_cost(1000, 2000, pricing)
        # (1000 * 0.14 + 2000 * 0.28) / 1e6 = 700 / 1e6 = 0.000700
        assert cost == Decimal("0.000700")

    def test_zero_tokens_zero_cost(self) -> None:
        pricing = PricingSnapshot(
            model="test",
            input_price_per_million=Decimal("1.0"),
            output_price_per_million=Decimal("1.0"),
            version="v1",
        )
        cost = calculate_estimated_cost(0, 0, pricing)
        assert cost == Decimal("0.000000")

    def test_decimal_rounding(self) -> None:
        pricing = PricingSnapshot(
            model="test",
            input_price_per_million=Decimal("0.001"),
            output_price_per_million=Decimal("0.001"),
            version="v1",
        )
        cost = calculate_estimated_cost(1, 1, pricing)
        assert cost == Decimal("0.000000")  # 0.002e-6 rounds to 0.000000


class TestLLMCallResult:
    def test_available_cost(self) -> None:
        pricing = PricingSnapshot(
            model="deepseek-v4",
            input_price_per_million=Decimal("0.14"),
            output_price_per_million=Decimal("0.28"),
            version="v1",
        )
        result = LLMCallResult(
            content='{"key":"value"}',
            model="deepseek-v4",
            input_tokens=100,
            output_tokens=200,
            cost_status="available",
            estimated_cost=Decimal("0.000070"),
            latency_ms=500,
            pricing=pricing,
        )
        assert result.cost_status == "available"
        assert result.estimated_cost == Decimal("0.000070")

    def test_unavailable_cost(self) -> None:
        pricing = PricingSnapshot(
            model="deepseek-v4",
            input_price_per_million=Decimal("0"),
            output_price_per_million=Decimal("0"),
            version="unconfigured",
        )
        result = LLMCallResult(
            content="{}",
            model="deepseek-v4",
            input_tokens=100,
            output_tokens=200,
            cost_status="unavailable",
            estimated_cost=None,
            latency_ms=500,
            pricing=pricing,
        )
        assert result.cost_status == "unavailable"
        assert result.estimated_cost is None


# ── FakeLLMClient tests ─────────────────────────────────────────────────────


class TestFakeLLMClient:
    @pytest.mark.asyncio
    async def test_returns_configured_response(self) -> None:
        fake = FakeLLMClient(response_text='{"hello": "world"}')
        result = await fake.chat([{"role": "user", "content": "hi"}])
        assert result.content == '{"hello": "world"}'
        assert result.model == "fake"
        assert result.cost_status == "unavailable"

    @pytest.mark.asyncio
    async def test_custom_token_counts(self) -> None:
        fake = FakeLLMClient(
            response_text="ok",
            input_tokens=50,
            output_tokens=25,
        )
        result = await fake.chat([])
        assert result.input_tokens == 50
        assert result.output_tokens == 25


# ── StructuredLLM tests ─────────────────────────────────────────────────────


class _TestModel(BaseModel):
    name: str
    value: int


class TestStructuredLLM:
    @pytest.mark.asyncio
    async def test_parses_valid_json(self) -> None:
        fake = FakeLLMClient(response_text='{"name": "test", "value": 42}')
        sllm = StructuredLLM(fake)
        model, result = await sllm.invoke([], _TestModel)
        assert model.name == "test"
        assert model.value == 42
        assert result.content == '{"name": "test", "value": 42}'

    @pytest.mark.asyncio
    async def test_extracts_json_from_code_fence(self) -> None:
        fake = FakeLLMClient(
            response_text='Here is the result:\n```json\n{"name": "x", "value": 1}\n```\nDone.'
        )
        sllm = StructuredLLM(fake)
        model, _ = await sllm.invoke([], _TestModel)
        assert model.name == "x"

    @pytest.mark.asyncio
    async def test_repair_on_invalid_json(self) -> None:
        """First response invalid → repair attempt succeeds."""
        responses = [
            '{"name": "x", value: 1}',  # missing quotes around 'value'
            '{"name": "x", "value": 1}',  # corrected
        ]
        call_index = [0]

        class MultiResponseFake(FakeLLMClient):
            async def chat(self, messages, **kwargs):
                idx = call_index[0]
                call_index[0] += 1
                return await FakeLLMClient(
                    response_text=responses[min(idx, len(responses) - 1)]
                ).chat(messages, **kwargs)

        sllm = StructuredLLM(MultiResponseFake(response_text=""))
        model, _ = await sllm.invoke([], _TestModel)
        assert model.value == 1
        assert call_index[0] == 2  # two calls made

    @pytest.mark.asyncio
    async def test_raises_after_repair_fails(self) -> None:
        """Both attempts fail → StructuredOutputError."""
        fake = FakeLLMClient(response_text="not json at all")
        sllm = StructuredLLM(fake)
        with pytest.raises(StructuredOutputError):
            await sllm.invoke([], _TestModel)

    def test_extract_json_plain_object(self) -> None:
        text = 'some prefix {"a": 1, "b": 2} suffix'
        result = StructuredLLM.extract_json(text)
        assert result == '{"a": 1, "b": 2}'

    def test_extract_json_array(self) -> None:
        text = "prefix [1, 2, 3] suffix"
        result = StructuredLLM.extract_json(text)
        assert result == "[1, 2, 3]"

    def test_extract_json_only_braces(self) -> None:
        text = '{"key": "value"}'
        result = StructuredLLM.extract_json(text)
        assert result == '{"key": "value"}'


# ── EvidenceService tests (§19.1) ───────────────────────────────────────────


class TestEvidenceService:
    @pytest.fixture
    def service(self) -> EvidenceService:
        return EvidenceService()

    @pytest.fixture
    def tmp_project(self) -> str:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            (src / "Test.java").write_text(
                "package demo;\n"
                "public class Test {\n"
                '    String sql = "SELECT * FROM users WHERE id = \'" + uid + "\'";\n'
                "}\n"
            )
            yield td

    @pytest.mark.asyncio
    async def test_all_checks_pass(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/Test.java",
            "start_line": 3,
            "end_line": 3,
            "evidence": 'String sql = "SELECT * FROM users WHERE id = \'" + uid + "\'";',
            "source_chunk_ids": [1],
            "rule_id": "JAVA-SQL-001",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "passed"

    @pytest.mark.asyncio
    async def test_bad_path_fails(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "../outside.txt",
            "start_line": 1,
            "end_line": 1,
            "evidence": "x",
            "source_chunk_ids": [1],
            "rule_id": "X-1",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "failed"
        assert result["evidence_checks"]["path"] is False

    @pytest.mark.asyncio
    async def test_line_out_of_range_fails(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/Test.java",
            "start_line": 99,
            "end_line": 100,
            "evidence": "x",
            "source_chunk_ids": [1],
            "rule_id": "X-1",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "failed"
        assert result["evidence_checks"]["lines"] is False

    @pytest.mark.asyncio
    async def test_empty_evidence_fails(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/Test.java",
            "start_line": 3,
            "end_line": 3,
            "evidence": "",
            "source_chunk_ids": [1],
            "rule_id": "X-1",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "failed"
        assert result["evidence_checks"]["evidence"] is False

    @pytest.mark.asyncio
    async def test_empty_chunks_fails(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/Test.java",
            "start_line": 3,
            "end_line": 3,
            "evidence": "x",
            "source_chunk_ids": [],
            "rule_id": "X-1",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "failed"
        assert result["evidence_checks"]["chunks"] is False

    @pytest.mark.asyncio
    async def test_fingerprint_is_stable(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/Test.java",
            "start_line": 3,
            "end_line": 3,
            "evidence": "same evidence",
            "source_chunk_ids": [1],
            "rule_id": "R-001",
        }
        r1 = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        r2 = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert r1["fingerprint"] == r2["fingerprint"]

    @pytest.mark.asyncio
    async def test_nonexistent_file_fails(self, service, tmp_project) -> None:
        issue = {
            "relative_path": "src/DoesNotExist.java",
            "start_line": 1,
            "end_line": 1,
            "evidence": "x",
            "source_chunk_ids": [1],
            "rule_id": "X-1",
        }
        result = await service.verify_one(
            issue=issue,
            project_id=1,
            project_root=tmp_project,
        )
        assert result["evidence_status"] == "failed"
