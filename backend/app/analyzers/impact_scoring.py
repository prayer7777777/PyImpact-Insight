from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.api import schemas


PATH_DECAY = 0.85
SEED_SCORE = 1.00
MODULE_SEED_SCORE = 0.70
TEST_SYMBOL_BONUS = 0.05
TEST_SYMBOL_KINDS = {
    schemas.SymbolKind.TEST_FUNCTION.value,
    schemas.SymbolKind.TEST_METHOD.value,
}


@dataclass(frozen=True)
class ChangedSeed:
    symbol_id: str
    symbol_key: str
    symbol_name: str
    symbol_kind: str
    file_path: str
    start_line: int
    end_line: int
    is_module_level: bool


@dataclass(frozen=True)
class SymbolNode:
    symbol_id: str
    symbol_key: str
    symbol_name: str
    symbol_kind: str
    file_id: str
    file_path: str


@dataclass(frozen=True)
class EdgeLink:
    src_symbol_id: str
    dst_symbol_id: str
    edge_type: str
    weight: float
    evidence: dict[str, object]


@dataclass(frozen=True)
class _TraversalEdge:
    target_symbol_id: str
    edge_type: str
    weight: float
    evidence: dict[str, object]


@dataclass(frozen=True)
class _PathContribution:
    source_symbol_id: str
    source_symbol_key: str
    source_symbol_kind: str
    target_symbol_id: str
    target_symbol_key: str
    target_symbol_name: str
    target_symbol_kind: str
    target_file_path: str
    impact_path: tuple[str, ...]
    edge_types: tuple[str, ...]
    hop_count: int
    path_score: float
    evidence: tuple[dict[str, object], ...]
    is_test_symbol: bool


@dataclass(frozen=True)
class ScoredImpact:
    symbol_id: str
    symbol_key: str
    symbol_name: str
    symbol_kind: str
    file_path: str
    score: float
    confidence: str
    reasons: tuple[str, ...]
    explanation_path: tuple[str, ...]
    reasons_json: dict[str, object]


def score_impacts(
    *,
    changed_symbols: list[ChangedSeed],
    symbols: list[SymbolNode],
    edges: list[EdgeLink],
    max_depth: int,
) -> list[ScoredImpact]:
    if not changed_symbols:
        return []

    symbol_by_id = {symbol.symbol_id: symbol for symbol in symbols}
    adjacency = _build_adjacency(edges)
    contributions_by_target: dict[str, list[_PathContribution]] = {}

    for seed in sorted(changed_symbols, key=lambda item: item.symbol_key):
        if seed.symbol_id not in symbol_by_id:
            continue
        self_contribution = _self_contribution(seed, symbol_by_id[seed.symbol_id])
        contributions_by_target.setdefault(seed.symbol_id, []).append(self_contribution)
        _collect_path_contributions(
            seed=seed,
            current_symbol_id=seed.symbol_id,
            symbol_by_id=symbol_by_id,
            adjacency=adjacency,
            max_depth=max_depth,
            path=(seed.symbol_key,),
            edge_types=(),
            evidence=(),
            weight_product=1.0,
            hop_count=0,
            visited_symbol_ids={seed.symbol_id},
            contributions_by_target=contributions_by_target,
        )

    impacts = [
        _merge_contributions(contributions)
        for contributions in contributions_by_target.values()
        if contributions
    ]
    return sorted(impacts, key=lambda item: (-item.score, item.file_path, item.symbol_name))


def _build_adjacency(edges: list[EdgeLink]) -> dict[str, list[_TraversalEdge]]:
    adjacency: dict[str, list[_TraversalEdge]] = {}
    for edge in edges:
        if edge.edge_type == schemas.EdgeType.IMPORTS.value:
            _add_edge(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                evidence=edge.evidence,
            )
        elif edge.edge_type == schemas.EdgeType.INHERITS.value:
            _add_edge(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                evidence=edge.evidence,
            )
        elif edge.edge_type == schemas.EdgeType.CONTAINS.value:
            _add_edge(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                evidence=edge.evidence,
            )
            _add_edge(
                adjacency,
                source=edge.src_symbol_id,
                target=edge.dst_symbol_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                evidence=edge.evidence,
            )

    for links in adjacency.values():
        links.sort(key=lambda item: (item.edge_type, item.target_symbol_id))
    return adjacency


