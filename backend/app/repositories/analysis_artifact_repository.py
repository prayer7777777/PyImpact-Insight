from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class AnalysisArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_code_file(
        self,
        *,
        repository_id: str,
        analysis_id: str,
        path: str,
        module_name: str,
        content_hash: str,
        parse_status: str,
        error_message: str | None,
        created_at: datetime,
    ) -> models.CodeFile:
        record = models.CodeFile(
            repository_id=repository_id,
            analysis_id=analysis_id,
            path=path,
            module_name=module_name,
            content_hash=content_hash,
            parse_status=parse_status,
            error_message=error_message,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_symbol(
        self,
        *,
        analysis_id: str,
        file_id: str,
        kind: str,
        qualname: str,
        name: str,
        start_line: int,
        end_line: int,
        created_at: datetime,
    ) -> models.Symbol:
        record = models.Symbol(
            analysis_id=analysis_id,
            file_id=file_id,
            kind=kind,
            qualname=qualname,
            name=name,
            start_line=start_line,
            end_line=end_line,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_edge(
        self,
        *,
        analysis_id: str,
        src_symbol_id: str,
        dst_symbol_id: str,
        edge_type: str,
        weight: float,
        evidence: dict[str, Any],
        created_at: datetime,
    ) -> models.Edge:
        record = models.Edge(
            analysis_id=analysis_id,
            src_symbol_id=src_symbol_id,
            dst_symbol_id=dst_symbol_id,
            edge_type=edge_type,
            weight=weight,
            evidence=evidence,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def commit(self) -> None:
        self.session.commit()

    def list_code_files(self, analysis_id: str) -> list[models.CodeFile]:
        statement = select(models.CodeFile).where(models.CodeFile.analysis_id == analysis_id)
        return list(self.session.execute(statement).scalars().all())

    def list_symbols(self, analysis_id: str) -> list[models.Symbol]:
        statement = select(models.Symbol).where(models.Symbol.analysis_id == analysis_id)
        return list(self.session.execute(statement).scalars().all())

    def list_edges(self, analysis_id: str) -> list[models.Edge]:
        statement = select(models.Edge).where(models.Edge.analysis_id == analysis_id)
        return list(self.session.execute(statement).scalars().all())

