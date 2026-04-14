from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from app.analyzers.git_diff import ChangedFile, ChangedLineRange, GitDiffError, GitDiffReader
from app.analyzers.impact_propagation import (
    ChangedSeed as PropagationChangedSeed,
    EdgeLink as PropagationEdgeLink,
    SymbolNode as PropagationSymbolNode,
    propagate_impacts,
)
from app.analyzers.impact_scoring import (
    ChangedSeed as ScoringChangedSeed,
    EdgeLink as ScoringEdgeLink,
    SymbolNode as ScoringSymbolNode,
    score_impacts,
)
from app.analyzers.python_ast_parser import ParsedPythonFile, PythonAstParser
from app.analyzers.python_scanner import scan_python_files
from app.api import schemas
from app.core.errors import ApiError
from app.db import models
from app.repositories.analysis_artifact_repository import AnalysisArtifactRepository
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.change_repository import ChangeRepository
from app.repositories.impact_repository import ImpactRepository
from app.repositories.repository_repository import RepositoryRepository


ZERO_SUMMARY = {
    "changed_files": 0,
    "changed_python_files": 0,
    "changed_symbols": 0,
    "unmapped_changes": 0,
    "impacted_symbols": 0,
    "top_impacts": 0,
    "high_confidence_impacts": 0,
    "impacted_tests": 0,
    "propagation_paths": 0,
    "recommended_tests": 0,
    "skipped_files": 0,
    "parse_failures": 0,
    "scanned_files": 0,
    "parsed_files": 0,
    "parse_failed_files": 0,
    "extracted_symbols": 0,
    "extracted_edges": 0,
}

LIMITED_IMPACT_ENGINE_WARNING = {
    "code": "P5_LIMITED_IMPACT_ENGINE",
    "message": "P5 scores changed and structurally propagated symbols through imports, inheritance, and containment edges with deterministic hop decay, but it does not use calls, coverage, test recommendation, or historical snapshot graphs.",
}


class AnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.analysis_repository = AnalysisRepository(session)
        self.artifact_repository = AnalysisArtifactRepository(session)
        self.change_repository = ChangeRepository(session)
        self.impact_repository = ImpactRepository(session)
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
            summary, warnings = self._run_repository_analysis(repository, analysis)
            self.analysis_repository.set_status(
                analysis,
                status=schemas.AnalysisStatus.COMPLETED.value,
                finished_at=datetime.now(UTC),
                summary=summary,
                warnings=warnings,
            )
        except GitDiffError as exc:
            self.session.rollback()
            self.analysis_repository.set_status(
                analysis,
                status=schemas.AnalysisStatus.FAILED.value,
                finished_at=datetime.now(UTC),
                error_code=exc.code,
                error_message=exc.message,
            )
            raise ApiError(exc.code, exc.message, details=exc.details) from exc
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

    def _run_repository_analysis(
        self, repository: models.Repository, analysis: models.Analysis
    ) -> tuple[dict, list[dict]]:
        parser = PythonAstParser()
        diff_reader = GitDiffReader()
        paths = scan_python_files(repository.repo_path)
        parsed_files = [parser.parse_file(repository.repo_path, path) for path in paths]

        now = datetime.now(UTC)
        code_file_by_path: dict[str, models.CodeFile] = {}
        symbols_by_file_path: dict[str, list[models.Symbol]] = {}
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
            code_file_by_path[parsed.relative_path] = code_file
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
                symbols_by_file_path.setdefault(parsed.relative_path, []).append(symbol)
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

        diff_result = diff_reader.read(
            repo_path=repository.repo_path,
            diff_mode=schemas.DiffMode(analysis.diff_mode),
            commit_from=analysis.commit_from,
            commit_to=analysis.commit_to,
            base_ref=analysis.base_ref,
            head_ref=analysis.head_ref,
            include_untracked=analysis.include_untracked,
        )
        change_summary = self._persist_change_mapping(
            analysis_id=analysis.analysis_id,
            changed_files=diff_result.files,
            code_file_by_path=code_file_by_path,
            symbols_by_file_path=symbols_by_file_path,
            created_at=now,
        )
        impact_candidate_summary = self._persist_impact_candidates(
            analysis_id=analysis.analysis_id,
            max_depth=int((analysis.options or {}).get("max_depth", 4)),
            created_at=now,
        )
        final_impact_summary = self._persist_final_impacts(
            analysis_id=analysis.analysis_id,
            max_depth=int((analysis.options or {}).get("max_depth", 4)),
        )

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
        summary.update(change_summary)
        summary.update(impact_candidate_summary)
        summary.update(final_impact_summary)
        warnings = [LIMITED_IMPACT_ENGINE_WARNING.copy()]
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

    def _persist_change_mapping(
        self,
        *,
        analysis_id: str,
        changed_files: list[ChangedFile],
        code_file_by_path: dict[str, models.CodeFile],
        symbols_by_file_path: dict[str, list[models.Symbol]],
        created_at: datetime,
    ) -> dict[str, int]:
        created_changed_symbols: set[str] = set()
        unmapped_changes = 0
        skipped_files = 0

        for changed_file in changed_files:
            if not changed_file.is_python or changed_file.is_binary:
                skipped_files += 1
            code_file = code_file_by_path.get(changed_file.path)
            symbols = symbols_by_file_path.get(changed_file.path, [])
            ranges: list[ChangedLineRange | None] = (
                list(changed_file.line_ranges) if changed_file.line_ranges else [None]
            )

            for line_range in ranges:
                mapped_symbols = self._symbols_for_changed_range(symbols, line_range)
                mapped_symbol = self._primary_mapped_symbol(mapped_symbols)
                should_record_unmapped = (
                    changed_file.is_python
                    and not changed_file.is_binary
                    and line_range is not None
                    and mapped_symbol is None
                )
                if should_record_unmapped:
                    unmapped_changes += 1

                self.change_repository.create_change_span(
                    analysis_id=analysis_id,
                    file_id=code_file.file_id if code_file is not None else None,
                    mapped_symbol_id=mapped_symbol.symbol_id if mapped_symbol is not None else None,
                    path=changed_file.path,
                    old_path=changed_file.old_path,
                    change_type=changed_file.change_type.value,
                    start_line=line_range.start_line if line_range is not None else None,
                    end_line=line_range.end_line if line_range is not None else None,
                    is_python=changed_file.is_python,
                    is_binary=changed_file.is_binary,
                    is_unmapped=should_record_unmapped,
                    created_at=created_at,
                )

                for symbol in mapped_symbols:
                    if symbol.symbol_id in created_changed_symbols:
                        continue
                    created_changed_symbols.add(symbol.symbol_id)
                    self.change_repository.create_changed_symbol(
                        analysis_id=analysis_id,
                        symbol_id=symbol.symbol_id,
                        file_id=symbol.file_id,
                        symbol_key=f"{changed_file.path}::{symbol.qualname}",
                        symbol_name=symbol.name,
                        symbol_kind=symbol.kind,
                        file_path=changed_file.path,
                        change_type=changed_file.change_type.value,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        is_module_level=symbol.kind == schemas.SymbolKind.MODULE.value,
                        created_at=created_at,
                    )

        return {
            "changed_files": len(changed_files),
            "changed_python_files": sum(1 for changed_file in changed_files if changed_file.is_python),
            "changed_symbols": len(created_changed_symbols),
            "unmapped_changes": unmapped_changes,
            "skipped_files": skipped_files,
        }

    def _persist_impact_candidates(
        self,
        *,
        analysis_id: str,
        max_depth: int,
        created_at: datetime,
    ) -> dict[str, int]:
        changed_symbols = self.change_repository.list_changed_symbols(analysis_id)
        if not changed_symbols:
            return {
                "impacted_symbols": 0,
                "impacted_tests": 0,
                "propagation_paths": 0,
            }

        code_files = self.artifact_repository.list_code_files(analysis_id)
        code_file_by_id = {code_file.file_id: code_file for code_file in code_files}
        symbols = self.artifact_repository.list_symbols(analysis_id)
        symbol_nodes = [
            PropagationSymbolNode(
                symbol_id=symbol.symbol_id,
                symbol_key=self._symbol_key(symbol, code_file_by_id),
                symbol_name=symbol.name,
                symbol_kind=symbol.kind,
                file_id=symbol.file_id,
                file_path=code_file_by_id[symbol.file_id].path,
            )
            for symbol in symbols
            if symbol.file_id in code_file_by_id
        ]
        edge_links = [
            PropagationEdgeLink(
                src_symbol_id=edge.src_symbol_id,
                dst_symbol_id=edge.dst_symbol_id,
                edge_type=edge.edge_type,
            )
            for edge in self.artifact_repository.list_edges(analysis_id)
        ]
        candidates = propagate_impacts(
            changed_symbols=[
                PropagationChangedSeed(
                    symbol_id=changed_symbol.symbol_id,
                    symbol_key=changed_symbol.symbol_key,
                    symbol_kind=changed_symbol.symbol_kind,
                )
                for changed_symbol in changed_symbols
            ],
            symbols=symbol_nodes,
            edges=edge_links,
            max_depth=max_depth,
        )

        for candidate in candidates:
            self.impact_repository.create_impacted_symbol(
                analysis_id=analysis_id,
                source_symbol_id=candidate.source_symbol_id,
                symbol_id=candidate.symbol_id,
                file_id=candidate.file_id,
                source_symbol_key=candidate.source_symbol_key,
                symbol_key=candidate.symbol_key,
                symbol_name=candidate.symbol_name,
                symbol_kind=candidate.symbol_kind,
                file_path=candidate.file_path,
                hop_count=candidate.hop_count,
                impact_reason=candidate.impact_reason,
                impact_path=list(candidate.impact_path),
                edge_types=list(candidate.edge_types),
                is_test=candidate.is_test,
                created_at=created_at,
            )

        return {
            "impacted_symbols": len(candidates),
            "impacted_tests": sum(1 for candidate in candidates if candidate.is_test),
            "propagation_paths": len(candidates),
        }

    def _persist_final_impacts(
        self,
        *,
        analysis_id: str,
        max_depth: int,
    ) -> dict[str, int]:
        changed_symbols = self.change_repository.list_changed_symbols(analysis_id)
        if not changed_symbols:
            return {
                "top_impacts": 0,
                "high_confidence_impacts": 0,
                "impacted_tests": 0,
            }

        code_files = self.artifact_repository.list_code_files(analysis_id)
        code_file_by_id = {code_file.file_id: code_file for code_file in code_files}
        symbols = self.artifact_repository.list_symbols(analysis_id)
        symbol_nodes = [
            ScoringSymbolNode(
                symbol_id=symbol.symbol_id,
                symbol_key=self._symbol_key(symbol, code_file_by_id),
                symbol_name=symbol.name,
                symbol_kind=symbol.kind,
                file_id=symbol.file_id,
                file_path=code_file_by_id[symbol.file_id].path,
            )
            for symbol in symbols
            if symbol.file_id in code_file_by_id
        ]
        edge_links = [
            ScoringEdgeLink(
                src_symbol_id=edge.src_symbol_id,
                dst_symbol_id=edge.dst_symbol_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                evidence=edge.evidence or {},
            )
            for edge in self.artifact_repository.list_edges(analysis_id)
        ]
        impacts = score_impacts(
            changed_symbols=[
                ScoringChangedSeed(
                    symbol_id=changed_symbol.symbol_id,
                    symbol_key=changed_symbol.symbol_key,
                    symbol_name=changed_symbol.symbol_name,
                    symbol_kind=changed_symbol.symbol_kind,
                    file_path=changed_symbol.file_path,
                    start_line=changed_symbol.start_line,
                    end_line=changed_symbol.end_line,
                    is_module_level=changed_symbol.is_module_level,
                )
                for changed_symbol in changed_symbols
            ],
            symbols=symbol_nodes,
            edges=edge_links,
            max_depth=max_depth,
        )

        for impact in impacts:
            self.impact_repository.create_impact(
                analysis_id=analysis_id,
                symbol_id=impact.symbol_id,
                symbol_key=impact.symbol_key,
                symbol_name=impact.symbol_name,
                symbol_kind=impact.symbol_kind,
                file_path=impact.file_path,
                score=impact.score,
                confidence=impact.confidence,
                reasons=list(impact.reasons),
                explanation_path=list(impact.explanation_path),
                reasons_json=impact.reasons_json,
            )

        return {
            "top_impacts": len(impacts),
            "high_confidence_impacts": sum(
                1 for impact in impacts if impact.confidence == schemas.Confidence.HIGH.value
            ),
            "impacted_tests": sum(
                1
                for impact in impacts
                if impact.symbol_kind
                in {
                    schemas.SymbolKind.TEST_FUNCTION.value,
                    schemas.SymbolKind.TEST_METHOD.value,
                }
            ),
        }

    def _symbol_key(self, symbol: models.Symbol, code_file_by_id: dict[str, models.CodeFile]) -> str:
        return f"{code_file_by_id[symbol.file_id].path}::{symbol.qualname}"

    def _symbols_for_changed_range(
        self, symbols: list[models.Symbol], line_range: ChangedLineRange | None
    ) -> list[models.Symbol]:
        if line_range is None:
            return []

        module_symbol = next(
            (symbol for symbol in symbols if symbol.kind == schemas.SymbolKind.MODULE.value),
            None,
        )
        mapped_by_id: dict[str, models.Symbol] = {}
        if module_symbol is not None and self._line_range_overlaps_symbol(line_range, module_symbol):
            mapped_by_id[module_symbol.symbol_id] = module_symbol

        for line_number in range(line_range.start_line, line_range.end_line + 1):
            candidates = [
                symbol
                for symbol in symbols
                if symbol.kind != schemas.SymbolKind.MODULE.value
                and symbol.start_line <= line_number <= symbol.end_line
            ]
            if not candidates:
                continue
            innermost = min(
                candidates,
                key=lambda symbol: (
                    symbol.end_line - symbol.start_line,
                    -(symbol.start_line),
                ),
            )
            mapped_by_id[innermost.symbol_id] = innermost

        return sorted(
            mapped_by_id.values(),
            key=lambda symbol: (
                symbol.kind != schemas.SymbolKind.MODULE.value,
                symbol.start_line,
                symbol.end_line,
                symbol.qualname,
            ),
        )

    def _primary_mapped_symbol(self, symbols: list[models.Symbol]) -> models.Symbol | None:
        non_module_symbols = [
            symbol for symbol in symbols if symbol.kind != schemas.SymbolKind.MODULE.value
        ]
        if non_module_symbols:
            return min(
                non_module_symbols,
                key=lambda symbol: (
                    symbol.end_line - symbol.start_line,
                    -(symbol.start_line),
                ),
            )
        if symbols:
            return symbols[0]
        return None

    def _line_range_overlaps_symbol(
        self, line_range: ChangedLineRange, symbol: models.Symbol
    ) -> bool:
        return line_range.start_line <= symbol.end_line and line_range.end_line >= symbol.start_line

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
            f"- Changed Python files: {result.summary.changed_python_files}",
            f"- Changed symbols: {result.summary.changed_symbols}",
            f"- Unmapped changes: {result.summary.unmapped_changes}",
            f"- Impacted symbols: {result.summary.impacted_symbols}",
            f"- Top impacts: {result.summary.top_impacts}",
            f"- High-confidence impacts: {result.summary.high_confidence_impacts}",
            f"- Impacted tests: {result.summary.impacted_tests}",
            f"- Propagation paths: {result.summary.propagation_paths}",
            f"- Recommended tests: {result.summary.recommended_tests}",
            f"- Skipped files: {result.summary.skipped_files}",
            f"- Parse failures: {result.summary.parse_failures}",
            f"- Scanned Python files: {result.summary.scanned_files}",
            f"- Parsed Python files: {result.summary.parsed_files}",
            f"- Parse-failed Python files: {result.summary.parse_failed_files}",
            f"- Extracted symbols: {result.summary.extracted_symbols}",
            f"- Extracted edges: {result.summary.extracted_edges}",
            "",
            "## Changed Symbols",
            "",
        ]
        if result.changed_symbols:
            lines.extend(
                f"- `{item.symbol_key}` ({item.symbol_kind.value}, {item.change_type.value}, "
                f"lines {item.start_line}-{item.end_line})"
                for item in result.changed_symbols
            )
            lines.append("")
        else:
            lines.extend(["- No changed Python symbols were mapped.", ""])
        lines.extend(["## Impacted Symbol Candidates", ""])
        if result.impacted_symbols:
            lines.extend(
                f"- `{item.symbol_key}` from `{item.source_symbol_key}` "
                f"({item.impact_reason}, hops {item.hop_count})"
                for item in result.impacted_symbols
            )
            lines.append("")
        else:
            lines.extend(["- No impacted symbol candidates were generated.", ""])
        lines.extend(["## Final Impacts", ""])
        if result.impacts:
            lines.extend(
                f"- `{item.symbol_key}` (score {item.score:.4f}, {item.confidence.value}, "
                f"paths {item.reasons_json.merged_paths_count})"
                for item in result.impacts[:10]
            )
            lines.append("")
        else:
            lines.extend(["- No final impacts were scored.", ""])
        lines.extend(
            [
                "## Limitations",
                "",
                "- P5 scores only imports, inheritance, and containment-based propagation.",
                "- P5 does not run calls analysis, coverage-backed scoring, or test recommendation.",
                "- P5 scores against the current working-tree symbol graph rather than a historical snapshot graph.",
                "",
            ]
        )
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
        changed_symbols = [
            schemas.ChangedSymbolItem(
                symbol_id=item.symbol_id,
                symbol_key=item.symbol_key,
                symbol_name=item.symbol_name,
                symbol_kind=item.symbol_kind,
                file_path=item.file_path,
                start_line=item.start_line,
                end_line=item.end_line,
                change_type=item.change_type,
            )
            for item in self.change_repository.list_changed_symbols(analysis.analysis_id)
        ]
        impacted_symbols = [
            schemas.ImpactedSymbolItem(
                symbol_id=item.symbol_id,
                source_symbol_id=item.source_symbol_id,
                source_symbol_key=item.source_symbol_key,
                symbol_key=item.symbol_key,
                symbol_name=item.symbol_name,
                symbol_kind=item.symbol_kind,
                file_path=item.file_path,
                hop_count=item.hop_count,
                impact_reason=item.impact_reason,
                impact_path=item.impact_path,
                edge_types=item.edge_types,
                is_test=item.is_test,
            )
            for item in self.impact_repository.list_impacted_symbols(analysis.analysis_id)
        ]
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
            for impact in self.impact_repository.list_impacts(analysis.analysis_id)
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
            changed_symbols=changed_symbols,
            impacted_symbols=impacted_symbols,
            impacts=impacts,
            test_suggestions=test_suggestions,
            warnings=warning_adapter.validate_python(analysis.warnings or []),
        )