def _add_edge(
    adjacency: dict[str, list[_TraversalEdge]],
    *,
    source: str,
    target: str,
    edge_type: str,
    weight: float,
    evidence: dict[str, object],
) -> None:
    if source == target:
        return
    adjacency.setdefault(source, []).append(
        _TraversalEdge(
            target_symbol_id=target,
            edge_type=edge_type,
            weight=weight,
            evidence=evidence,
        )
    )


def _self_contribution(seed: ChangedSeed, symbol: SymbolNode) -> _PathContribution:
    seed_score = MODULE_SEED_SCORE if seed.is_module_level else SEED_SCORE
    return _PathContribution(
        source_symbol_id=seed.symbol_id,
        source_symbol_key=seed.symbol_key,
        source_symbol_kind=seed.symbol_kind,
        target_symbol_id=symbol.symbol_id,
        target_symbol_key=symbol.symbol_key,
        target_symbol_name=symbol.symbol_name,
        target_symbol_kind=symbol.symbol_kind,
        target_file_path=symbol.file_path,
        impact_path=(seed.symbol_key,),
        edge_types=(),
        hop_count=0,
        path_score=seed_score,
        evidence=(
            {
                "edge_type": "changed_symbol",
                "file_path": seed.file_path,
                "line": seed.start_line,
                "detail": (
                    f"diff mapped directly to changed symbol lines "
                    f"{seed.start_line}-{seed.end_line}"
                ),
            },
        ),
        is_test_symbol=symbol.symbol_kind in TEST_SYMBOL_KINDS,
    )


def _collect_path_contributions(
    *,
    seed: ChangedSeed,
    current_symbol_id: str,
    symbol_by_id: dict[str, SymbolNode],
    adjacency: dict[str, list[_TraversalEdge]],
    max_depth: int,
    path: tuple[str, ...],
    edge_types: tuple[str, ...],
    evidence: tuple[dict[str, object], ...],
    weight_product: float,
    hop_count: int,
    visited_symbol_ids: set[str],
    contributions_by_target: dict[str, list[_PathContribution]],
) -> None:
    if hop_count >= max_depth:
        return

    seed_score = MODULE_SEED_SCORE if seed.is_module_level else SEED_SCORE

    for edge in adjacency.get(current_symbol_id, []):
        if edge.target_symbol_id in visited_symbol_ids:
            continue
        target = symbol_by_id.get(edge.target_symbol_id)
        if target is None:
            continue

        next_hop = hop_count + 1
        next_path = (*path, target.symbol_key)
        next_edge_types = (*edge_types, edge.edge_type)
        next_evidence = (*evidence, _normalize_edge_evidence(edge))
        next_weight_product = weight_product * edge.weight
        next_score = seed_score * next_weight_product * (PATH_DECAY**next_hop)
        contribution = _PathContribution(
            source_symbol_id=seed.symbol_id,
            source_symbol_key=seed.symbol_key,
            source_symbol_kind=seed.symbol_kind,
            target_symbol_id=target.symbol_id,
            target_symbol_key=target.symbol_key,
            target_symbol_name=target.symbol_name,
            target_symbol_kind=target.symbol_kind,
            target_file_path=target.file_path,
            impact_path=next_path,
            edge_types=next_edge_types,
            hop_count=next_hop,
            path_score=next_score,
            evidence=next_evidence,
            is_test_symbol=target.symbol_kind in TEST_SYMBOL_KINDS,
        )
        contributions_by_target.setdefault(target.symbol_id, []).append(contribution)
        _collect_path_contributions(
            seed=seed,
            current_symbol_id=target.symbol_id,
            symbol_by_id=symbol_by_id,
            adjacency=adjacency,
            max_depth=max_depth,
            path=next_path,
            edge_types=next_edge_types,
            evidence=next_evidence,
            weight_product=next_weight_product,
            hop_count=next_hop,
            visited_symbol_ids={*visited_symbol_ids, target.symbol_id},
            contributions_by_target=contributions_by_target,
        )


