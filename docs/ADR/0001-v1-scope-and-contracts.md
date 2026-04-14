# ADR 0001: V1 Scope and Contracts

## Status

Accepted

## Date

2026-04-14

## Context

`docs/PROJECT_SPEC.md` defines the product direction for a Python repository change-impact analyzer. The specification is sufficient as a project charter, but implementation still needs executable contracts so backend schemas, persistence models, analyzers, scoring, reports, and frontend views do not diverge.

This ADR freezes the V1 contracts for:

- API shape and error format
- diff mode behavior
- graph edge direction
- impact propagation and explanation paths
- scoring and confidence
- Python symbol scope
- path, ID, and enum conventions

V1 remains Python-only. It does not attempt multi-language analysis, deep interprocedural data flow, IDE/LSP behavior, or complete support for dynamic Python features.

## Decision

### 1. Versioned API Surface

All HTTP APIs use the `/api/v1` prefix.

V1 starts with five required endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Return service health and version metadata. |
| `POST` | `/api/v1/repositories` | Register a local Git repository for analysis. |
| `POST` | `/api/v1/analyses` | Start one change-impact analysis task. |
| `GET` | `/api/v1/analyses/{analysis_id}` | Return analysis status, summary, impacts, and test suggestions. |
| `GET` | `/api/v1/analyses/{analysis_id}/report` | Return a Markdown report for an analysis. |

Additional graph, path, history, and settings endpoints may be added later, but they must not replace these baseline contracts in V1.

### 2. API Error Envelope

All failed API responses use this shape:

```json
{
  "error": {
    "code": "INVALID_DIFF_MODE",
    "message": "diff_mode must be one of working_tree, commit_range, refs_compare",
    "details": {},
    "request_id": "uuid"
  }
}
```

Rules:

- `error.code` is stable and machine-readable.
- `error.message` is human-readable and safe to show in the UI.
- `error.details` is an object. Use `{}` when no structured details exist.
- `error.request_id` is a UUID string generated per request.
- The same request ID should also be returned in the `X-Request-ID` header when the web framework makes that practical.
- Exceptions must not be swallowed silently. Unexpected exceptions map to `INTERNAL_ERROR` with a non-sensitive message.

Initial error codes:

| Code | Meaning |
| --- | --- |
| `INVALID_REQUEST` | Request body or query parameters are malformed. |
| `INVALID_REPOSITORY_PATH` | The repository path does not exist or is not readable. |
| `NOT_A_GIT_REPOSITORY` | The path is not inside a Git repository. |
| `REPOSITORY_HAS_NO_COMMITS` | The selected diff mode requires a Git commit but none exists. |
| `INVALID_DIFF_MODE` | `diff_mode` is not a supported enum value. |
| `INVALID_REF` | A commit, branch, tag, or ref cannot be resolved. |
| `ANALYSIS_NOT_FOUND` | The requested analysis ID does not exist. |
| `ANALYSIS_FAILED` | The task exists but failed during execution. |
| `INTERNAL_ERROR` | Unexpected server error. |

### 3. ID, Path, and Time Conventions

Persistent resource IDs are UUID strings:

- `repository_id`
- `analysis_id`
- `file_id`
- `symbol_id`
- `edge_id`

Analyzer-facing stable keys are strings and may be stored alongside UUIDs:

- `file_key`: repo-relative POSIX path, for example `app/service.py`
- `symbol_key`: `file_key::qualname`, for example `app/service.py::service.bootstrap`

Path rules:

- All API paths are repository-relative POSIX paths using `/`.
- Absolute local paths may be accepted only in repository registration requests.
- API responses must not expose host-specific absolute paths except the registered repository path in repository detail responses.
- Ignored files are excluded before parsing and graph construction.

Time rules:

- API timestamps use ISO 8601 strings with timezone.
- Internally stored timestamps should be UTC.

### 4. Core Enums

#### Diff Mode

