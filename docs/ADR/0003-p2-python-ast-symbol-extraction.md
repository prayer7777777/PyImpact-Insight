# ADR 0003: P2 Python AST Symbol Extraction

## Status

Accepted

## Date

2026-04-14

## Context

P1 added SQLite-backed repository and analysis persistence. P2 introduces the first real analysis step: scanning Python files and extracting a static symbol/index graph with `ast`.

P2 must remain inside the V1 boundary. It must not implement Git diff, change mapping, call graph extraction, impact propagation, scoring, coverage, or test recommendation.

## Decision

### File Scanning

An analysis scans the registered repository root recursively for `.py` files.

The scanner ignores these directory names anywhere in the tree:

- `.git`
- `.venv`
- `venv`
- `node_modules`
- `dist`
- `build`
- `__pycache__`

Each scanned Python file creates one `CodeFile` row with:

- repository ID
- analysis ID
- repository-relative POSIX path
- module name
- content hash
- parse status
- optional parse error message

### Parse Failure Handling

`SyntaxError` and source read errors are local file failures.

Rules:

- A failed file is recorded as `parse_failed`.
- A failed file does not create module, symbol, or edge rows.
- A failed file increments `parse_failed_files`.
- Local parse failures do not make the overall analysis `FAILED`.
- The analysis includes a `PYTHON_PARSE_FAILED` warning when one or more files fail to parse.

### Symbol Extraction

P2 extracts:

- `module`
- `class`
- `function`
- `async_function`
- `method`
- `async_method`
- `staticmethod`
- `classmethod`
- `test_function`
- `test_method`

The symbol qualified name is `module.name` for top-level symbols and `module.Class.method` for methods.

P2 intentionally does not separately model:

- lambda expressions
- nested functions inside functions
- dynamically generated functions
- monkey patch targets
- runtime import targets
- framework-specific dependency injection targets

### Edge Extraction

P2 persists:

- `contains`: module/class -> child symbol
- `imports`: importer module -> imported repository module
- `inherits`: subclass -> base class, when the base can be resolved unambiguously

P2 does not persist:

- `calls`
- `tests`
- heuristic proximity edges
- name similarity edges

Import edges are written only when the imported target resolves to a Python module scanned in the same repository. Standard library, third-party, and unresolved imports are skipped.

### Summary Fields

P2 extends the analysis summary with:

- `scanned_files`
- `parsed_files`
- `parse_failed_files`
- `extracted_symbols`
- `extracted_edges`

Existing impact-oriented summary fields remain present and are zero in P2:

- `changed_files`
- `changed_symbols`
- `impacted_symbols`
- `recommended_tests`
- `skipped_files`
- `parse_failures`

`parse_failures` mirrors `parse_failed_files` for backward compatibility with the P0/P1 response shape.

### Analysis Lifecycle

P2 preserves the P1 lifecycle:

- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`

Normal parse failures leave the task as `COMPLETED`. The task is `FAILED` only when orchestration or persistence itself fails.

## Consequences

- The database now contains `CodeFile`, `Symbol`, and `Edge` rows after an analysis.
- The report can show extraction statistics.
- P2 provides the foundation for P3 graph construction, but it is not an impact-analysis engine yet.
- Existing SQLite databases created before P2 may need to be recreated in local development because migrations are still deferred.
