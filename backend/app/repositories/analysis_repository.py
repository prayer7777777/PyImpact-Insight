from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        repository_id: str,
        diff_mode: str,
        commit_from: str | None,
        commit_to: str | None,
        base_ref: str | None,
        head_ref: str | None,
        include_untracked: bool,
        options: dict[str, Any],
        status: str,
        created_at: datetime,
        summary: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> models.Analysis:
        record = models.Analysis(
            repository_id=repository_id,
            diff_mode=diff_mode,
            commit_from=commit_from,
            commit_to=commit_to,
            base_ref=base_ref,
            head_ref=head_ref,
            include_untracked=include_untracked,
            options=options,
            status=status,
            created_at=created_at,
            summary=summary,
            warnings=warnings,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_by_id(self, analysis_id: str) -> models.Analysis | None:
        return self.session.get(models.Analysis, analysis_id)

    def list_impacts(self, analysis_id: str) -> list[models.Impact]:
        statement = select(models.Impact).where(models.Impact.analysis_id == analysis_id)
        return list(self.session.execute(statement).scalars().all())

    def list_test_recommendations(self, analysis_id: str) -> list[models.TestRecommendation]:
        statement = select(models.TestRecommendation).where(
            models.TestRecommendation.analysis_id == analysis_id
        )
        return list(self.session.execute(statement).scalars().all())

    def set_status(
        self,
        record: models.Analysis,
        *,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        summary: dict[str, Any] | None = None,
        warnings: list[dict[str, Any]] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> models.Analysis:
        record.status = status
        if started_at is not None:
            record.started_at = started_at
        if finished_at is not None:
            record.finished_at = finished_at
        if summary is not None:
            record.summary = summary
        if warnings is not None:
            record.warnings = warnings
        record.error_code = error_code
        record.error_message = error_message
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record