| Value | Meaning |
| --- | --- |
| `working_tree` | Compare the working tree against `HEAD`, including staged and unstaged tracked changes. |
| `commit_range` | Compare `commit_from` directly to `commit_to`. |
| `refs_compare` | Compare `merge-base(base_ref, head_ref)` to `head_ref`, for branch or pull-request style analysis. |

#### Analysis Status

| Value | Meaning |
| --- | --- |
| `queued` | Task was accepted but has not started. |
| `running` | Task is currently executing. |
| `completed` | Task finished successfully. |
| `failed` | Task stopped with a structured error. |
| `canceled` | Task was canceled by the user or system. |

#### File Change Type

| Value | Meaning |
| --- | --- |
| `added` | File exists only in the target side. |
| `modified` | File exists on both sides and content changed. |
| `deleted` | File exists only in the base side. |
| `renamed` | Git identified a rename, with or without content changes. |

#### Parse Status

| Value | Meaning |
| --- | --- |
| `parsed` | Python file parsed successfully. |
| `parse_failed` | Python parser failed, usually because of syntax errors. |
| `skipped_binary` | File is binary and not analyzed. |
| `skipped_non_python` | File is outside V1 Python analyzer scope. |
| `skipped_ignored` | File was excluded by ignore rules. |
| `missing` | File does not exist on the side being parsed. |

#### Symbol Kind

| Value | Meaning |
| --- | --- |
| `module` | Python module derived from a `.py` file. |
| `class` | Class definition. |
| `function` | Top-level synchronous function. |
| `async_function` | Top-level async function. |
| `method` | Instance method. |
| `async_method` | Async instance method. |
| `staticmethod` | Method decorated with `@staticmethod`. |
| `classmethod` | Method decorated with `@classmethod`. |
| `test_function` | Pytest-style top-level test function. |
| `test_method` | Pytest-style test method. |

#### Edge Type

| Value | Direction |
| --- | --- |
| `contains` | module or class -> child symbol |
| `calls` | caller -> callee |
| `imports` | importer -> imported module |
| `inherits` | subclass -> base class |
| `tests` | test symbol -> production symbol |
| `same_module_proximity` | symbol -> nearby symbol in the same module |
| `same_package_proximity` | symbol -> nearby symbol in the same package |
| `name_similarity` | symbol -> symbol with a similar name |

#### Confidence

| Value | Score Range |
| --- | --- |
| `high` | `score >= 0.75` |
| `medium` | `0.45 <= score < 0.75` |
| `low` | `score < 0.45` |

### 5. Repository Registration Contract

Request:

```json
{
  "name": "sample-service",
  "repo_path": "/absolute/path/to/repo",
  "main_branch": "main"
}
```

Response:

```json
{
  "repository_id": "uuid",
  "name": "sample-service",
  "repo_path": "/absolute/path/to/repo",
  "main_branch": "main",
  "language": "python",
  "created_at": "2026-04-14T12:00:00Z"
}
```

Rules:

- `repo_path` must exist and resolve to a Git repository.
- `language` is always `python` in V1.
- `main_branch` defaults to the current Git branch when omitted.
- Repository registration does not run impact analysis by itself.

### 6. Analysis Request Contract

Request:

```json
{
  "repository_id": "uuid",
  "diff_mode": "working_tree",
  "commit_from": null,
  "commit_to": null,
  "base_ref": null,
  "head_ref": null,
  "include_untracked": false,
  "options": {
    "max_depth": 4,
    "include_tests": true,
    "use_coverage": false
  }
}
```

Rules:

- `repository_id` is required.
- `diff_mode` is required.
- `commit_from` and `commit_to` are required only for `commit_range`.
- `base_ref` and `head_ref` are required only for `refs_compare`.
- `include_untracked` applies only to `working_tree`.
- `options.max_depth` defaults to `4`.
- `options.include_tests` defaults to `true`.
- `options.use_coverage` defaults to `false`.

Initial accepted response:

```json
{
  "analysis_id": "uuid",
  "repository_id": "uuid",
  "status": "queued",
  "created_at": "2026-04-14T12:00:00Z"
}
```

