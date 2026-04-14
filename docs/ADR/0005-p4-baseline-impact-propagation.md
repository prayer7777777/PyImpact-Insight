# ADR 0005: P4 Baseline Impact Propagation

## Status

Accepted

## Date

2026-04-14

## Context

P3 persists changed Python symbols and the structural graph needed to continue analysis. P4 adds the first baseline propagation step that turns changed symbols into candidate impacted symbols.

P4 must remain intentionally narrow. It should produce explainable candidate targets and propagation paths, but it must not introduce final scoring, confidence bands, coverage logic, or test recommendation logic.

## Decision

### Candidate Model

P4 adds a dedicated persisted candidate model:

- `ImpactedSymbol`

This model is separate from the existing scored `Impact` model.

Rules:

- `ImpactedSymbol` stores baseline candidates only.
- It records `source_symbol`, `target symbol`, `hop_count`, `impact_reason`, `impact_path`, and traversed `edge_types`.
- P4 leaves the scored `Impact` table empty.

### Propagation Inputs

P4 starts from the persisted `ChangedSymbol` rows produced by P3.

The propagation graph uses only these existing edge types:

- `imports`
- `inherits`
- `contains`

P4 does not use:

- `calls`
- `tests`
- heuristic proximity edges
- name similarity edges

### Traversal Rules

P4 uses breadth-first traversal with `options.max_depth` as the hop limit.

#### Reverse dependency traversal

For dependency-style edges, P4 walks in the reverse direction from the changed symbol toward dependents:

- `imports`: imported module -> importer module
- `inherits`: base class -> subclass

#### Structural containment cascade

`contains` is treated as a structural cascade edge rather than a pure dependency edge.

P4 traverses it in both directions:

- child -> parent with reason `reverse_contains`
- parent -> child with reason `contains_child`

This allows baseline parent/child impact roll-up and roll-down, including:

- changed method -> containing class/module
- changed module -> contained functions/classes/tests
- test module reached by imports -> contained test function reached by `contains`

### Path Selection and Deduplication

P4 records one best candidate per impacted symbol.

Selection rules:

- prefer lower `hop_count`
- when hop count is equal, prefer a path whose changed source is not a module-level symbol
- if still tied, prefer lexicographically smaller `impact_path`

Changed symbols themselves are not stored again as impacted targets.

Cycles must not cause infinite traversal.

### Summary Fields

P4 extends `AnalysisSummary` with:

- `impacted_symbols`
- `impacted_tests`
- `propagation_paths`

Definitions:

- `impacted_symbols`: number of persisted `ImpactedSymbol` rows
- `impacted_tests`: impacted candidates whose symbol kind is `test_function` or `test_method`
- `propagation_paths`: number of stored baseline propagation paths, currently equal to `impacted_symbols`

### API Shape

`GET /api/v1/analyses/{analysis_id}` includes a new `impacted_symbols` list with:

- source and target symbol IDs
- source and target symbol keys
- symbol kind
- file path
- hop count
- impact reason
- impact path
- traversed edge types
- `is_test`

The existing scored `impacts` list remains present but empty in P4.

### Limitations

P4 intentionally does not implement:

- `CALLS` propagation
- final scoring
- confidence levels
- explanation prose refinement
- coverage-backed propagation
- test recommendation ranking

P4 still relies on the current working tree symbol graph. Historical snapshot parsing for arbitrary refs remains deferred.

## Consequences

- Completed analyses now persist baseline impacted symbol candidates.
- Reports and API responses can show changed symbols, impacted candidates, and propagation paths separately.
- Existing local SQLite databases created before P4 may need to be recreated because migrations are still deferred.
