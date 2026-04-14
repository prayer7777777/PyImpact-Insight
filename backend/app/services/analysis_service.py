from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.analyzers.python_ast_parser import ParsedPythonFile, PythonAstParser
from app.analyzers.python_scanner import scan_python_files
from app.api import schemas
from app.core.errors import ApiError
from app.db import models
from app.repositories.analysis_artifact_repository import AnalysisArtifactRepository
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.repository_repository import RepositoryRepository


ZERO_SUMMARY = {
    "changed_files": 0,
    "changed_symbols": 0,
    "impacted_symbols": 0,
    "recommended_tests": 0,
    "skipped_files": 0,
    "parse_failures": 0,
    "scanned_files": 0,
    "parsed_files": 0,
    "parse_failed_files": 0,
    "extracted_symbols": 0,
    "extracted_edges": 0,
}

NO_IMPACT_ENGINE_WARNING = {
    "code": "P2_NO_IMPACT_ENGINE",
    "message": "P2 extracts Python files, symbols, and import/contains/inherits edges but does not run Git diff, change mapping, calls analysis, impact propagation, scoring, coverage, or test recommendation.",
}


class AnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.analysis_repository = AnalysisRepository(session)
        self.artifact_repository = AnalysisArtifactRepository(session)
        self.repository_repository = RepositoryRepository(session)

    def create_analysis(self, payload: schemas.AnalysisCreate) -> schemas.AnalysisAccepted:
        repository = self.repository_repository.get_by_id(str(payload.repository_id))
        if repository is None:
            raise ApiError(
                "INVALID_REQUEST",
                "repository_id does not refer to a registered repository.",
                status_code=404,
                details={"repository_id": str(payload.repository_id)},
            )

        created_at = datetime.now(UTC)
        analysis = self.analysis_repository.create(
            repository_id=str(payload.repository_id),
            diff_mode=payload.diff_mode.value,
            commit_from=payload.commit_from,
            commit_to=payload.commit_to,
            base_ref=payload.base_ref,
            head_ref=payload.head_ref,
            include_untracked=payload.include_untracked,
            options=payload.options.model_dump(),
            status=schemas.AnalysisStatus.PENDING.value,
            created_at=created_at,
            summary=ZERO_SUMMARY.copy(),
            warnings=[],
        )
        accepted = schemas.AnalysisAccepted(
            analysis_id=analysis.analysis_id,
            repository_id=analysis.repository_id,
            status=schemas.AnalysisStatus.PENDING,
            created_at=analysis.created_at,
        )

        try:
            running_at = datetime.now(UTC)
            analysis = self.analysis_repository.set_status(
                analysis,
                status=schemas.AnalysisStatus.RUNNING.value,
                started_at=running_at,
            )
            summary, warnings = self._extract_repository_symbols(repository, analysis)
            self.analysis_repository.set_status(
                analysis,
                status=schemas.AnalysisStatus.COMPLETED.value,
                finished_at=datetime.now(UTC),
                summary=summary,
                warnings=warnings,
            )
        except Exception as exc:
            self.session.rollback()
            self.analysis_repository.set_status(
                analysis,
                status=schemas.AnalysisStatus.FAILED.value,
                finished_at=datetime.now(UTC),
                error_code="ANALYSIS_FAILED",
                error_message=str(exc),
            )
            raise

        return accepted

    def _extract_repository_symbols(
        self, repository: models.Repository, analysis: models.Analysis
    ) -> tuple[dict, list[dict]]:
        parser = PythonAstParser()
        paths = scan_python_files(repository.repo_path)
        parsed_files = [parser.parse_file(repository.repo_path, path) for path in paths]

        now = datetime.now(UTC)
        symbol_by_qualname: dict[str, models.Symbol] = {}
        module_symbol_by_name: dict[str, models.Symbol] = {}
        class_symbols_by_name: dict[str, list[models.Symbol]] = {}

        for parsed in parsed_files:
            code_file = self.artifact_repository.create_code_file(
                repository_id=repository.repository_id,
                analysis_id=analysis.analysis_id,
                path=parsed.relative_path,
                module_name=parsed.module_name,
                content_hash=parsed.content_hash,
                parse_status=parsed.parse_status.value,
                error_message=parsed.error_message,
                created_at=now,
            )
            if parsed.parse_status != schemas.ParseStatus.PARSED:
                continue

            for parsed_symbol in parsed.symbols:
                symbol = self.artifact_repository.create_symbol(
                    analysis_id=analysis.analysis_id,
                    file_id=code_file.file_id,
                    kind=parsed_symbol.kind.value,
                    qualname=parsed_symbol.qualname,
                    name=parsed_symbol.name,
                    start_line=parsed_symbol.start_line,
                    end_line=parsed_symbol.end_line,
                    created_at=now,
                )
                symbol_by_qualname[parsed_symbol.qualname] = symbol
                if parsed_symbol.kind == schemas.SymbolKind.MODULE:
                    module_symbol_by_name[parsed.module_name] = symbol
                if parsed_symbol.kind == schemas.SymbolKind.CLASS:
                    class_symbols_by_name.setdefault(parsed_symbol.name, []).append(symbol)

        created_edges = self._persist_edges(
            analysis_id=analysis.analysis_id,
            parsed_files=parsed_files,
            symbol_by_qualname=symbol_by_qualname,
            module_symbol_by_name=module_symbol_by_name,
            class_symbols_by_name=class_symbols_by_name,
            created_at=now,
        )
        self.artifact_repository.commit()

        parse_failed_files = sum(
            1 for parsed in parsed_files if parsed.parse_status == schemas.ParseStatus.PARSE_FAILED
        )
        summary = ZERO_SUMMARY.copy()
        summary.update(
            {
                "parse_failures": parse_failed_files,
                "scanned_files": len(parsed_files),
                "parsed_files": len(parsed_files) - parse_failed_files,
                "parse_failed_files": parse_failed_files,
                "extracted_symbols": len(symbol_by_qualname),
                "extracted_edges": created_edges,
            }
        )
        warnings = [NO_IMPACT_ENGINE_WARNING.copy()]
        if parse_failed_files:
            failed_paths = [
                parsed.relative_path
                for parsed in parsed_files
                if parsed.parse_status == schemas.ParseStatus.PARSE_FAILED
            ]
            warnings.append(
                {
                    "code": "PYTHON_PARSE_FAILED",
                    "message": f"{parse_failed_files} Python file(s) failed to parse: {', '.join(failed_paths)}",
                }
            )
        return summary, warnings

    def _persist_edges(
        self,
        *,
        analysis_id: str,
        parsed_files: list[ParsedPythonFile],
        symbol_by_qualname: dict[str, models.Symbol],
        module_symbol_by_name: dict[str, models.Symbol],
        class_symbols_by_name: dict[str, list[models.Symbol]],
        created_at: datetime,
    ) -> int:
        edge_keys: set[tuple[str, str, str]] = set()
        created_edges = 0

        for parsed in parsed_files:
            for edge_ref in parsed.contains_edges:
                created_edges += self._create_edge_if_resolved(
                    analysis_id=analysis_id,
                    edge_type=edge_ref.edge_type.value,
                    src=symbol_by_qualname.get(edge_ref.src_qualname),
                    dst=symbol_by_qualname.get(edge_ref.dst_qualname),
                    weight=edge_ref.weight,
                    evidence=edge_ref.evidence,
                    edge_keys=edge_keys,
                    created_at=created_at,
                )

            for import_ref in parsed.imports:
                target = self._resolve_import_target(import_ref.candidates, module_symbol_by_name)
                if target is None:
                    continue
                created_edges += self._create_edge_if_resolved(
                    analysis_id=analysis_id,
                    edge_type=schemas.EdgeType.IMPORTS.value,
                    src=symbol_by_qualname.get(import_ref.src_qualname),
                    dst=target,
                    weight=0.80,
                    evidence={
                        "edge_type": schemas.EdgeType.IMPORTS.value,
                        "file_path": parsed.relative_path,
                        "line": import_ref.line,
                        "detail": import_ref.detail,
                    },
                    edge_keys=edge_keys,
                    created_at=created_at,
                )

            for inherit_ref in parsed.inherits:
                target = self._resolve_inherit_target(inherit_ref.base_name, class_symbols_by_name)
                if target is None:
                    continue
                created_edges += self._create_edge_if_resolved(
                    analysis_id=analysis_id,
                    edge_type=schemas.EdgeType.INHERITS.value,
                    src=symbol_by_qualname.get(inherit_ref.src_qualname),
                    dst=target,
                    weight=0.75,
                    evidence={
                        "edge_type": schemas.EdgeType.INHERITS.value,
                        "file_path": parsed.relative_path,
                        "line": inherit_ref.line,
                        "detail": inherit_ref.detail,
                    },
                    edge_keys=edge_keys,
                    created_at=created_at,
                )

        return created_edges

    def _create_edge_if_resolved(
        self,
        *,
        analysis_id: str,
        edge_type: str,
        src: models.Symbol | None,
        dst: models.Symbol | None,
        weight: float,
        evidence: dict,
        edge_keys: set[tuple[str, str, str]],
        created_at: datetime,
    ) -> int:
        if src is None or dst is None:
            return 0
        key = (src.symbol_id, dst.symbol_id, edge_type)
        if key in edge_keys:
            return 0
        edge_keys.add(key)
        self.artifact_repository.create_edge(
            analysis_id=analysis_id,
            src_symbol_id=src.symbol_id,
            dst_symbol_id=dst.symbol_id,
            edge_type=edge_type,
            weight=weight,
            evidence=evidence,
            created_at=created_at,
        )
        return 1

    def _resolve_import_target(
        self,
        candidates: tuple[str, ...],
        module_symbol_by_name: dict[str, models.Symbol],
    ) -> models.Symbol | None:
        for candidate in candidates:
            if candidate in module_symbol_by_name:
                return module_symbol_by_name[candidate]
        return None

    def _resolve_inherit_target(
        self,
        base_name: str,
        class_symbols_by_name: dict[str, list[models.Symbol]],
    ) -> models.Symbol | None:
        short_name = base_name.rsplit(".", maxsplit=1)[-1]
        matches = class_symbols_by_name.get(short_name, [])
        if len(matches) == 1:
            return matches[0]
        return None

    def get_analysis(self, analysis_id: UUID) -> schemas.AnalysisResult:
        analysis = self._get_analysis_record(analysis_id)
        return self._to_result_schema(analysis)

    def get_report(self, analysis_id: UUID) -> str:
        analysis = self._get_analysis_record(analysis_id)
        repository = self.repository_repository.get_by_id(analysis.repository_id)
        result = self._to_result_schema(analysis)
        repo_name = repository.name if repository is not None else "unknown"
        repo_path = repository.repo_path if repository is not None else "unknown"
        main_branch = repository.main_branch if repository is not None else "unknown"

        lines = [
            "# Change Impact Analysis Report",
            "",
            f"- Analysis ID: `{result.analysis_id}`",
            f"- Repository ID: `{result.repository_id}`",
            f"- Repository: `{repo_name}`",
            f"- Repository path: `{repo_path}`",
            f"- Main branch: `{main_branch}`",
            f"- Status: `{result.status.value}`",
            f"- Diff mode: `{analysis.diff_mode}`",
            f"- Created at: `{analysis.created_at.isoformat()}`",
            f"- Started at: `{analysis.started_at.isoformat() if analysis.started_at else 'not started'}`",
            f"- Finished at: `{analysis.finished_at.isoformat() if analysis.finished_at else 'not finished'}`",
            "",
            "## Summary",
            "",
            f"- Changed files: {result.summary.changed_files}",
            f"- Changed symbols: {result.summary.changed_symbols}",
            f"- Impacted symbols: {result.summary.impacted_symbols}",
            f"- Recommended tests: {result.summary.recommended_tests}",
            f"- Skipped files: {result.summary.skipped_files}",
            f"- Parse failures: {result.summary.parse_failures}",
            f"- Scanned Python files: {result.summary.scanned_files}",
            f"- Parsed Python files: {result.summary.parsed_files}",
            f"- Parse-failed Python files: {result.summary.parse_failed_files}",
            f"- Extracted symbols: {result.summary.extracted_symbols}",
            f"- Extracted edges: {result.summary.extracted_edges}",
            "",
            "## Limitations",
            "",
            "- P2 scans Python files and extracts module/class/function/method/test symbols.",
            "- P2 extracts contains, imports, and simple inheritance edges.",
            "- P2 does not run Git diff, change mapping, calls analysis, impact propagation, scoring, coverage, or test recommendation.",
            "",
        ]
        if result.warnings:
            lines.extend(["## Warnings", ""])
            lines.extend(f"- `{warning.code}`: {warning.message}" for warning in result.warnings)
            lines.append("")
        return "\n".join(lines)

    def _get_analysis_record(self, analysis_id: UUID) -> models.Analysis:
        analysis = self.analysis_repository.get_by_id(str(analysis_id))
        if analysis is None:
            raise ApiError(
                "ANALYSIS_NOT_FOUND",
                "The requested analysis ID does not exist.",
                status_code=404,
                details={"analysis_id": str(analysis_id)},
            )
        return analysis

    def _to_result_schema(self, analysis: models.Analysis) -> schemas.AnalysisResult:
        impacts = [
            schemas.ImpactItem(
                symbol_id=impact.symbol_id,
                symbol_key=impact.symbol_key,
                symbol_name=impact.symbol_name,
                symbol_kind=impact.symbol_kind,
                file_path=impact.file_path,
                score=impact.score,
                confidence=impact.confidence,
                reasons=impact.reasons,
                explanation_path=impact.explanation_path,
                reasons_json=impact.reasons_json,
            )
            for impact in self.analysis_repository.list_impacts(analysis.analysis_id)
        ]
        test_suggestions = [
            schemas.TestSuggestionItem(
                test_symbol_id=item.test_symbol_id,
                test_name=item.test_name,
                file_path=item.file_path,
                priority=item.priority,
                reason=item.reason,
                coverage_backed=item.coverage_backed,
            )
            for item in self.analysis_repository.list_test_recommendations(analysis.analysis_id)
        ]
        warning_adapter = TypeAdapter(list[schemas.WarningMessage])
        return schemas.AnalysisResult(
            analysis_id=analysis.analysis_id,
            repository_id=analysis.repository_id,
            status=schemas.AnalysisStatus(analysis.status),
            summary=schemas.AnalysisSummary(**(analysis.summary or ZERO_SUMMARY)),
            changed_symbols=[],
            impacts=impacts,
            test_suggestions=test_suggestions,
            warnings=warning_adapter.validate_python(analysis.warnings or []),
        )