V1 may execute synchronously inside the request for simplicity, but the public contract still exposes task status so asynchronous execution can be added later without breaking clients.

### 7. Analysis Result Contract

Response:

```json
{
  "analysis_id": "uuid",
  "repository_id": "uuid",
  "status": "completed",
  "summary": {
    "changed_files": 3,
    "changed_symbols": 7,
    "impacted_symbols": 18,
    "recommended_tests": 6,
    "skipped_files": 1,
    "parse_failures": 0
  },
  "changed_symbols": [
    {
      "symbol_id": "uuid",
      "symbol_key": "app/config.py::config.load_settings",
      "symbol_name": "config.load_settings",
      "symbol_kind": "function",
      "file_path": "app/config.py",
      "start_line": 10,
      "end_line": 28,
      "change_type": "modified"
    }
  ],
  "impacts": [
    {
      "symbol_id": "uuid",
      "symbol_key": "app/service.py::service.bootstrap",
      "symbol_name": "service.bootstrap",
      "symbol_kind": "function",
      "file_path": "app/service.py",
      "score": 0.86,
      "confidence": "high",
      "reasons": ["calls", "same_module_proximity"],
      "explanation_path": [
        "app/config.py::config.load_settings",
        "app/service.py::service.bootstrap"
      ],
      "reasons_json": {
        "source_symbol": "app/config.py::config.load_settings",
        "edge_types": ["calls"],
        "path_length": 1,
        "evidence": [
          {
            "edge_type": "calls",
            "file_path": "app/service.py",
            "line": 18,
            "detail": "service.bootstrap calls config.load_settings"
          }
        ]
      }
    }
  ],
  "test_suggestions": [
    {
      "test_symbol_id": "uuid",
      "test_name": "tests/test_service.py::test_bootstrap",
      "file_path": "tests/test_service.py",
      "priority": "high",
      "reason": "test relation reaches impacted symbol through reverse dependency traversal",
      "coverage_backed": false
    }
  ],
  "warnings": [
    {
      "code": "NO_COVERAGE_DATA",
      "message": "Test suggestions do not include dynamic coverage evidence."
    }
  ]
}
```

Rules:

- Every impact must include `score`, `confidence`, `reasons`, `explanation_path`, and `reasons_json`.
- High-confidence impacts must include at least one concrete evidence item.
- `explanation_path` uses `symbol_key` values.
- The report endpoint renders from the same persisted result data.

### 8. Diff Behavior

#### `working_tree`

`working_tree` compares the current working tree to `HEAD`.

Rules:

- Includes staged and unstaged changes for tracked files.
- Excludes untracked files by default.
- Includes untracked Python files as `added` only when `include_untracked` is `true`.
- Requires at least one commit when `include_untracked` is `false`.
- If the repository has no commits and `include_untracked` is `true`, untracked Python files are treated as added files from an empty base.

#### `commit_range`

`commit_range` compares `commit_from` directly to `commit_to`.

Rules:

- Both commits must resolve.
- Working tree changes are ignored.
- The comparison uses tree content, not local checkout state.

#### `refs_compare`

`refs_compare` compares `merge-base(base_ref, head_ref)` to `head_ref`.

Rules:

- Both refs must resolve.
- This mode is intended for branch or pull-request style analysis.
- Working tree changes are ignored.

#### Common Diff Rules

Line ranges:

- Added and modified spans use target-side line numbers.
- Deleted spans use base-side line numbers.
- A hunk that touches multiple symbols produces multiple `ChangeSpan` records.

Rename behavior:

- Rename records keep both `old_path` and `new_path`.
- Added or modified lines in a renamed file map against the target-side file.
- Deleted lines in a renamed file map against the base-side file.
- If a symbol exists only in the base side, it may appear as a deleted seed symbol but not as a runnable impacted target.

Skipped files:

