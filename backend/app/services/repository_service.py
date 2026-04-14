from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.api import schemas
from app.core.errors import ApiError
from app.db import models
from app.repositories.repository_repository import RepositoryRepository


class RepositoryService:
    def __init__(self, session: Session) -> None:
        self.repository_repository = RepositoryRepository(session)

    def create_repository(self, payload: schemas.RepositoryCreate) -> schemas.RepositoryRead:
        repo_path = self._validate_repository_path(payload.repo_path)
        existing = self.repository_repository.get_by_path(repo_path)
        if existing is not None:
            return self._to_schema(existing)

        record = self.repository_repository.create(
            name=payload.name,
            repo_path=repo_path,
            main_branch=payload.main_branch or self._read_current_branch(repo_path),
            language="python",
            created_at=datetime.now(UTC),
        )
        return self._to_schema(record)

    def get_repository(self, repository_id: str) -> models.Repository:
        record = self.repository_repository.get_by_id(repository_id)
        if record is None:
            raise ApiError(
                "INVALID_REQUEST",
                "repository_id does not refer to a registered repository.",
                status_code=404,
                details={"repository_id": repository_id},
            )
        return record

    def _validate_repository_path(self, raw_path: str) -> str:
        candidate = Path(raw_path).expanduser()
        if not candidate.exists():
            raise ApiError(
                "INVALID_REPOSITORY_PATH",
                "Repository path does not exist.",
                status_code=400,
                details={"repo_path": raw_path},
            )
        if not candidate.is_dir():
            raise ApiError(
                "INVALID_REPOSITORY_PATH",
                "Repository path must be a directory.",
                status_code=400,
                details={"repo_path": raw_path},
            )
        resolved = candidate.resolve()
        if not os.access(resolved, os.R_OK):
            raise ApiError(
                "INVALID_REPOSITORY_PATH",
                "Repository path is not readable.",
                status_code=400,
                details={"repo_path": str(resolved)},
            )

        git_marker = resolved / ".git"
        if not git_marker.exists():
            raise ApiError(
                "NOT_A_GIT_REPOSITORY",
                "Repository path must contain a .git entry.",
                status_code=400,
                details={"repo_path": str(resolved)},
            )
        if not os.access(git_marker, os.R_OK):
            raise ApiError(
                "INVALID_REPOSITORY_PATH",
                "Repository .git entry is not readable.",
                status_code=400,
                details={"repo_path": str(resolved), "git_path": str(git_marker)},
            )
        return str(resolved)

    def _read_current_branch(self, repo_path: str) -> str:
        head_path = Path(repo_path) / ".git" / "HEAD"
        if not head_path.is_file():
            return "main"
        try:
            head = head_path.read_text(encoding="utf-8").strip()
        except OSError:
            return "main"
        prefix = "ref: refs/heads/"
        if head.startswith(prefix):
            return head.removeprefix(prefix)
        return "main"

    def _to_schema(self, record: models.Repository) -> schemas.RepositoryRead:
        return schemas.RepositoryRead(
            repository_id=record.repository_id,
            name=record.name,
            repo_path=record.repo_path,
            main_branch=record.main_branch,
            language="python",
            created_at=record.created_at,
        )

