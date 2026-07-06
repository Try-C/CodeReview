"""Unit tests for upload path policy and isolated local storage."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import AppError
from app.schemas.upload import UploadInitRequest
from app.services.upload_policy import UploadPolicy
from app.storage.local import LocalProjectStorage


@pytest.fixture
def policy() -> UploadPolicy:
    return UploadPolicy(Settings(_env_file=None, app_env="test"))


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.py",
        "/absolute.py",
        "C:/windows.py",
        "src\\windows.py",
        "src//collapsed.py",
        "src/./collapsed.py",
        "src/con.py",
        "src/trailing.py ",
        "src/invalid?.py",
    ],
)
def test_unsafe_cross_platform_paths_are_rejected(
    policy: UploadPolicy,
    relative_path: str,
) -> None:
    with pytest.raises(AppError) as error:
        policy.normalize_path(relative_path)

    assert error.value.code == "UNSAFE_UPLOAD_PATH"


def test_policy_classifies_languages_and_default_exclusions(policy: UploadPolicy) -> None:
    assert policy.normalize_path("src/review.py") == "src/review.py"
    assert policy.language_for("src/review.py") == "python"
    assert policy.language_for("src/Review.java") == "java"
    assert policy.language_for("README.md") is None
    assert policy.is_excluded("node_modules/generated.py")
    assert not policy.is_excluded("src/review.py")


def test_blank_project_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="project_name must not be blank"):
        UploadInitRequest(
            project_name="   ",
            files=[{"relative_path": "main.py", "size": 1}],
        )


def test_storage_keeps_targets_beneath_root_and_deletes_registered_tree(
    tmp_path: Path,
) -> None:
    storage = LocalProjectStorage(tmp_path / "uploads")
    upload_id = "a" * 32
    storage_key = "b" * 32
    storage.create_staging(upload_id)

    with pytest.raises(AppError, match="escapes"):
        storage.temporary_target(upload_id, "../outside.py")

    temporary, target = storage.temporary_target(upload_id, "src/main.py")
    temporary.write_text("print('safe')\n", encoding="utf-8")
    temporary.replace(target)
    project_root = storage.promote(upload_id, storage_key)

    assert target.relative_to(storage.root)
    assert (project_root / "src" / "main.py").is_file()

    storage.delete_project(storage_key)

    assert not project_root.exists()
