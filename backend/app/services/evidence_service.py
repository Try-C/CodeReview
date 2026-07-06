"""Deterministic evidence verification per spec §13.

Four checks for every issue:
    1. path_valid       — file exists within project root, no symlinks
    2. line_range_valid — 1 <= start <= end <= file_line_count
    3. evidence_match   — evidence text matches file content at the declared lines
    4. chunks_owned     — every source_chunk_id belongs to the project

Failures are recorded and the issue is blocked from entering the Critic stage.
"""

from __future__ import annotations

import hashlib
import logging
import stat
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)


class EvidenceService:
    """Stateless; every verify_one() call receives explicit project_id and root."""

    async def verify_one(
        self,
        *,
        issue: dict[str, Any],
        project_id: int,
        project_root: str,
        file_cache: dict[str, str] | None = None,
        session: Any = None,
    ) -> dict[str, Any]:
        """Run all four checks against one issue and return a result dict.

        The returned dict is a shallow copy of *issue* extended with
        ``evidence_checks``, ``evidence_status``, and ``fingerprint``.
        """
        root = Path(project_root).resolve()
        rel = issue.get("relative_path", "")
        if file_cache is None:
            file_cache = {}
        checks: dict[str, bool] = {}

        # 1. Path check.
        checks["path"] = self._check_path(rel, root)

        # 2. Line range check.
        checks["lines"] = self._check_lines(issue, file_cache, root, rel)

        # 3. Evidence match.
        checks["evidence"] = self._check_evidence(issue, file_cache, root, rel)

        # 4. Chunk ownership.
        checks["chunks"] = await self._check_chunks(
            issue.get("source_chunk_ids", []), project_id, session
        )

        result = {**issue}
        result["evidence_checks"] = checks
        result["evidence_status"] = "passed" if all(checks.values()) else "failed"
        result["fingerprint"] = self._build_fingerprint(result)
        return result

    # ── Individual checks ────────────────────────────────────────────────

    @staticmethod
    def _check_path(relative_path: str, root: Path) -> bool:
        """Verify the path resolves safely within *root* and is a regular file."""
        if not relative_path:
            return False
        try:
            raw_target = root / relative_path
            current = root
            for component in Path(relative_path).parts:
                current = current / component
                attributes = getattr(
                    current.stat(follow_symlinks=False),
                    "st_file_attributes",
                    0,
                )
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                if current.is_symlink() or attributes & reparse_flag:
                    return False
            target = raw_target.resolve()
            target.relative_to(root)
        except (AttributeError, ValueError, OSError):
            return False
        return target.is_file()

    @staticmethod
    def _check_lines(
        issue: dict[str, Any],
        file_cache: dict[str, str],
        root: Path,
        rel: str,
    ) -> bool:
        """Validate 1 <= start_line <= end_line <= file_line_count."""
        start = issue.get("start_line", 0)
        end = issue.get("end_line", 0)
        if not (isinstance(start, int) and isinstance(end, int)):
            return False
        if not (1 <= start <= end):
            return False
        content = EvidenceService._read_file(root, rel, file_cache)
        if content is None:
            return False
        line_count = content.count("\n") + (1 if content else 0)
        return end <= line_count

    @staticmethod
    def _check_evidence(
        issue: dict[str, Any],
        file_cache: dict[str, str],
        root: Path,
        rel: str,
    ) -> bool:
        """Check that the evidence text appears within the declared line range."""
        evidence = issue.get("evidence", "")
        if not evidence:
            return False
        start = issue.get("start_line", 0)
        end = issue.get("end_line", 0)
        content = EvidenceService._read_file(root, rel, file_cache)
        if content is None:
            return False
        lines = content.split("\n")
        if end > len(lines):
            return False
        # Extract the declared line range (0-indexed).
        snippet = "\n".join(lines[start - 1 : end])
        # Only normalise line endings and outer whitespace. Internal whitespace
        # remains exact so deterministic evidence cannot drift into fuzzy matching.
        norm_evidence = evidence.replace("\r\n", "\n").replace("\r", "\n").strip()
        norm_snippet = snippet.replace("\r\n", "\n").replace("\r", "\n").strip()
        return norm_evidence in norm_snippet

    @staticmethod
    async def _check_chunks(
        source_chunk_ids: list[int],
        project_id: int,
        session: Any,
    ) -> bool:
        """Verify every source_chunk_id exists and belongs to *project_id*.

        A missing database session fails closed: ownership cannot be established.
        """
        if not source_chunk_ids:
            return False
        if session is None:
            return False
        try:
            from sqlalchemy import select

            from app.models.index import CodeChunk

            expected = set(source_chunk_ids)
            rows = await session.scalars(
                select(CodeChunk.id).where(
                    CodeChunk.id.in_(list(expected)),
                    CodeChunk.project_id == project_id,
                )
            )
            actual = set(rows)
            return actual == expected
        except Exception as exc:
            logger.warning("chunk_check_error %s", exc)
            return False

    # ── Fingerprint ──────────────────────────────────────────────────────

    @staticmethod
    def _build_fingerprint(issue: dict[str, Any]) -> str:
        """SHA-256 of (normalised_path + start_line + end_line + rule_id + evidence_hash)."""
        path = PurePosixPath(str(issue.get("relative_path", "")).replace("\\", "/")).as_posix()
        start = str(issue.get("start_line", 0))
        end = str(issue.get("end_line", 0))
        rule = str(issue.get("rule_id", ""))
        evidence = str(issue.get("evidence", ""))
        evidence_hash = hashlib.sha256(evidence.encode()).hexdigest()
        raw = "\0".join((path, start, end, rule, evidence_hash))
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── File I/O ─────────────────────────────────────────────────────────

    @staticmethod
    def _read_file(root: Path, rel: str, cache: dict[str, str]) -> str | None:
        """Read file content, using *cache* to avoid repeated I/O."""
        if rel in cache:
            return cache[rel]
        try:
            target = (root / rel).resolve()
            target.relative_to(root)
            content = target.read_text(encoding="utf-8")
            cache[rel] = content
            return content
        except Exception:
            return None
