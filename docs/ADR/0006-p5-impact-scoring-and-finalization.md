# ADR 0006: P5 Impact Scoring and Finalization

## Status

Accepted

## Date

2026-04-14

## Context

P4 persists baseline `ImpactedSymbol` candidates and their best propagation path, but it does not produce final ranked `Impact` results. The API still returns an empty `impacts` list, and analysis summary data cannot yet distinguish between raw candidate propagation and final scored output.

P5 must turn changed symbols and propagated candidates into deterministic, explainable, persisted final impacts without expanding scope into call graph analysis, coverage-backed propagation, test recommendation ranking, or historical snapshot graphs.

## Decision

### Final Result Model

P5 uses the existing persisted `Impact` table as the final result layer.

Rules:

- `ImpactedSymbol` remains the baseline candidate layer from P4.
- `Impact` becomes the persisted, sorted, API-facing final result layer.
- Final impacts include both:
  - directly changed symbols
  - propagated candidate symbols reached through supported structural edges

### Supported Inputs

P5 scores only the graph and change data already available after P4:

- changed symbols from `ChangedSymbol`
- graph symbols from `Symbol`
- graph edges from `Edge`
- baseline candidate semantics defined in ADR 0005

P5 still does not use:

- `calls`
- `tests` edges
- coverage
- heuristic proximity edges
- name similarity edges
- historical ref-specific symbol graphs

### Base Seed Scores

Seed scores follow ADR 0001 and remain stable:

- changed non-module symbol: `1.00`
- changed module symbol: `0.70`

P5 does not create final file-level impacts for unmapped spans or parse-failed files. Those remain visible only through summary counters and warnings.

### Edge Weights

P5 uses the persisted structural edge weights already established by ADR 0001 and earlier stages:

- `imports`: `0.80`
- `inherits`: `0.75`
- `contains`: `0.40`

### Hop Decay

P5 applies the ADR 0001 default decay:

- `path_decay = 0.85`

For a path with `hop_count = n`:

```text
path_score = seed_score * edge_weight_product * (0.85 ^ n)
```

Self impacts for changed symbols have `hop_count = 0`, so no decay is applied.

### Test Symbol Adjustment

P5 allows a small deterministic bonus for symbols that are themselves tests:

- `test_symbol_bonus = 0.05`

Rules:

- Apply the bonus only when the impacted symbol kind is `test_function` or `test_method`.
- Apply the bonus after choosing the best merged path score.
- Clamp the final score to `1.0`.

P5 does not infer or rank runnable tests beyond these already-detected test symbols.

### Multi-Path Merge Rule

Multiple changed-source paths may reach the same target symbol. P5 merges them into one final `Impact`.

Merge rules:

1. Group path contributions by target `symbol_id`.
2. Compute a path score for every contribution.
3. Select the public explanation path from the highest-scoring contribution.
4. If scores tie, prefer:
   - lower `hop_count`
   - non-module changed source over module changed source
   - lexicographically smaller `impact_path`
5. Public `score` is:

```text
score = min(1.0, best_path_score + test_symbol_bonus_if_applicable)
```

6. Additional paths do not additively increase the public score in P5.
7. Additional paths are preserved through merged metadata:
   - `merged_paths_count`
   - merged `edge_types`
   - merged source-symbol list

This keeps the score stable and consistent with ADR 0001, while still exposing merge evidence.

### Confidence Thresholds

Confidence remains a pure score mapping:

- `high`: `score >= 0.75`
- `medium`: `0.45 <= score < 0.75`
- `low`: `score < 0.45`

No other heuristic or random rule may modify confidence.

### reasons_json Contract

P5 extends `reasons_json` while preserving ADR 0001 minimum fields.

Every final impact must include:

- `source_symbol`
- `matched_from_changed_symbol`
- `edge_types`
- `path_length`
- `hop_count`
- `merged_paths_count`
- `is_test_symbol`
- `evidence`

Recommended shape:

```json
{
  "source_symbol": "core.py::core.target",
  "matched_from_changed_symbol": "core.py::core.target",
  "edge_types": ["imports", "contains"],
  "path_length": 2,
  "hop_count": 2,
  "merged_paths_count": 3,
  "is_test_symbol": false,
  "contributing_changed_symbols": [
    "core.py::core.target",
    "core.py::core"
  ],
  "evidence": [
    {
      "edge_type": "imports",
      "file_path": "consumer.py",
      "line": 1,
      "detail": "consumer imports core"
    }
  ]
}
```

Rules:

- `source_symbol` and `matched_from_changed_symbol` both refer to the changed symbol chosen for the best explanation path.
- `path_length` equals `hop_count`.
- `edge_types` is the stable merged set of edge types observed across all merged paths.
- `evidence` may include best-path evidence and additional deduplicated evidence from merged paths.
- A changed symbol scoring itself may use a synthetic `changed_symbol` evidence item with diff-mapping detail.

### Summary Fields

P5 extends `AnalysisSummary` with:

- `top_impacts`
- `high_confidence_impacts`

P5 also redefines `impacted_tests` to mean the number of final scored impacts whose symbol kind is `test_function` or `test_method`.

Definitions:

- `impacted_symbols`: number of persisted baseline `ImpactedSymbol` candidates
- `propagation_paths`: number of persisted baseline propagation paths
- `top_impacts`: number of persisted final `Impact` rows returned in ranked order
- `high_confidence_impacts`: number of final `Impact` rows with confidence `high`
- `impacted_tests`: number of final `Impact` rows whose target symbol is a test symbol

### Sorting

Final `Impact` rows are sorted by:

1. `score` descending
2. `file_path` ascending
3. `symbol_name` ascending

### Limitations

P5 intentionally does not implement:

- `calls` propagation
- coverage-backed score adjustment
- test recommendation generation
- historical ref-specific symbol graphs
- explanation prose beyond structured path metadata

Scores in P5 are therefore baseline structural scores, not full semantic impact estimates.

## Consequences

- `GET /api/v1/analyses/{analysis_id}` now returns non-empty `impacts` when changed symbols or propagated candidates exist.
- Final impact scores are deterministic and explainable from persisted graph and diff data.
- Changed symbols receive explicit final impact entries instead of being visible only in `changed_symbols`.
- Multi-path hits are merged into one stable public result without inflating the score unpredictably.
