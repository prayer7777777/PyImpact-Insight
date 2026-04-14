from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    repository_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    repo_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    main_branch: Mapped[str] = mapped_column(String(120), nullable=False, default="main")
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analyses: Mapped[list[Analysis]] = relationship(back_populates="repository")
    code_files: Mapped[list[CodeFile]] = relationship(back_populates="repository")


class Analysis(Base):
    __tablename__ = "analyses"

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repository_id"), nullable=False, index=True
    )
    diff_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    commit_from: Mapped[str | None] = mapped_column(String(120))
    commit_to: Mapped[str | None] = mapped_column(String(120))
    base_ref: Mapped[str | None] = mapped_column(String(120))
    head_ref: Mapped[str | None] = mapped_column(String(120))
    include_untracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)

    repository: Mapped[Repository] = relationship(back_populates="analyses")
    code_files: Mapped[list[CodeFile]] = relationship(back_populates="analysis")
    symbols: Mapped[list[Symbol]] = relationship(back_populates="analysis")
    edges: Mapped[list[Edge]] = relationship(back_populates="analysis")
    change_spans: Mapped[list[ChangeSpan]] = relationship(back_populates="analysis")
    changed_symbols: Mapped[list[ChangedSymbol]] = relationship(back_populates="analysis")
    impacted_symbols: Mapped[list[ImpactedSymbol]] = relationship(back_populates="analysis")
    impacts: Mapped[list[Impact]] = relationship(back_populates="analysis")
    test_recommendations: Mapped[list[TestRecommendation]] = relationship(back_populates="analysis")


class CodeFile(Base):
    __tablename__ = "code_files"

    file_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repository_id"), nullable=False, index=True
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    module_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="code_files")
    analysis: Mapped[Analysis] = relationship(back_populates="code_files")
    symbols: Mapped[list[Symbol]] = relationship(back_populates="code_file")
    change_spans: Mapped[list[ChangeSpan]] = relationship(back_populates="code_file")
    changed_symbols: Mapped[list[ChangedSymbol]] = relationship(back_populates="code_file")
    impacted_symbols: Mapped[list[ImpactedSymbol]] = relationship(back_populates="code_file")


class Symbol(Base):
    __tablename__ = "symbols"

    symbol_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("code_files.file_id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    qualname: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="symbols")
    code_file: Mapped[CodeFile] = relationship(back_populates="symbols")
    change_spans: Mapped[list[ChangeSpan]] = relationship(back_populates="mapped_symbol")
    changed_symbols: Mapped[list[ChangedSymbol]] = relationship(back_populates="symbol")
    impacted_symbols: Mapped[list[ImpactedSymbol]] = relationship(
        back_populates="symbol", foreign_keys="ImpactedSymbol.symbol_id"
    )
    source_impacts: Mapped[list[ImpactedSymbol]] = relationship(
        back_populates="source_symbol", foreign_keys="ImpactedSymbol.source_symbol_id"
    )


class Edge(Base):
    __tablename__ = "edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    src_symbol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=False, index=True
    )
    dst_symbol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=False, index=True
    )
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="edges")
    src_symbol: Mapped[Symbol] = relationship(foreign_keys=[src_symbol_id])
    dst_symbol: Mapped[Symbol] = relationship(foreign_keys=[dst_symbol_id])


class ChangeSpan(Base):
    __tablename__ = "change_spans"

    change_span_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("code_files.file_id"), nullable=True, index=True
    )
    mapped_symbol_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    old_path: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    is_python: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_binary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_unmapped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="change_spans")
    code_file: Mapped[CodeFile | None] = relationship(back_populates="change_spans")
    mapped_symbol: Mapped[Symbol | None] = relationship(back_populates="change_spans")


class ChangedSymbol(Base):
    __tablename__ = "changed_symbols"

    changed_symbol_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    symbol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("code_files.file_id"), nullable=False, index=True
    )
    symbol_key: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    is_module_level: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="changed_symbols")
    symbol: Mapped[Symbol] = relationship(back_populates="changed_symbols")
    code_file: Mapped[CodeFile] = relationship(back_populates="changed_symbols")


class ImpactedSymbol(Base):
    __tablename__ = "impacted_symbols"

    impacted_symbol_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    source_symbol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=False, index=True
    )
    symbol_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id"), nullable=False, index=True
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("code_files.file_id"), nullable=False, index=True
    )
    source_symbol_key: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_key: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    impact_reason: Mapped[str] = mapped_column(Text, nullable=False)
    impact_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    edge_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    analysis: Mapped[Analysis] = relationship(back_populates="impacted_symbols")
    source_symbol: Mapped[Symbol] = relationship(
        back_populates="source_impacts", foreign_keys=[source_symbol_id]
    )
    symbol: Mapped[Symbol] = relationship(
        back_populates="impacted_symbols", foreign_keys=[symbol_id]
    )
    code_file: Mapped[CodeFile] = relationship(back_populates="impacted_symbols")


class Impact(Base):
    __tablename__ = "impacts"

    impact_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    symbol_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    symbol_key: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    explanation_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reasons_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    analysis: Mapped[Analysis] = relationship(back_populates="impacts")


class TestRecommendation(Base):
    __tablename__ = "test_recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.analysis_id"), nullable=False, index=True
    )
    test_symbol_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    test_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_backed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    analysis: Mapped[Analysis] = relationship(back_populates="test_recommendations")
