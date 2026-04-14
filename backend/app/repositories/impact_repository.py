from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class ImpactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_impacted_symbol(
        self,
        *,
        analysis_id: str,
        source_symbol_id: str,
        symbol_id: str,
        file_id: str,
        source_symbol_key: str,
        symbol_key: str,
        symbol_name: str,
        symbol_kind: str,
        file_path: str,
        hop_count: int,
        impact_reason: str,
        impact_path: list[str],
        edge_types: list[str],
        is_test: bool,
        created_at: datetime,
    ) -> models.ImpactedSymbol:
        record = models.ImpactedSymbol(
            analysis_id=analysis_id,
            source_symbol_id=source_symbol_id,
            symbol_id=symbol_id,
            file_id=file_id,
            source_symbol_key=source_symbol_key,
            symbol_key=symbol_key,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            file_path=file_path,
            hop_count=hop_count,
            impact_reason=impact_reason,
            impact_path=impact_path,
            edge_types=edge_types,
            is_test=is_test,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def create_impact(
        self,
        *,
        analysis_id: str,
        symbol_id: str,
        symbol_key: str,
        symbol_name: str,
        symbol_kind: str,
        file_path: str,
        score: float,
        confidence: str,
        reasons: list[str],
        explanation_path: list[str],
        reasons_json: dict[str, object],
    ) -> models.Impact:
        record = models.Impact(
            analysis_id=analysis_id,
            symbol_id=symbol_id,
            symbol_key=symbol_key,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            file_path=file_path,
            score=score,
            confidence=confidence,
            reasons=reasons,
            explanation_path=explanation_path,
            reasons_json=reasons_json,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_impacted_symbols(self, analysis_id: str) -> list[models.ImpactedSymbol]:
        statement = (
            select(models.ImpactedSymbol)
            .where(models.ImpactedSymbol.analysis_id == analysis_id)
            .order_by(
                models.ImpactedSymbol.hop_count,
                models.ImpactedSymbol.file_path,
                models.ImpactedSymbol.symbol_key,
            )
        )
        return list(self.session.execute(statement).scalars().all())

    def list_impacts(self, analysis_id: str) -> list[models.Impact]:
        statement = (
            select(models.Impact)
            .where(models.Impact.analysis_id == analysis_id)
            .order_by(
                models.Impact.score.desc(),
                models.Impact.file_path,
                models.Impact.symbol_name,
            )
        )
        return list(self.session.execute(statement).scalars().all())
