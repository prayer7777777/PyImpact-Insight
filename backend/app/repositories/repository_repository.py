from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class RepositoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        repo_path: str,
        main_branch: str,
        language: str,
        created_at: datetime,
    ) -> models.Repository:
        record = models.Repository(
            name=name,
            repo_path=repo_path,
            main_branch=main_branch,
            language=language,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_by_id(self, repository_id: str) -> models.Repository | None:
        return self.session.get(models.Repository, repository_id)

    def get_by_path(self, repo_path: str) -> models.Repository | None:
        statement = select(models.Repository).where(models.Repository.repo_path == repo_path)
        return self.session.execute(statement).scalar_one_or_none()

