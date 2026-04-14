from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiffMode(StrEnum):
    WORKING_TREE = "working_tree"
    COMMIT_RANGE = "commit_range"
    REFS_COMPARE = "refs_compare"


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FileChangeType(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ParseStatus(StrEnum):
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"
    SKIPPED_BINARY = "skipped_binary"
    SKIPPED_NON_PYTHON = "skipped_non_python"
    SKIPPED_IGNORED = "skipped_ignored"
    MISSING = "missing"


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    ASYNC_METHOD = "async_method"
    STATICMETHOD = "staticmethod"
    CLASSMETHOD = "classmethod"
    TEST_FUNCTION = "test_function"
    TEST_METHOD = "test_method"


class EdgeType(StrEnum):
    CONTAINS = "contains"
    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    TESTS = "tests"
    SAME_MODULE_PROXIMITY = "same_module_proximity"
    SAME_PACKAGE_PROXIMITY = "same_package_proximity"
    NAME_SIMILARITY = "name_similarity"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_REPOSITORY_PATH = "INVALID_REPOSITORY_PATH"
    NOT_A_GIT_REPOSITORY = "NOT_A_GIT_REPOSITORY"
    REPOSITORY_HAS_NO_COMMITS = "REPOSITORY_HAS_NO_COMMITS"
    INVALID_DIFF_MODE = "INVALID_DIFF_MODE"
    INVALID_REF = "INVALID_REF"
    ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ErrorBody(BaseModel):
    code: ErrorCode | str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repo_path: str = Field(min_length=1)
    main_branch: str | None = Field(default=None, min_length=1, max_length=120)


class RepositoryRead(BaseModel):
    repository_id: UUID
    name: str
    repo_path: str
    main_branch: str
    language: Literal["python"]
    created_at: datetime


class AnalysisOptions(BaseModel):
    max_depth: int = Field(default=4, ge=1, le=20)
    include_tests: bool = True
    use_coverage: bool = False


class AnalysisCreate(BaseModel):
    repository_id: UUID
    diff_mode: DiffMode
    commit_from: str | None = None
    commit_to: str | None = None
    base_ref: str | None = None
    head_ref: str | None = None
    include_untracked: bool = False
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="after")
    def validate_refs(self) -> AnalysisCreate:
        if self.diff_mode == DiffMode.COMMIT_RANGE and (not self.commit_from or not self.commit_to):
            raise ValueError("commit_from and commit_to are required for commit_range")
        if self.diff_mode == DiffMode.REFS_COMPARE and (not self.base_ref or not self.head_ref):
            raise ValueError("base_ref and head_ref are required for refs_compare")
        return self


class AnalysisAccepted(BaseModel):
    analysis_id: UUID
    repository_id: UUID
    status: AnalysisStatus
    created_at: datetime


class AnalysisSummary(BaseModel):
    changed_files: int = Field(default=0, ge=0)
    changed_python_files: int = Field(default=0, ge=0)
    changed_symbols: int = Field(default=0, ge=0)
    unmapped_changes: int = Field(default=0, ge=0)
    impacted_symbols: int = Field(default=0, ge=0)
    top_impacts: int = Field(default=0, ge=0)
    high_confidence_impacts: int = Field(default=0, ge=0)
    impacted_tests: int = Field(default=0, ge=0)
    propagation_paths: int = Field(default=0, ge=0)
    recommended_tests: int = Field(default=0, ge=0)
    skipped_files: int = Field(default=0, ge=0)
    parse_failures: int = Field(default=0, ge=0)
    scanned_files: int = Field(default=0, ge=0)
    parsed_files: int = Field(default=0, ge=0)
    parse_failed_files: int = Field(default=0, ge=0)
    extracted_symbols: int = Field(default=0, ge=0)
    extracted_edges: int = Field(default=0, ge=0)


class ChangedSymbolItem(BaseModel):
    symbol_id: UUID
    symbol_key: str
    symbol_name: str
    symbol_kind: SymbolKind
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    change_type: FileChangeType


class ImpactedSymbolItem(BaseModel):
    symbol_id: UUID
    source_symbol_id: UUID
    source_symbol_key: str
    symbol_key: str
    symbol_name: str
    symbol_kind: SymbolKind
    file_path: str
    hop_count: int = Field(ge=1)
    impact_reason: str
    impact_path: list[str]
    edge_types: list[EdgeType]
    is_test: bool


class EvidenceItem(BaseModel):
    edge_type: EdgeType | Literal["changed_symbol"]
    file_path: str | None = None
    line: int | None = Field(default=None, ge=1)
    detail: str


class ReasonsJson(BaseModel):
    source_symbol: str
    matched_from_changed_symbol: str
    edge_types: list[EdgeType]
    path_length: int = Field(ge=0)
    hop_count: int = Field(ge=0)
    merged_paths_count: int = Field(default=1, ge=1)
    is_test_symbol: bool = False
    contributing_changed_symbols: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ImpactItem(BaseModel):
    symbol_id: UUID
    symbol_key: str
    symbol_name: str
    symbol_kind: SymbolKind
    file_path: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: Confidence
    reasons: list[EdgeType | Literal["changed_symbol"]]
    explanation_path: list[str]
    reasons_json: ReasonsJson


class TestSuggestionItem(BaseModel):
    test_symbol_id: UUID
    test_name: str
    file_path: str
    priority: Priority
    reason: str
    coverage_backed: bool


class WarningMessage(BaseModel):
    code: str
    message: str


class AnalysisResult(BaseModel):
    analysis_id: UUID
    repository_id: UUID
    status: AnalysisStatus
    summary: AnalysisSummary
    changed_symbols: list[ChangedSymbolItem] = Field(default_factory=list)
    impacted_symbols: list[ImpactedSymbolItem] = Field(default_factory=list)
    impacts: list[ImpactItem] = Field(default_factory=list)
    test_suggestions: list[TestSuggestionItem] = Field(default_factory=list)
    warnings: list[WarningMessage] = Field(default_factory=list)


class ReportResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"contentMediaType": "text/markdown"})

    content: str
