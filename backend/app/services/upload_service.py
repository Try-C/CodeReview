"""Secure folder upload orchestration and project creation."""

import hashlib
import os
from collections import Counter
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.project import Project, ProjectFile
from app.models.upload import UploadSession
from app.schemas.project import ProjectResponse
from app.schemas.upload import (
    UploadCompleteResponse,
    UploadInitRequest,
    UploadManifestItem,
    UploadSessionResponse,
)
from app.services.upload_policy import UploadPolicy
from app.storage.local import LocalProjectStorage

READ_CHUNK_SIZE = 64 * 1024
ALLOWED_TEXT_CONTROL_BYTES = frozenset(b"\t\n\f\r")
REJECTED_MIME_PREFIXES = ("audio/", "font/", "image/", "video/")
REJECTED_MIME_TYPES = {
    "application/pdf",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/zip",
}


class UploadService:
    """Persist an immutable manifest and stream validated files into isolation."""

    def __init__(
        self,
        session: AsyncSession,
        storage: LocalProjectStorage,
        settings: Settings,
    ) -> None:
        self._session = session
        self._storage = storage
        self._policy = UploadPolicy(settings)
        self._settings = settings

    async def initialize(self, user_id: int, payload: UploadInitRequest) -> UploadSession:
        """Validate the manifest and create a fresh isolated staging directory."""
        if len(payload.files) > self._settings.max_file_count:
            raise AppError(
                code="UPLOAD_FILE_COUNT_EXCEEDED",
                message="Manifest exceeds the configured file count limit",
                status_code=422,
                details={"max_file_count": self._settings.max_file_count},
            )

        manifest: list[UploadManifestItem] = []
        seen_paths: set[str] = set()
        accepted_declared_size = 0
        for requested in payload.files:
            relative_path = self._policy.normalize_path(requested.relative_path)
            collision_key = relative_path.casefold()
            if collision_key in seen_paths:
                raise AppError(
                    code="DUPLICATE_UPLOAD_PATH",
                    message="Manifest paths must be unique across platforms",
                    status_code=422,
                    details={"relative_path": relative_path},
                )
            seen_paths.add(collision_key)

            language = self._policy.language_for(relative_path)
            status = "pending"
            reason = None
            if self._policy.is_excluded(relative_path):
                status = "skipped"
                reason = "EXCLUDED_PATH"
            elif language is None:
                status = "skipped"
                reason = "UNSUPPORTED_FILE_TYPE"
            elif requested.size > self._policy.max_file_bytes:
                status = "skipped"
                reason = "SINGLE_FILE_SIZE_EXCEEDED"
            else:
                accepted_declared_size += requested.size
            manifest.append(
                UploadManifestItem(
                    relative_path=relative_path,
                    declared_size=requested.size,
                    status=status,
                    language=language,
                    reason=reason,
                )
            )

        if accepted_declared_size > self._policy.max_project_bytes:
            raise AppError(
                code="UPLOAD_PROJECT_SIZE_EXCEEDED",
                message="Manifest exceeds the configured project size limit",
                status_code=422,
                details={"max_project_size_bytes": self._policy.max_project_bytes},
            )

        upload_id = uuid4().hex
        self._storage.create_staging(upload_id)
        upload = UploadSession(
            user_id=user_id,
            upload_id=upload_id,
            project_name=payload.project_name,
            total_files=len(manifest),
            skipped_files=sum(item.status == "skipped" for item in manifest),
            total_size=sum(item.declared_size for item in manifest),
            manifest=[item.model_dump(mode="json") for item in manifest],
        )
        self._session.add(upload)
        try:
            await self._session.commit()
            await self._session.refresh(upload)
        except BaseException:
            await self._session.rollback()
            self._storage.delete_upload(upload_id)
            raise
        return upload

    async def get(self, upload_id: str, user_id: int) -> UploadSession:
        """Return an upload only to its owner."""
        upload = await self._session.scalar(
            select(UploadSession).where(
                UploadSession.upload_id == upload_id,
                UploadSession.user_id == user_id,
            )
        )
        if upload is None:
            raise self._not_found(upload_id)
        return upload

    async def upload_files(
        self,
        upload_id: str,
        user_id: int,
        files: list[UploadFile],
    ) -> UploadSession:
        """Stream a retry-safe batch and update manifest coverage."""
        upload = await self._locked(upload_id, user_id)
        if upload.status == "completed":
            raise AppError(
                code="UPLOAD_ALREADY_COMPLETED",
                message="Completed uploads cannot accept more files",
                status_code=409,
            )

        manifest = [UploadManifestItem.model_validate(item) for item in upload.manifest]
        manifest_by_path = {item.relative_path: item for item in manifest}
        normalized_names: list[str] = []
        batch_names: set[str] = set()
        for upload_file in files:
            if upload_file.filename is None:
                raise AppError(
                    code="UPLOAD_FILENAME_REQUIRED",
                    message="Every uploaded file must include its manifest path",
                    status_code=422,
                )
            relative_path = self._policy.normalize_path(upload_file.filename)
            if relative_path in batch_names:
                raise AppError(
                    code="DUPLICATE_UPLOAD_PATH",
                    message="A batch cannot contain the same path twice",
                    status_code=422,
                    details={"relative_path": relative_path},
                )
            item = manifest_by_path.get(relative_path)
            if item is None:
                raise AppError(
                    code="FILE_NOT_IN_MANIFEST",
                    message="Uploaded files must be declared in the manifest",
                    status_code=422,
                    details={"relative_path": relative_path},
                )
            if item.status == "skipped" and item.actual_size is None:
                raise AppError(
                    code="FILE_NOT_UPLOADABLE",
                    message="A server-skipped manifest entry cannot be uploaded",
                    status_code=422,
                    details={"relative_path": relative_path, "reason": item.reason},
                )
            batch_names.add(relative_path)
            normalized_names.append(relative_path)

        for upload_file, relative_path in zip(files, normalized_names, strict=True):
            item = manifest_by_path[relative_path]
            await self._store_file(upload_id, upload_file, item, manifest)

        self._apply_manifest(upload, manifest)
        upload.status = "uploading" if upload.uploaded_files else "created"
        await self._session.commit()
        await self._session.refresh(upload)
        return upload

    async def complete(self, upload_id: str, user_id: int) -> UploadCompleteResponse:
        """Finalize coverage and atomically expose an uploaded project."""
        upload = await self._locked(upload_id, user_id)
        if upload.status == "completed":
            if upload.project_id is None:
                raise RuntimeError("Completed upload is missing its project")
            project = await self._session.get(Project, upload.project_id)
            if project is None:
                raise RuntimeError("Completed upload references a missing project")
            return self._complete_response(upload, project)

        manifest = [UploadManifestItem.model_validate(item) for item in upload.manifest]
        pending = [item.relative_path for item in manifest if item.status == "pending"]
        if pending:
            raise AppError(
                code="UPLOAD_INCOMPLETE",
                message="Every accepted manifest file must be uploaded before completion",
                status_code=409,
                details={"pending_files": pending[:20], "pending_count": len(pending)},
            )
        uploaded = [item for item in manifest if item.status == "uploaded"]
        if not uploaded:
            raise AppError(
                code="UPLOAD_HAS_NO_ACCEPTED_FILES",
                message="At least one valid Java or Python file is required",
                status_code=409,
            )

        language_stats: dict[str, int] = dict(
            Counter(item.language for item in uploaded if item.language is not None)
        )
        main_language = max(language_stats, key=language_stats.__getitem__)
        storage_key = uuid4().hex
        project = Project(
            user_id=user_id,
            project_name=upload.project_name,
            storage_key=storage_key,
            main_language=main_language,
            language_stats=language_stats,
            total_files=len(uploaded),
            total_lines=sum(item.line_count or 0 for item in uploaded),
            total_size=sum(item.actual_size or 0 for item in uploaded),
        )
        project.files.extend(
            ProjectFile(
                relative_path=item.relative_path,
                content_hash=item.content_hash,
                language=item.language,
                size=item.actual_size or 0,
                line_count=item.line_count or 0,
            )
            for item in uploaded
        )
        self._session.add(project)
        await self._session.flush()
        upload.project_id = project.id
        upload.status = "completed"
        self._storage.promote(upload_id, storage_key)
        try:
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            self._storage.rollback_promotion(storage_key, upload_id)
            raise
        await self._session.refresh(upload)
        await self._session.refresh(project)
        return self._complete_response(upload, project)

    async def _locked(self, upload_id: str, user_id: int) -> UploadSession:
        upload = await self._session.scalar(
            select(UploadSession)
            .where(
                UploadSession.upload_id == upload_id,
                UploadSession.user_id == user_id,
            )
            .with_for_update()
        )
        if upload is None:
            raise self._not_found(upload_id)
        return upload

    async def _store_file(
        self,
        upload_id: str,
        upload_file: UploadFile,
        item: UploadManifestItem,
        manifest: list[UploadManifestItem],
    ) -> None:
        content_type = (upload_file.content_type or "").casefold()
        if content_type.startswith(REJECTED_MIME_PREFIXES) or content_type in REJECTED_MIME_TYPES:
            self._reject_item(item, "UNSUPPORTED_MIME_TYPE")
            return

        temporary, target = self._storage.temporary_target(
            upload_id,
            item.relative_path,
        )
        digest = hashlib.sha256()
        actual_size = 0
        contains_nul = False
        control_bytes = 0
        try:
            with temporary.open("xb") as destination:
                while chunk := await upload_file.read(READ_CHUNK_SIZE):
                    actual_size += len(chunk)
                    if actual_size > self._policy.max_file_bytes:
                        self._reject_item(item, "SINGLE_FILE_SIZE_EXCEEDED")
                        return
                    contains_nul = contains_nul or b"\x00" in chunk
                    control_bytes += sum(
                        byte < 32 and byte not in ALLOWED_TEXT_CONTROL_BYTES for byte in chunk
                    )
                    digest.update(chunk)
                    destination.write(chunk)

            if actual_size != item.declared_size:
                self._reject_item(item, "FILE_SIZE_MISMATCH", failed=True)
                return
            if contains_nul or control_bytes * 10 > actual_size * 3:
                self._reject_item(item, "BINARY_FILE")
                return
            decoded = self._decode_text(temporary)
            if decoded is None:
                self._reject_item(item, "UNSUPPORTED_ENCODING")
                return
            text, encoding = decoded
            line_count = len(text.splitlines())
            other_lines = sum(
                candidate.line_count or 0
                for candidate in manifest
                if candidate is not item and candidate.status == "uploaded"
            )
            if other_lines + line_count > self._settings.max_total_lines:
                self._reject_item(item, "TOTAL_LINE_COUNT_EXCEEDED")
                return
            other_size = sum(
                candidate.actual_size or 0
                for candidate in manifest
                if candidate is not item and candidate.status == "uploaded"
            )
            if other_size + actual_size > self._policy.max_project_bytes:
                self._reject_item(item, "PROJECT_SIZE_EXCEEDED")
                return
            os.replace(temporary, target)
            item.status = "uploaded"
            item.reason = None
            item.actual_size = actual_size
            item.line_count = line_count
            item.content_hash = digest.hexdigest()
            item.encoding = encoding
        except OSError:
            self._reject_item(item, "FILE_WRITE_FAILED", failed=True)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _decode_text(path: Path) -> tuple[str, str] | None:
        data = path.read_bytes()
        candidates = ("utf-8-sig", "utf-8") if data.startswith(b"\xef\xbb\xbf") else ("utf-8",)
        for encoding in (*candidates, "gb18030", "gbk"):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        return None

    @staticmethod
    def _reject_item(
        item: UploadManifestItem,
        reason: str,
        *,
        failed: bool = False,
    ) -> None:
        if item.status == "uploaded":
            return
        item.status = "failed" if failed else "skipped"
        item.reason = reason
        item.actual_size = None
        item.line_count = None
        item.content_hash = None
        item.encoding = None

    @staticmethod
    def _apply_manifest(
        upload: UploadSession,
        manifest: list[UploadManifestItem],
    ) -> None:
        upload.manifest = [item.model_dump(mode="json") for item in manifest]
        upload.total_files = len(manifest)
        upload.uploaded_files = sum(item.status == "uploaded" for item in manifest)
        upload.skipped_files = sum(item.status == "skipped" for item in manifest)
        upload.failed_files = sum(item.status == "failed" for item in manifest)
        upload.total_size = sum(item.declared_size for item in manifest)
        upload.uploaded_size = sum(
            item.actual_size or 0 for item in manifest if item.status == "uploaded"
        )

    @staticmethod
    def _complete_response(
        upload: UploadSession,
        project: Project,
    ) -> UploadCompleteResponse:
        return UploadCompleteResponse(
            upload=UploadSessionResponse.model_validate(upload),
            project=ProjectResponse.model_validate(project),
        )

    @staticmethod
    def _not_found(upload_id: str) -> AppError:
        return AppError(
            code="UPLOAD_NOT_FOUND",
            message="Upload does not exist",
            status_code=404,
            details={"upload_id": upload_id},
        )
