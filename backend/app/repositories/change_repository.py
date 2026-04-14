from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_change_span(
        self,
        *,
        analysis_id: str,
        file_id: str | None,
        mapped_symbol_id: str | None,
        path: str,
        old_path: str | None,
        change_type: str,
        start_line: int | None,
        end_line: int | None,
        is_python: bool,
        is_binary: bool,
        is_unmapped: bool,
        created_at: datetime,
    ) -> models.ChangeSpan:
        record = models.ChangeSpan(
            analysis_id=analysis_id,
            file_id=file_id,
            mapped_symbol_id=mapped_symbol_id,
            path=path,
            old_path=old_path,
            change_type=change_type,
            start_line=start_line,
            end_line=end_line,
            is_python=is_python,
            is_binary=is_binary,
            is_unmapped=is_unmapped,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_changed_symbol(
        self,
        *,
        analysis_id: str,
        symbol_id: str,
        file_id: str,
        symbol_key: str,
        symbol_name: str,
        symbol_kind: str,
        file_path: str,
        change_type: str,
        start_line: int,
        end_line: int,
        is_module_level: bool,
        created_at: datetime,
    ) -> models.ChangedSymbol:
        record = models.ChangedSymbol(
            analysis_id=analysis_id,
            symbol_id=symbol_id,
            file_id=file_id,
            symbol_key=symbol_key,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            file_path=file_path,
            change_type=change_type,
            start_line=start_line,
            end_line=end_line,
            is_module_level=is_module_level,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_change_spans(self, analysis_id: str) -> list[models.ChangeSpan]:
        statement = (
            select(models.ChangeSpan)
            .where(models.ChangeSpan.analysis_id == analysis_id)
            .order_by(models.ChangeSpan.path, models.ChangeSpan.start_line)
        )
        return list(self.session.execute(statement).scalars().all())

    def list_changed_symbols(self, analysis_id: str) -> list[models.ChangedSymbol]:
        statement = (
            select(models.ChangedSymbol)
            .where(models.ChangedSymbol.analysis_id == analysis_id)
            .order_by(models.ChangedSymbol.file_path, models.ChangedSymbol.start_line)
        )
        return list(self.session.execute(statement).scalars().all())
