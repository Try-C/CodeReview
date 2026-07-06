"""Retry-safe persistence for graph-node execution and model usage."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graph.state import CodeReviewState
from app.models.node_run import NodeRun


class NodeRunService:
    """Upsert one stable trace row per logical graph-node invocation."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(
        self,
        node_name: str,
        state: CodeReviewState,
        output: dict[str, Any] | None,
        error: Exception | None,
    ) -> None:
        run_key = self._run_key(node_name, state)
        usage = output.get("last_usage", {}) if output else {}
        now = datetime.now(UTC)

        async with self._sessions() as session:
            row = await session.scalar(
                select(NodeRun)
                .where(NodeRun.task_id == state.task_id, NodeRun.run_key == run_key)
                .with_for_update()
            )
            if row is None:
                row = NodeRun(
                    task_id=state.task_id,
                    run_key=run_key,
                    node_name=node_name,
                    status="running",
                    attempt=1,
                    started_at=now,
                )
                session.add(row)
            elif row.status != "success":
                row.attempt += 1

            row.status = "failed" if error else "success"
            row.finished_at = now
            row.input_summary = self._state_summary(state)
            row.output_summary = self._output_summary(output)
            row.error_code = type(error).__name__ if error else None
            row.error_message = "Graph node failed" if error else None
            self._apply_usage(row, usage)
            await session.commit()

    @staticmethod
    def _run_key(node_name: str, state: CodeReviewState) -> str:
        identity = ":".join(
            (
                node_name,
                str(state.current_review_index),
                str(state.review_round),
                str(state.retrieval_retry_count),
                str(state.llm_call_count),
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _state_summary(state: CodeReviewState) -> dict[str, Any]:
        item = state.current_review_item or {}
        return {
            "current_review_index": state.current_review_index,
            "review_item_key": item.get("key"),
            "review_round": state.review_round,
            "retrieval_retry_count": state.retrieval_retry_count,
            "llm_call_count": state.llm_call_count,
        }

    @staticmethod
    def _output_summary(output: dict[str, Any] | None) -> dict[str, Any] | None:
        if output is None:
            return None
        usage = output.get("last_usage", {})
        model_call_count = usage.get("call_count", 0) if isinstance(usage, dict) else 0
        return {
            "next_action": output.get("next_action"),
            "issue_count": len(output.get("current_issues", [])),
            "verified_issue_count": len(output.get("verified_issues", [])),
            "rejected_issue_count": len(output.get("rejected_issues", [])),
            "warning": output.get("current_item_warning"),
            "stop_reason": output.get("stop_reason"),
            "model_call_count": model_call_count,
        }

    @staticmethod
    def _apply_usage(row: NodeRun, usage: object) -> None:
        if not isinstance(usage, dict) or not usage:
            row.usage_type = "none"
            return
        pricing = usage.get("pricing", {})
        if not isinstance(pricing, dict):
            pricing = {}
        row.usage_type = "llm"
        row.provider = str(usage.get("provider", "")) or None
        row.model_name = str(usage.get("model", "")) or None
        row.latency_ms = int(usage.get("latency_ms", 0))
        row.input_tokens = int(usage.get("input_tokens", 0))
        row.output_tokens = int(usage.get("output_tokens", 0))
        row.input_price_per_million = NodeRunService._decimal(
            pricing.get("input_price_per_million")
        )
        row.output_price_per_million = NodeRunService._decimal(
            pricing.get("output_price_per_million")
        )
        row.pricing_currency = str(pricing.get("currency", "")) or None
        row.pricing_version = str(pricing.get("version", "")) or None
        row.cost_status = str(usage.get("cost_status", "unavailable"))
        row.estimated_cost = NodeRunService._decimal(usage.get("estimated_cost"))

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))
