from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.api import schemas


NAME_PROXIMITY_FLOOR = 0.25
NAME_PROXIMITY_CEILING = 0.60
NAME_PROXIMITY_MULTIPLIER = 0.55
STATIC_TEST_EDGE_WEIGHT = 0.90
COVERAGE_TEST_BONUS = 0.15
TEST_SYMBOL_KINDS = {
    schemas.SymbolKind.TEST_FUNCTION.value,
    schemas.SymbolKind.TEST_METHOD.value,
}


@dataclass(frozen=True)
class TestSymbolNode:
    symbol_id: str
    symbol_key: str
    test_name: str
    symbol_name: str
    symbol_kind: str
    file_path: str


@dataclass(frozen=True)
class ImpactNode:
    symbol_id: str
    symbol_key: str
    symbol_name: str
    symbol_kind: str
    file_path: str
    score: float
    confidence: str
    explanation_path: tuple[str, ...]
    hop_count: int
    merged_paths_count: int
    reasons_json: dict[str, object]


@dataclass(frozen=True)
class TestEdgeNode:
    src_test_symbol_id: str
    dst_symbol_id: str
    dst_symbol_kind: str
    dst_file_path: str
    weight: float
    coverage_backed: bool
    evidence: dict[str, object]


@dataclass(frozen=True)
class _RecommendationCandidate:
    test_symbol_id: str
    test_name: str
    file_path: str
    score: float
    confidence: str
    priority: str
    reason: str
    reasons_json: dict[str, object]
    coverage_backed: bool
    relation_type: str
    hop_count: int
    is_direct_test_hit: bool
    matched_impacted_symbol: str
    evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ScoredTestRecommendation:
    test_symbol_id: str
    test_name: str
    file_path: str
    score: float
    confidence: str
    priority: str
    reason: str
    reasons_json: dict[str, object]
    coverage_backed: bool


def recommend_tests(
    *,
    test_symbols: list[TestSymbolNode],
    impacts: list[ImpactNode],
    test_edges: list[TestEdgeNode],
) -> list[ScoredTestRecommendation]:
    if not test_symbols or not impacts:
        return []

    test_symbol_by_id = {test_symbol.symbol_id: test_symbol for test_symbol in test_symbols}
    candidates_by_test_symbol_id: dict[str, list[_RecommendationCandidate]] = {}
    edges_by_target_symbol_id: dict[str, list[TestEdgeNode]] = {}
    module_edges_by_file_path: dict[str, list[TestEdgeNode]] = {}

    for edge in test_edges:
        edges_by_target_symbol_id.setdefault(edge.dst_symbol_id, []).append(edge)
        if edge.dst_symbol_kind == schemas.SymbolKind.MODULE.value:
            module_edges_by_file_path.setdefault(edge.dst_file_path, []).append(edge)

    for impact in impacts:
        if impact.symbol_kind in TEST_SYMBOL_KINDS:
            direct_test_symbol = test_symbol_by_id.get(impact.symbol_id)
            if direct_test_symbol is not None:
                _add_candidate(
                    candidates_by_test_symbol_id,
                    _direct_test_hit_candidate(direct_test_symbol, impact),
                )

        for edge in edges_by_target_symbol_id.get(impact.symbol_id, []):
            test_symbol = test_symbol_by_id.get(edge.src_test_symbol_id)
            if test_symbol is None:
                continue
            _add_candidate(
                candidates_by_test_symbol_id,
                _edge_candidate(
                    test_symbol=test_symbol,
                    impact=impact,
                    edge=edge,
                    relation_type="coverage_tests_edge"
                    if edge.coverage_backed
                    else "tests_edge_exact",
                    exact_match=True,
                ),
            )

        for edge in module_edges_by_file_path.get(impact.file_path, []):
            if edge.dst_symbol_id == impact.symbol_id:
                continue
            test_symbol = test_symbol_by_id.get(edge.src_test_symbol_id)
            if test_symbol is None:
                continue
            _add_candidate(
                candidates_by_test_symbol_id,
                _edge_candidate(
                    test_symbol=test_symbol,
                    impact=impact,
                    edge=edge,
                    relation_type="coverage_tests_edge"
                    if edge.coverage_backed
                    else "tests_edge_module",
                    exact_match=False,
                ),
            )

        for test_symbol in _matching_test_symbols_by_name_or_path(test_symbols, impact):
            _add_candidate(
                candidates_by_test_symbol_id,
                _name_proximity_candidate(test_symbol, impact),
            )

    recommendations = [
        _merge_candidates(test_symbol_by_id[test_symbol_id], candidates)
        for test_symbol_id, candidates in candidates_by_test_symbol_id.items()
        if candidates
    ]
    return sorted(
        recommendations,
        key=lambda item: (-item.score, item.file_path, item.test_name),
    )


