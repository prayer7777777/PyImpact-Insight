# ADR 0004: P3 Git Diff and Changed Symbol Mapping

## Status

Accepted

## Date

2026-04-14

## Context

P2 scans Python files with `ast` and persists `CodeFile`, `Symbol`, and `Edge` records. P3 adds the next pipeline step: read Git changes, compute changed line ranges, and map those ranges to persisted Python symbols.

P3 is still not an impact analysis engine. It must not add call graph extraction, impact propagation, scoring, coverage, or test recommendation logic.

## Decision

### Diff Modes

P3 supports the three ADR 0001 diff modes:

| Mode | Behavior |
| --- | --- |
| `working_tree` | Reads `git diff HEAD --` with rename detection and zero context. This includes staged and unstaged tracked changes. `include_untracked=true` adds files from `git ls-files --others --exclude-standard`. The repository must have at least one commit. |
| `commit_range` | Reads a direct diff from `commit_from` to `commit_to`. |
| `refs_compare` | Resolves `merge-base(base_ref, head_ref)` and diffs that merge base against `head_ref`. |

Invalid refs fail the analysis with `INVALID_REF`. A `working_tree` analysis in a repository with no commits fails with `REPOSITORY_HAS_NO_COMMITS`.

### Changed Files and Line Ranges

Every changed file detected by Git contributes to `changed_files`.

Line range rules:

- Added, modified, and renamed file hunks use target-side line numbers.
- Pure deletion hunks and deleted files use base-side line numbers.
- Binary files are counted as changed files but do not produce line ranges.
- Non-Python files are counted but skipped for symbol mapping.
- Untracked text files use a whole-file range from line `1` to the current line count.

### Python-Only Mapping

Only paths ending in `.py` are mapped to symbols.

Mapping rules:

- A changed line hits a symbol when the line is inside `start_line <= line <= end_line`.
- Module-level hits are retained whenever the changed range overlaps the module symbol.
- For nested non-module hits on the same changed line, P3 keeps the innermost symbol.
- A changed range can therefore produce both a module-level `ChangedSymbol` and one or more innermost changed symbols.
- A Python line range with no mapped symbol is persisted as an unmapped change.

Common unmapped cases:

- deleted Python file whose target-side symbols are unavailable
- parse-failed Python file
- Python change outside any persisted symbol

### Persistence

P3 adds two persisted artifact types:

- `ChangeSpan`: one changed file/range record, including path, optional old path, change type, line range, binary flag, Python flag, and unmapped flag.
- `ChangedSymbol`: one deduplicated changed symbol record per analysis, including symbol key, symbol kind, file path, change type, symbol range, and whether it is module-level.

P3 keeps `Impact` and `TestRecommendation` empty.

### Summary Fields

P3 extends `AnalysisSummary` with:

- `changed_files`
- `changed_python_files`
- `changed_symbols`
- `unmapped_changes`

`skipped_files` counts changed files skipped for mapping because they are non-Python or binary.

P2 extraction fields remain present:

- `scanned_files`
- `parsed_files`
- `parse_failed_files`
- `extracted_symbols`
- `extracted_edges`

### Limitations

P3 parses the repository's current working tree and maps Git diff line ranges against those current symbols. For `commit_range` and `refs_compare`, results are most accurate when the working tree is checked out at `commit_to` or `head_ref`. Snapshot parsing for arbitrary historical refs is deferred.

P3 intentionally does not implement:

- `CALLS` edges
- impact propagation
- scoring or confidence output
- explanation paths
- coverage-backed test recommendation
- multi-language analysis

## Consequences

- A completed analysis now persists `ChangeSpan` and `ChangedSymbol` rows when Git reports changes.
- The analysis detail and report can show changed symbol records.
- Existing local SQLite databases created before P3 may need to be recreated because migrations are still deferred.
