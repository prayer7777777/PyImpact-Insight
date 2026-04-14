# ADR 0007: P6 Tests, Coverage, and Recommendation Baseline

## Status

Accepted

## Date

2026-04-14

## Context

P5 produces changed symbols, baseline impacted symbols, final scored impacts, and explainable reasons, but it still leaves the `test_suggestions` list effectively unused. The repository can already recognize test symbols during AST extraction, yet there is no persisted test relation layer, no optional coverage enhancement, and no ranked recommendation output.

P6 adds a baseline test recommendation loop without expanding scope into call graph analysis, historical snapshot graphs, or a complex test optimizer.

## Decision

### Recommendation Goal

P6 produces a persisted `TestRecommendation` list for every completed analysis.

Rules:

- Recommendations remain advisory.
- They must be explainable from persisted change, impact, graph, and optional coverage data.
- They must work when coverage data is absent.

### Persisted Relation Model

P6 uses two persisted layers:

1. `Edge` rows with `edge_type = tests`
2. `TestRecommendation` rows

Rules:

- `tests` edges model stable static or coverage-backed relations from a test symbol to a production symbol.
- `TestRecommendation` remains the ranked API-facing recommendation layer.
- Recommendations may merge multiple relation candidates into one public row per test symbol.

### Static `tests` Edge Rules

P6 creates baseline static `tests` edges from already parsed Python test symbols.

Static rule:

- if a module contains one or more extracted test symbols
- and that module imports a resolvable non-test Python module
- then create `tests` edges from each test symbol in that module to the imported production module symbol

Stored direction remains:

- `test symbol -> production symbol`

Static `tests` edges use:

- weight: `0.90`
- evidence detail: static import relation from the test module

P6 does not yet create `tests` edges from:

- call graph analysis
- fixture dependency resolution
- runtime monkey patching
- framework-specific test discovery metadata

### Coverage Input

P6 treats coverage as an optional enhancement, never as the only source of test recommendations.

Supported coverage input for V1:

- repository-root `coverage.json`
- repository-root `coverage/coverage.json`

Expected format:

- Coverage.py JSON output with per-line `contexts`
- equivalent JSON with:
  - `files`
  - file-relative paths
  - `contexts` mapping line numbers to context strings

Context requirement:

- Coverage enhancement is only applied when contexts can be mapped to extracted test symbols.
- Without usable per-test contexts, the system falls back to static recommendations.

P6 does not read:

- historical coverage caches
- remote coverage services
- multi-run coverage merge stores

### Coverage Mapping Rules

When `options.use_coverage` is `true` and a usable `coverage.json` artifact exists:

1. Match coverage context strings to extracted test symbols.
2. Map covered production file lines to the smallest enclosing persisted non-test symbol.
3. Create or strengthen `tests` edges from the matched test symbol to the covered production symbol.

Coverage-backed `tests` edges use:

- weight: `1.00`
- evidence detail: coverage-backed line hit

If a static `tests` edge and a coverage-backed `tests` edge target the same source/target pair:

- keep one persisted edge
- prefer the higher weight
- merge evidence details when practical

### Coverage Missing or Unusable

Coverage absence must not fail the analysis.

Rules:

- if `options.use_coverage` is `false`, skip coverage loading silently
- if `options.use_coverage` is `true` and no supported coverage artifact exists, emit `NO_COVERAGE_DATA`
- if `options.use_coverage` is `true` and coverage exists but has no usable per-test contexts, emit `NO_COVERAGE_DATA`
- analysis still completes and produces baseline test recommendations

P6 keeps the warning intentionally coarse. Clients only need to know whether dynamic evidence was usable.

### Baseline Recommendation Sources

P6 merges recommendation candidates from these sources:

1. direct impacted test symbols
2. persisted static `tests` edges
3. persisted coverage-backed `tests` edges
4. conservative naming/file proximity fallback