def test_context_aliases(test_symbol: TestSymbolNode) -> set[str]:
    file_path = Path(test_symbol.file_path).as_posix()
    aliases = {test_symbol.symbol_key, test_symbol.test_name, test_symbol.symbol_name}
    if test_symbol.symbol_kind == schemas.SymbolKind.TEST_FUNCTION.value:
        aliases.add(f"{file_path}::{test_symbol.symbol_name}")
    elif test_symbol.symbol_kind == schemas.SymbolKind.TEST_METHOD.value:
        class_name = _class_name_from_test_name(test_symbol.test_name)
        method_name = test_symbol.symbol_name
        aliases.add(f"{file_path}::{class_name}::{method_name}")
    return aliases


def _class_name_from_test_name(test_name: str) -> str:
    parts = test_name.split("::")
    if len(parts) >= 3:
        return parts[-2]
    return "Test"


def _add_candidate(
    candidates_by_test_symbol_id: dict[str, list[_RecommendationCandidate]],
    candidate: _RecommendationCandidate,
) -> None:
    candidates_by_test_symbol_id.setdefault(candidate.test_symbol_id, []).append(candidate)


def _direct_test_hit_candidate(
    test_symbol: TestSymbolNode, impact: ImpactNode
) -> _RecommendationCandidate:
    score = round(impact.score, 4)
    confidence = _confidence_for_score(score)
    return _RecommendationCandidate(
        test_symbol_id=test_symbol.symbol_id,
        test_name=test_symbol.test_name,
        file_path=test_symbol.file_path,
        score=score,
        confidence=confidence,
        priority=_priority_for_confidence(confidence),
        reason="Test symbol is directly impacted by the current analysis graph.",
        reasons_json={
            "whether_coverage_used": False,
            "matched_impacted_symbol": impact.symbol_key,
            "relation_type": "direct_test_hit",
            "hop_count": impact.hop_count,
            "merged_paths_count": max(1, impact.merged_paths_count),
            "is_direct_test_hit": True,
            "evidence": list(_normalize_evidence_list(impact.reasons_json.get("evidence", []))),
        },
        coverage_backed=False,
        relation_type="direct_test_hit",
        hop_count=impact.hop_count,
        is_direct_test_hit=True,
        matched_impacted_symbol=impact.symbol_key,
        evidence=tuple(_normalize_evidence_list(impact.reasons_json.get("evidence", []))),
    )


def _edge_candidate(
    *,
    test_symbol: TestSymbolNode,
    impact: ImpactNode,
    edge: TestEdgeNode,
    relation_type: str,
    exact_match: bool,
) -> _RecommendationCandidate:
    if edge.coverage_backed:
        score = round(min(1.0, impact.score + COVERAGE_TEST_BONUS), 4)
        reason = "Coverage-backed test relation reaches the impacted production symbol."
    else:
        score = round(min(1.0, impact.score * edge.weight), 4)
        reason = (
            "Static test relation reaches the exact impacted production symbol."
            if exact_match
            else "Static test module relation reaches the impacted production file."
        )

    confidence = _confidence_for_score(score)
    evidence = (
        *_normalize_evidence_list(impact.reasons_json.get("evidence", [])),
        _normalize_edge_evidence(edge.evidence),
    )
    return _RecommendationCandidate(
        test_symbol_id=test_symbol.symbol_id,
        test_name=test_symbol.test_name,
        file_path=test_symbol.file_path,
        score=score,
        confidence=confidence,
        priority=_priority_for_confidence(confidence),
        reason=reason,
        reasons_json={
            "whether_coverage_used": edge.coverage_backed,
            "matched_impacted_symbol": impact.symbol_key,
            "relation_type": relation_type,
            "hop_count": impact.hop_count,
            "merged_paths_count": max(1, impact.merged_paths_count),
            "is_direct_test_hit": False,
            "evidence": list(_dedupe_evidence(evidence)),
        },
        coverage_backed=edge.coverage_backed,
        relation_type=relation_type,
        hop_count=impact.hop_count,
        is_direct_test_hit=False,
        matched_impacted_symbol=impact.symbol_key,
        evidence=tuple(_dedupe_evidence(evidence)),
    )


def _name_proximity_candidate(
    test_symbol: TestSymbolNode, impact: ImpactNode
) -> _RecommendationCandidate:
    score = round(
        min(NAME_PROXIMITY_CEILING, max(NAME_PROXIMITY_FLOOR, impact.score * NAME_PROXIMITY_MULTIPLIER)),
        4,
    )
    confidence = _confidence_for_score(score)
    evidence = (
        {
            "edge_type": "name_similarity",
            "file_path": test_symbol.file_path,
            "line": None,
            "detail": (
                f"{test_symbol.test_name} matches {impact.symbol_key} through file or symbol naming proximity"
            ),
        },
    )
    return _RecommendationCandidate(
        test_symbol_id=test_symbol.symbol_id,
        test_name=test_symbol.test_name,
        file_path=test_symbol.file_path,
        score=score,
        confidence=confidence,
        priority=_priority_for_confidence(confidence),
        reason="Conservative naming proximity suggests this test may cover the impacted code.",
        reasons_json={
            "whether_coverage_used": False,
            "matched_impacted_symbol": impact.symbol_key,
            "relation_type": "name_proximity",
            "hop_count": impact.hop_count,
            "merged_paths_count": max(1, impact.merged_paths_count),
            "is_direct_test_hit": False,
            "evidence": list(evidence),
        },
        coverage_backed=False,
        relation_type="name_proximity",
        hop_count=impact.hop_count,
        is_direct_test_hit=False,
        matched_impacted_symbol=impact.symbol_key,
        evidence=evidence,
    )


