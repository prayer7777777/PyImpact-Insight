# ADR 0002: P1 Persistence and Analysis Status

## Status

Accepted

## Date

2026-04-14

## Context

ADR 0001 froze the P0 API surface and placeholder contracts. P1 replaces the in-memory repository and analysis store with SQLite-backed SQLAlchemy persistence and adds minimum real repository validation.

P1 still does not implement Git diff, AST parsing, graph construction, scoring, coverage, or test recommendation logic.

## Decision

### Database

The backend uses SQLite through SQLAlchemy.

Default database URL:

```text
sqlite:///./data/b-impact.sqlite3
```

The application creates the required tables at startup with `Base.metadata.create_all`. Alembic migrations are deferred until the model surface stabilizes beyond P1.

### Repository Validation

`POST /api/v1/repositories` validates that:

- `repo_path` exists
- `repo_path` is a directory
- `repo_path` is readable
- `repo_path/.git` exists
- `repo_path/.git` is readable

The service stores the resolved absolute path. If the same resolved path is already registered, the existing repository record is returned.

### Analysis Lifecycle

P1 uses these persisted analysis statuses:

- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`

`POST /api/v1/analyses` writes an analysis row as `PENDING`, moves it to `RUNNING`, then completes a no-op analysis as `COMPLETED`. The no-op result has zero summary counts and a `P1_NO_ANALYSIS_ENGINE` warning.

`FAILED` is reserved for errors during task orchestration. Since P1 does not run an analysis engine, normal successful requests complete without producing impacts or test recommendations.

### Report Source

`GET /api/v1/analyses/{analysis_id}/report` renders Markdown from persisted repository and analysis rows, including:

- analysis ID
- repository ID
- repository name and path
- main branch
- status
- diff mode
- timestamps
- summary counts
- P1 limitation warning

## Consequences

- API route paths remain unchanged from ADR 0001.
- Status values are explicit lifecycle states in P1 rather than the P0 placeholder `queued` wording.
- Repository and analysis records persist across service restarts as long as the SQLite file is retained.
- P1 intentionally creates no `Impact` or `TestRecommendation` rows.