#### 1. Direct impacted test symbol

If a final impact is itself a test symbol:

- recommend that test directly
- relation type: `direct_test_hit`
- public score starts from the impacted symbol score

#### 2. Static `tests` edge

If a persisted static `tests` edge reaches:

- the exact impacted production symbol, or
- a module symbol in the same file as the impacted production symbol

then recommend the test.

Relation types:

- `tests_edge_exact`
- `tests_edge_module`

#### 3. Coverage-backed `tests` edge

If a coverage-backed `tests` edge reaches the exact impacted production symbol:

- recommend the test
- boost score and tie-breaking priority
- mark `coverage_backed = true`

Relation type:

- `coverage_tests_edge`

#### 4. Naming/file proximity fallback

If no stronger relation exists, P6 may recommend a test when:

- the test file stem matches `test_<target module stem>`
- or the test symbol name contains the impacted symbol short name

Relation type:

- `name_proximity`

This fallback is intentionally conservative and cannot produce high-confidence results by itself.

### Recommendation Scores

Recommendation scores are floats from `0.0` to `1.0`.

Base rules:

- `direct_test_hit`: `impact.score`
- `tests_edge_exact` or `tests_edge_module`: `impact.score * 0.90`
- `coverage_tests_edge`: `min(1.0, impact.score + 0.15)`
- `name_proximity`: `min(0.60, max(0.25, impact.score * 0.55))`

Merge rules:

1. Group candidates by `test_symbol_id`
2. Pick the highest-scoring candidate as the public recommendation
3. If scores tie, prefer:
   - coverage-backed candidate
   - direct test hit
   - lower hop count
   - lexicographically smaller test name
4. Keep merged metadata:
   - `merged_paths_count`
   - strongest relation type
   - whether any coverage was used
   - whether any direct test hit exists

### Recommendation Confidence and Priority

Confidence maps directly from score:

- `high`: `score >= 0.75`
- `medium`: `0.45 <= score < 0.75`
- `low`: `score < 0.45`

Priority remains for backward compatibility and follows confidence:

- `high` -> `high`
- `medium` -> `medium`
- `low` -> `low`

### Recommendation reasons_json Contract

Every recommendation must include a structured explanation object with at least:

- `whether_coverage_used`
- `matched_impacted_symbol`
- `relation_type`
- `hop_count`
- `merged_paths_count`
- `is_direct_test_hit`

Recommended shape:

```json
{
  "whether_coverage_used": true,
  "matched_impacted_symbol": "service.py::service.bootstrap",
  "relation_type": "coverage_tests_edge",
  "hop_count": 1,
  "merged_paths_count": 2,
  "is_direct_test_hit": false,
  "evidence": [
    {
      "edge_type": "tests",
      "file_path": "service.py",
      "line": 8,
      "detail": "coverage context tests/test_service.py::test_bootstrap covers service.bootstrap"
    }
  ]
}
```

### Summary Fields

P6 fills:

- `recommended_tests`
- `high_confidence_test_recommendations`

Definitions:

- `recommended_tests`: persisted recommendation count
- `high_confidence_test_recommendations`: recommendation count whose confidence is `high`

### API Shape

`GET /api/v1/analyses/{analysis_id}` continues returning `test_suggestions`.

Each item must include:

- `test_symbol_id`
- `test_name`
- `file_path`
- `score`
- `confidence`
- `priority`
- `reason`
- `reasons_json`
- `coverage_backed`

### Limitations

P6 intentionally does not implement:

- `CALLS`
- historical snapshot graph coverage replay
- flaky-test suppression
- cost-aware or shard-aware test selection
- framework-specific fixture dependency modeling

## Consequences

- Analyses now return explainable baseline test recommendations even without coverage.
- Existing coverage data can improve confidence and ordering when usable per-test contexts are present.
- Recommendation quality remains conservative because P6 still lacks call graph and fixture-level semantics.