def _matching_test_symbols_by_name_or_path(
    test_symbols: list[TestSymbolNode],
    impact: ImpactNode,
) -> list[TestSymbolNode]:
    target_stem = Path(impact.file_path).stem
    matches: list[TestSymbolNode] = []
    for test_symbol in test_symbols:
        test_file_name = Path(test_symbol.file_path).name
        file_match = test_file_name == f"test_{target_stem}.py"
        name_match = impact.symbol_name.lower() in test_symbol.test_name.lower()
        if file_match or name_match:
            matches.append(test_symbol)
    return matches


def _merge_candidates(
    test_symbol: TestSymbolNode,
    candidates: list[_RecommendationCandidate],
) -> ScoredTestRecommendation:
    best = min(
        candidates,
        key=lambda item: (
            -item.score,
            not item.coverage_backed,
            not item.is_direct_test_hit,
            item.hop_count,
            item.test_name,
        ),
    )
    merged_evidence = _dedupe_evidence(
        evidence_item
        for candidate in sorted(
            candidates,
            key=lambda item: (
                -item.score,
                not item.coverage_backed,
                not item.is_direct_test_hit,
                item.hop_count,
                item.test_name,
            ),
        )
        for evidence_item in candidate.evidence
    )
    merged_direct = any(candidate.is_direct_test_hit for candidate in candidates)
    merged_coverage = any(candidate.coverage_backed for candidate in candidates)

    return ScoredTestRecommendation(
        test_symbol_id=test_symbol.symbol_id,
        test_name=test_symbol.test_name,
        file_path=test_symbol.file_path,
        score=best.score,
        confidence=best.confidence,
        priority=best.priority,
        reason=best.reason,
        reasons_json={
            "whether_coverage_used": merged_coverage,
            "matched_impacted_symbol": best.matched_impacted_symbol,
            "relation_type": best.relation_type,
            "hop_count": best.hop_count,
            "merged_paths_count": len(candidates),
            "is_direct_test_hit": merged_direct,
            "evidence": merged_evidence,
        },
        coverage_backed=merged_coverage,
    )


def _normalize_evidence_list(raw_items: object) -> list[dict[str, object]]:
    if not isinstance(raw_items, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "edge_type": str(item.get("edge_type", "tests")),
                "file_path": item.get("file_path") if isinstance(item.get("file_path"), str) else None,
                "line": item.get("line") if isinstance(item.get("line"), int) else None,
                "detail": str(item.get("detail", "evidence")),
            }
        )
    return normalized


def _normalize_edge_evidence(raw_item: dict[str, object]) -> dict[str, object]:
    return {
        "edge_type": str(raw_item.get("edge_type", schemas.EdgeType.TESTS.value)),
        "file_path": raw_item.get("file_path") if isinstance(raw_item.get("file_path"), str) else None,
        "line": raw_item.get("line") if isinstance(raw_item.get("line"), int) else None,
        "detail": str(raw_item.get("detail", schemas.EdgeType.TESTS.value)),
    }


def _dedupe_evidence(items: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str | None, int | None, str]] = set()
    deduped: list[dict[str, object]] = []
    for item in items:
        key = (
            str(item.get("edge_type", schemas.EdgeType.TESTS.value)),
            item.get("file_path") if isinstance(item.get("file_path"), str) else None,
            item.get("line") if isinstance(item.get("line"), int) else None,
            str(item.get("detail", schemas.EdgeType.TESTS.value)),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "edge_type": key[0],
                "file_path": key[1],
                "line": key[2],
                "detail": key[3],
            }
        )
    return deduped


def _confidence_for_score(score: float) -> str:
    if score >= 0.75:
        return schemas.Confidence.HIGH.value
    if score >= 0.45:
        return schemas.Confidence.MEDIUM.value
    return schemas.Confidence.LOW.value


def _priority_for_confidence(confidence: str) -> str:
    if confidence == schemas.Confidence.HIGH.value:
        return schemas.Priority.HIGH.value
    if confidence == schemas.Confidence.MEDIUM.value:
        return schemas.Priority.MEDIUM.value
    return schemas.Priority.LOW.value
