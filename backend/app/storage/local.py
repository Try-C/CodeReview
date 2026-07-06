"""Constrained local storage for untrusted project files."""

import os
import re
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from app.core.exceptions import AppError

STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class LocalProjectStorage:
    """Keep staging and completed uploads beneath one validated root."""

    def __init__(self, root: Path) -> None:
        self._configured_root = root.expanduser().absolute()

    @property
    def root(self) -> Path:
        """Return the configured absolute root without exposing a mutable path."""
        return self._configured_root

    def create_staging(self, upload_id: str) -> Path:
        """Create a fresh server-owned staging directory."""
        self._require_storage_key(upload_id)
        root = self._prepare_root()
        staging_parent = root / ".staging"
        staging_parent.mkdir(mode=0o700, exist_ok=True)
        self._reject_link(staging_parent)
        staging = self._within_root(staging_parent / upload_id)
        staging.mkdir(mode=0o700, exist_ok=False)
        return staging

    def temporary_target(self, upload_id: str, relative_path: str) -> tuple[Path, Path]:
        """Return safe temporary and final targets for a normalized relative path."""
        staging = self._staging(upload_id)
        self._assert_tree_has_no_links(staging)
        target = self._within(staging, staging.joinpath(*relative_path.split("/")))
        self._create_safe_parents(staging, target.parent)
        temporary = self._within(
            staging,
            target.parent / f".{target.name}.{uuid4().hex}.uploading",
        )
        return temporary, target

    def promote(self, upload_id: str, storage_key: str) -> Path:
        """Atomically move a completed staging directory into project storage."""
        staging = self._staging(upload_id)
        self._require_storage_key(storage_key)
        self._assert_tree_has_no_links(staging)
        destination = self._within_root(self._prepare_root() / storage_key)
        if destination.exists():
            raise RuntimeError("Project storage destination already exists")
        os.replace(staging, destination)
        return destination

    def rollback_promotion(self, storage_key: str, upload_id: str) -> None:
        """Move a promoted tree back to staging when the database commit fails."""
        project = self._project(storage_key)
        staging = self._staging(upload_id, must_exist=False)
        if project.exists() and not staging.exists():
            self._assert_tree_has_no_links(project)
            os.replace(project, staging)

    def delete_upload(self, upload_id: str) -> None:
        """Delete only a validated staging directory."""
        staging = self._staging(upload_id, must_exist=False)
        self._safe_rmtree(staging)

    def delete_project(self, storage_key: str) -> None:
        """Delete only a validated, database-supplied project directory."""
        project = self._project(storage_key)
        self._safe_rmtree(project)

    def _prepare_root(self) -> Path:
        self._configured_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._reject_link(self._configured_root)
        return self._configured_root.resolve(strict=True)

    def _staging(self, upload_id: str, *, must_exist: bool = True) -> Path:
        self._require_storage_key(upload_id)
        staging = self._within_root(self._prepare_root() / ".staging" / upload_id)
        if must_exist and not staging.is_dir():
            raise RuntimeError("Upload staging directory does not exist")
        return staging

    def _project(self, storage_key: str) -> Path:
        self._require_storage_key(storage_key)
        return self._within_root(self._prepare_root() / storage_key)

    def _within_root(self, candidate: Path) -> Path:
        return self._within(self._prepare_root(), candidate)

    @staticmethod
    def _within(root: Path, candidate: Path) -> Path:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=False)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise AppError(
                code="UNSAFE_UPLOAD_PATH",
                message="Upload path escapes the configured storage root",
                status_code=422,
            ) from exc
        return resolved_candidate

    def _create_safe_parents(self, root: Path, parent: Path) -> None:
        relative = parent.relative_to(root)
        current = root
        for component in relative.parts:
            current = current / component
            if current.exists():
                self._reject_link(current)
                if not current.is_dir():
                    raise AppError(
                        code="UNSAFE_UPLOAD_PATH",
                        message="Upload path conflicts with an existing file",
                        status_code=422,
                    )
            else:
                current.mkdir(mode=0o700)

    def _safe_rmtree(self, path: Path) -> None:
        if not path.exists():
            return
        self._within_root(path)
        self._assert_tree_has_no_links(path)
        shutil.rmtree(path)

    def _assert_tree_has_no_links(self, path: Path) -> None:
        self._reject_link(path)
        if not path.exists():
            return
        for root, directories, files in os.walk(path, followlinks=False):
            root_path = Path(root)
            self._reject_link(root_path)
            for name in (*directories, *files):
                self._reject_link(root_path / name)

    @staticmethod
    def _reject_link(path: Path) -> None:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if path.is_symlink() or attributes & REPARSE_POINT_ATTRIBUTE:
            raise AppError(
                code="UNSAFE_STORAGE_LINK",
                message="Storage paths must not contain links or reparse points",
                status_code=422,
            )

    @staticmethod
    def _require_storage_key(value: str) -> None:
        if STORAGE_KEY_PATTERN.fullmatch(value) is None:
            raise ValueError("Storage identifiers must be server-generated hex values")