def _normalize_edge_evidence(edge: _TraversalEdge) -> dict[str, object]:
    file_path = edge.evidence.get("file_path")
    line = edge.evidence.get("line")
    detail = edge.evidence.get("detail", edge.edge_type)
    return {
        "edge_type": edge.edge_type,
        "file_path": file_path if isinstance(file_path, str) else None,
        "line": line if isinstance(line, int) else None,
        "detail": detail if isinstance(detail, str) else edge.edge_type,
    }


def _merge_contributions(contributions: list[_PathContribution]) -> ScoredImpact:
    best = min(
        contributions,
        key=lambda item: (
            -item.path_score,
            item.hop_count,
            item.source_symbol_kind == schemas.SymbolKind.MODULE.value,
            _path_sort_key(item.impact_path),
        ),
    )
    merged_edge_types = _stable_unique(
        edge_type for contribution in contributions for edge_type in contribution.edge_types
    )
    contributing_changed_symbols = _stable_unique(
        contribution.source_symbol_key for contribution in contributions
    )
    evidence = _dedupe_evidence(
        evidence_item
        for contribution in _sorted_contributions_for_evidence(contributions)
        for evidence_item in contribution.evidence
    )
    score = best.path_score + (TEST_SYMBOL_BONUS if best.is_test_symbol else 0.0)
    clamped_score = round(min(1.0, score), 4)

    reasons_values: list[str] = []
    if any(not contribution.edge_types for contribution in contributions):
        reasons_values.append("changed_symbol")
    reasons_values.extend(merged_edge_types)
    reasons = tuple(reasons_values) if reasons_values else ("changed_symbol",)

    return ScoredImpact(
        symbol_id=best.target_symbol_id,
        symbol_key=best.target_symbol_key,
        symbol_name=best.target_symbol_name,
        symbol_kind=best.target_symbol_kind,
        file_path=best.target_file_path,
        score=clamped_score,
        confidence=_confidence_for_score(clamped_score),
        reasons=reasons,
        explanation_path=best.impact_path,
        reasons_json={
            "source_symbol": best.source_symbol_key,
            "matched_from_changed_symbol": best.source_symbol_key,
            "edge_types": list(merged_edge_types),
            "path_length": best.hop_count,
            "hop_count": best.hop_count,
            "merged_paths_count": len(contributions),
            "is_test_symbol": best.is_test_symbol,
            "contributing_changed_symbols": list(contributing_changed_symbols),
            "evidence": evidence,
        },
    )


def _sorted_contributions_for_evidence(
    contributions: list[_PathContribution],
) -> list[_PathContribution]:
    return sorted(
        contributions,
        key=lambda item: (
            -item.path_score,
            item.hop_count,
            item.source_symbol_kind == schemas.SymbolKind.MODULE.value,
            _path_sort_key(item.impact_path),
        ),
    )


def _path_sort_key(path: tuple[str, ...]) -> str:
    return "\x1f".join(path)


def _stable_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _dedupe_evidence(items: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str | None, int | None, str]] = set()
    ordered: list[dict[str, object]] = []
    for item in items:
        key = (
            str(item["edge_type"]),
            item["file_path"] if isinstance(item.get("file_path"), str) else None,
            item["line"] if isinstance(item.get("line"), int) else None,
            str(item["detail"]),
        )
        if key in seen:
            continue
        seen.add(key)
        ordered.append(
            {
                "edge_type": key[0],
                "file_path": key[1],
                "line": key[2],
                "detail": key[3],
            }
        )
    return ordered


def _confidence_for_score(score: float) -> str:
    if score >= 0.75:
        return schemas.Confidence.HIGH.value
    if score >= 0.45:
        return schemas.Confidence.MEDIUM.value
    return schemas.Confidence.LOW.value
