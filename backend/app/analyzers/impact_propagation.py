from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.api.schemas import EdgeType, SymbolKind


@dataclass(frozen=True)
class ChangedSeed:
    symbol_id: str
    symbol_key: str
    symbol_kind: str


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


@dataclass(frozen=True)
class ImpactCandidate:
    source_symbol_id: str
    source_symbol_key: str
    source_symbol_kind: str
    symbol_id: str
    symbol_key: str
    symbol_name: str
    symbol_kind: str
    file_id: str
    file_path: str
    hop_count: int
    impact_reason: str
    impact_path: tuple[str, ...]
    edge_types: tuple[str, ...]
    is_test: bool


@dataclass(frozen=True)
class _TraversalEdge:
    target_symbol_id: str
    edge_type: str
    impact_reason: str


@dataclass(frozen=True)
class _QueueItem:
    symbol_id: str
    path: tuple[str, ...]
    edge_types: tuple[str, ...]
    reasons: tuple[str, ...]
    hop_count: int


TEST_SYMBOL_KINDS = {
    SymbolKind.TEST_FUNCTION.value,
    SymbolKind.TEST_METHOD.value,
}


def propagate_impacts(
    *,
    changed_symbols: list[ChangedSeed],
    symbols: list[SymbolNode],
    edges: list[EdgeLink],
    max_depth: int,
) -> list[ImpactCandidate]:
    symbol_by_id = {symbol.symbol_id: symbol for symbol in symbols}
    changed_symbol_ids = {seed.symbol_id for seed in changed_symbols}
    adjacency = _build_adjacency(edges)
    best_by_symbol_id: dict[str, ImpactCandidate] = {}

    for seed in sorted(changed_symbols, key=lambda item: item.symbol_key):
        if seed.symbol_id not in symbol_by_id:
            continue
        _propagate_from_seed(
            seed=seed,
            symbol_by_id=symbol_by_id,
            changed_symbol_ids=changed_symbol_ids,
            adjacency=adjacency,
            max_depth=max_depth,
            best_by_symbol_id=best_by_symbol_id,
        )

    return sorted(
        best_by_symbol_id.values(),
        key=lambda item: (item.hop_count, item.file_path, item.symbol_key),
    )


def _build_adjacency(edges: list[EdgeLink]) -> dict[str, list[_TraversalEdge]]:
    adjacency: dict[str, list[_TraversalEdge]] = {}
    for edge in edges:
        if edge.edge_type == EdgeType.IMPORTS.value:
            _add_adjacency(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                impact_reason="reverse_imports",
            )
        elif edge.edge_type == EdgeType.INHERITS.value:
            _add_adjacency(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                impact_reason="reverse_inherits",
            )
        elif edge.edge_type == EdgeType.CONTAINS.value:
            _add_adjacency(
                adjacency,
                source=edge.dst_symbol_id,
                target=edge.src_symbol_id,
                edge_type=edge.edge_type,
                impact_reason="reverse_contains",
            )
            _add_adjacency(
                adjacency,
                source=edge.src_symbol_id,
                target=edge.dst_symbol_id,
                edge_type=edge.edge_type,
                impact_reason="contains_child",
            )

    for links in adjacency.values():
        links.sort(key=lambda item: (item.impact_reason, item.target_symbol_id))
    return adjacency


def _add_adjacency(
    adjacency: dict[str, list[_TraversalEdge]],
    *,
    source: str,
    target: str,
    edge_type: str,
    impact_reason: str,
) -> None:
    if source == target:
        return
    adjacency.setdefault(source, []).append(
        _TraversalEdge(target_symbol_id=target, edge_type=edge_type, impact_reason=impact_reason)
    )


def _propagate_from_seed(
    *,
    seed: ChangedSeed,
    symbol_by_id: dict[str, SymbolNode],
    changed_symbol_ids: set[str],
    adjacency: dict[str, list[_TraversalEdge]],
    max_depth: int,
    best_by_symbol_id: dict[str, ImpactCandidate],
) -> None:
    queue: deque[_QueueItem] = deque(
        [
            _QueueItem(
                symbol_id=seed.symbol_id,
                path=(seed.symbol_key,),
                edge_types=(),
                reasons=(),
                hop_count=0,
            )
        ]
    )
    visited_depth = {seed.symbol_id: 0}

    while queue:
        item = queue.popleft()
        if item.hop_count >= max_depth:
            continue

        for edge in adjacency.get(item.symbol_id, []):
            target = symbol_by_id.get(edge.target_symbol_id)
            if target is None:
                continue
            next_hop = item.hop_count + 1
            if visited_depth.get(target.symbol_id, max_depth + 1) <= next_hop:
                continue
            visited_depth[target.symbol_id] = next_hop

            next_path = (*item.path, target.symbol_key)
            next_edge_types = (*item.edge_types, edge.edge_type)
            next_reasons = (*item.reasons, edge.impact_reason)
            if target.symbol_id not in changed_symbol_ids:
                candidate = ImpactCandidate(
                    source_symbol_id=seed.symbol_id,
                    source_symbol_key=seed.symbol_key,
                    source_symbol_kind=seed.symbol_kind,
                    symbol_id=target.symbol_id,
                    symbol_key=target.symbol_key,
                    symbol_name=target.symbol_name,
                    symbol_kind=target.symbol_kind,
                    file_id=target.file_id,
                    file_path=target.file_path,
                    hop_count=next_hop,
                    impact_reason=" -> ".join(next_reasons),
                    impact_path=next_path,
                    edge_types=next_edge_types,
                    is_test=target.symbol_kind in TEST_SYMBOL_KINDS,
                )
                _keep_best_candidate(best_by_symbol_id, candidate)

            queue.append(
                _QueueItem(
                    symbol_id=target.symbol_id,
                    path=next_path,
                    edge_types=next_edge_types,
                    reasons=next_reasons,
                    hop_count=next_hop,
                )
            )


def _keep_best_candidate(
    best_by_symbol_id: dict[str, ImpactCandidate], candidate: ImpactCandidate
) -> None:
    current = best_by_symbol_id.get(candidate.symbol_id)
    if current is None:
        best_by_symbol_id[candidate.symbol_id] = candidate
        return
    if candidate.hop_count < current.hop_count:
        best_by_symbol_id[candidate.symbol_id] = candidate
        return
    if candidate.hop_count == current.hop_count and (
        candidate.source_symbol_kind != SymbolKind.MODULE.value
        and current.source_symbol_kind == SymbolKind.MODULE.value
    ):
        best_by_symbol_id[candidate.symbol_id] = candidate
        return
    if candidate.hop_count == current.hop_count and candidate.impact_path < current.impact_path:
        best_by_symbol_id[candidate.symbol_id] = candidate