- Binary files are recorded as `skipped_binary`.
- Non-Python files are recorded as `skipped_non_python`.
- Ignored files are recorded as `skipped_ignored`.
- Skipped files can appear in summaries and warnings, but they do not produce symbols or graph edges in V1.

Parse failures:

- A Python file that cannot be parsed is marked `parse_failed`.
- If a previous valid symbol index exists, the analyzer may use it for low-confidence fallback mapping.
- Without a valid symbol index, changed spans become `unmapped_spans` at file level.
- Parse failures must be visible in the API response summary and warnings.

### 9. Symbol Extraction Rules

V1 supports extracting:

- modules
- classes
- top-level functions
- top-level async functions
- instance methods
- async instance methods
- static methods
- class methods
- pytest-style test functions
- pytest-style test methods

V1 does not separately model:

- lambdas
- comprehensions as callable symbols
- dynamically generated functions
- monkey patch targets
- runtime import targets
- framework-specific dependency injection targets

Nested functions:

- Nested functions may be recorded with a qualified name that includes the parent scope.
- V1 does not guarantee precise cross-scope call resolution for nested functions.
- If nested function behavior is uncertain, scoring must use low or medium confidence rather than high confidence.

Test detection:

- A top-level function named `test_*` is `test_function`.
- A method named `test_*` inside a class named `Test*` is `test_method`.
- Decorator-specific pytest behavior is optional in V1.

Line ranges:

- `start_line` and `end_line` are 1-based inclusive lines.
- Decorators are included in the symbol range when they exist.
- A change maps to the smallest enclosing supported symbol.
- If no supported enclosing symbol exists, the change maps to the module symbol.

### 10. Graph Edge Direction

Stored graph edges always use source-to-target semantic direction:

| Edge Type | Stored Direction | Example |
| --- | --- | --- |
| `contains` | container -> child | `app.service` -> `app.service.bootstrap` |
| `calls` | caller -> callee | `api.startup` -> `service.bootstrap` |
| `imports` | importer -> imported module | `api.routes` -> `service` |
| `inherits` | subclass -> base class | `JsonConfig` -> `BaseConfig` |
| `tests` | test -> production symbol | `test_bootstrap` -> `service.bootstrap` |
| `same_module_proximity` | source symbol -> nearby symbol | `load_settings` -> `validate_settings` |
| `same_package_proximity` | source symbol -> nearby symbol | `service.bootstrap` -> `service.shutdown` |
| `name_similarity` | source symbol -> similar symbol | `parse_config` -> `test_parse_config` |

Impact propagation rule:

- The analyzer starts from changed symbols.
- To find impacted dependents, default propagation traverses reverse dependency direction.
- For example, if stored edge is `caller -> callee`, a changed callee impacts callers by traversing the edge in reverse.
- The stored edge direction is preserved in `reasons_json` evidence.
- UI text should translate paths into human-readable explanations instead of exposing only raw graph direction.

### 11. Edge Weights and Evidence

Default edge weights:

| Edge Type | Weight | Confidence Category |
| --- | ---: | --- |
| `calls` | `1.00` | high-confidence |
| `imports` | `0.80` | high-confidence |
| `inherits` | `0.75` | high-confidence |
| `tests` | `0.90` | high-confidence |
| `tests` with coverage evidence | `1.00` | high-confidence |
| `contains` | `0.40` | structural |
| `same_module_proximity` | `0.35` | heuristic |
| `same_package_proximity` | `0.25` | heuristic |
| `name_similarity` | `0.20` | heuristic |

Each edge should include evidence when available:

```json
{
  "edge_type": "calls",
  "file_path": "app/service.py",
  "line": 18,
  "detail": "service.bootstrap calls config.load_settings"
}
```

Rules:

- High-confidence edges should include file and line evidence when statically known.
- Heuristic edges must identify the heuristic used.
- Unresolved imports and unresolved calls may be recorded as parser evidence, but they must not become high-confidence graph edges.

### 12. Scoring Contract

Scores are floats from `0.0` to `1.0`.

Seed rules:

- Directly changed symbol: seed score `1.00`.
- Module-level mapped change: seed score `0.70`.
- File-level unmapped Python span: seed score `0.45`.
- Parse-failed file-level span: seed score `0.30`.

Path scoring:

```text
path_score = seed_score * edge_weight_product * (path_decay ^ hop_count)
score = min(1.0, max(path_score for all paths to the impacted symbol) + optional_test_bonus)
```

Defaults:

- `path_decay`: `0.85`
- `max_depth`: `4`
- `optional_test_bonus`: `0.05` when an impacted production symbol has a direct or coverage-backed test relation

Confidence:

- `high`: `score >= 0.75`
- `medium`: `0.45 <= score < 0.75`
- `low`: `score < 0.45`

Tie and duplicate rules:

- If multiple paths reach the same symbol, keep the maximum score as the public `score`.
- Persist at least the best explanation path.
- Persist additional paths when they materially change the explanation.
- Sort impacts by score descending, then file path, then symbol name.

Explanation rules:

- Every impact must have `reasons_json.source_symbol`.
- Every impact must have `reasons_json.edge_types`.
- Every impact must have `reasons_json.path_length`.
- High-confidence impacts must have at least one evidence item.
- Heuristic-only impacts must be labeled through `reasons` and evidence details.

### 13. Test Suggestion Rules

Test suggestions are derived from:

- reverse traversal of stored `tests` edges
- name similarity between production symbols and tests
- same module or same package proximity
- coverage data when `options.use_coverage` is `true` and coverage data exists

Rules:

- Suggestions with coverage evidence may be high priority.
- Suggestions without coverage evidence must include the `NO_COVERAGE_DATA` warning when coverage was requested or expected.
- When no coverage data exists, responses must state that test suggestions do not include dynamic coverage evidence.
- Test suggestions must not claim execution certainty unless coverage data supports it.

Priority mapping:

| Priority | Rule |
| --- | --- |
| `high` | Direct `tests` edge or coverage-backed relation to a changed or high-confidence impacted symbol. |
| `medium` | Static or heuristic relation to a medium-confidence impacted symbol. |
| `low` | Heuristic-only relation with score below `0.45`. |

### 14. Persistence Model Implications

The database models should support at minimum:

- `Project`
- `AnalysisTask`
- `CodeFile`
- `Symbol`
- `Edge`
- `ChangeSpan`
- `ImpactResult`
- `TestSuggestion`
- `ProjectSetting`

JSON columns may be used for:

- `Edge.evidence`
- `ImpactResult.reasons_json`
- `ProjectSetting.ignore_paths`
- `ProjectSetting.score_weights`
- `ProjectSetting.parser_options`

Recommended uniqueness rules:

- A project path should be unique after realpath normalization.
- A code file is unique by `(project_id, path, analysis_id)` when storing per-analysis snapshots.
- A symbol is unique by `(analysis_id, file_id, qualname, kind, start_line, end_line)`.
- An edge is unique by `(analysis_id, src_symbol_id, dst_symbol_id, edge_type)`.

### 15. Consequences

Benefits:

- Backend schemas, ORM models, analyzers, scoring, reports, and frontend views share one contract.
- Graph edge direction is explicit, while impact propagation can safely use reverse traversal.
- Score and confidence are explainable and stable enough for tests.
- Diff edge cases have visible structured outcomes instead of silent loss.

Costs:

- Some endpoint names differ from the broader list in `PROJECT_SPEC.md`; the ADR intentionally narrows V1 to a smaller stable surface.
- Scoring weights are provisional and must be validated with fixture repositories.
- Dynamic Python behavior is intentionally under-modeled in V1.

### 16. Follow-Up Work

P0 should create the backend and frontend skeleton around these contracts without implementing the analysis engine.

P0.5 should add:

- `backend/app/api/schemas.py` with Pydantic models matching this ADR.
- `backend/app/db/models.py` or `backend/app/models/` ORM models matching this ADR.
- README setup and run commands.

P1 to P5 should not change these contracts unless a new ADR updates this decision.
