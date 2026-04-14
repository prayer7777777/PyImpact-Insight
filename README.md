# B-Impact

B-Impact is the V1 skeleton for a Python repository change-impact analyzer. P3 provides repository registration, SQLite persistence, analysis task lifecycle storage, Python file scanning, AST-based symbol extraction, basic structural/import/inheritance edges, Git diff reading, changed line ranges, changed symbol mapping, and a Markdown report path without implementing call graph extraction, impact propagation, scoring, coverage, or test recommendation logic.

The implementation follows:

- `AGENTS.md`
- `docs/PROJECT_SPEC.md`
- `docs/ADR/0001-v1-scope-and-contracts.md`
- `docs/ADR/0002-p1-persistence-and-analysis-status.md`
- `docs/ADR/0003-p2-python-ast-symbol-extraction.md`
- `docs/ADR/0004-p3-git-diff-and-changed-symbol-mapping.md`

## Current Scope

P3 includes:

- FastAPI backend under `backend/`
- Pydantic schemas aligned with ADR 0001 through ADR 0004
- SQLAlchemy ORM models for `Repository`, `Analysis`, `CodeFile`, `Symbol`, `Edge`, `ChangeSpan`, `ChangedSymbol`, `Impact`, and `TestRecommendation`
- SQLite persistence for repository, analysis, scanned file, symbol, edge, change span, and changed symbol records
- Minimum repository path validation
- Analysis lifecycle storage with `PENDING`, `RUNNING`, `COMPLETED`, and `FAILED`
- Recursive Python file scanning with common generated/dependency directories ignored
- AST extraction for modules, classes, functions, async functions, methods, static methods, class methods, and pytest-style tests
- `contains`, `imports`, and simple `inherits` edges
- Local `SyntaxError` handling that records `parse_failed` files without failing the whole analysis
- Git diff reading for `working_tree`, `commit_range`, and `refs_compare`
- Changed file and changed line range persistence
- Python-only changed symbol mapping with module-level hits and innermost symbol priority
- Unmapped change records for Python ranges that cannot be mapped to a persisted symbol
- Versioned API routes under `/api/v1`
- React + Vite frontend under `frontend/`
- Health endpoint, repository registration, analysis creation, analysis detail, and Markdown report routes
- Backend tests for health, repository registration, validation errors, analysis creation/querying, report output, symbol extraction, import edges, local parse failures, Git diff modes, changed symbol mapping, unmapped changes, and added/deleted file behavior

P3 does not include:

- call graph extraction
- impact propagation
- impact scoring
- coverage-backed test recommendation
- multi-language support

## Requirements

- Python 3.11+
- Node.js 20+
- npm 10+

This workspace currently uses `python3` rather than `python`.

## Backend Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e "backend[dev]"
```

Copy the environment template if you want to override defaults:

```bash
cp .env.example .env
```

The default backend database is SQLite:

```text
backend/data/b-impact.sqlite3
```

Tables are created automatically when the FastAPI app starts. You can also initialize them without starting the server:

```bash
cd backend
python3 -c "from app.db.session import init_db; init_db()"
```

Local development note: migrations are deferred while the model surface is still changing. If you have a database created before P3, recreate it by removing `backend/data/b-impact.sqlite3` and starting the backend again.

Start the API:

```bash
cd backend
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Useful backend URLs:

- Health: `http://127.0.0.1:8000/api/v1/health`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Swagger UI: `http://127.0.0.1:8000/docs`

Expected health response:

```json
{"status":"ok"}
```

Run backend tests:

```bash
cd backend
python3 -m pytest
```

## Frontend Setup

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies `/api` requests to `http://127.0.0.1:8000`.

## API Flow

Create a repository record:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/repositories \
  -H "Content-Type: application/json" \
  -d '{"name":"sample-service","repo_path":"/absolute/path/to/repo","main_branch":"main"}'
```

The repository path must exist, be a readable directory, and contain a readable `.git` entry.

Start an analysis record:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{
    "repository_id": "replace-with-repository-uuid",
    "diff_mode": "working_tree",
    "include_untracked": false,
    "options": {
      "max_depth": 4,
      "include_tests": true,
      "use_coverage": false
    }
  }'
```

The accepted response returns `PENDING`. P3 then scans Python files, extracts symbols and supported edges, reads Git diff data, maps changed Python line ranges to symbols, records local parse failures or unmapped changes, and stores the analysis as `COMPLETED` unless orchestration or persistence fails.

Supported diff modes:

- `working_tree`: compares tracked staged and unstaged changes against `HEAD`; set `include_untracked` to include untracked files.
- `commit_range`: compares `commit_from` directly to `commit_to`.
- `refs_compare`: compares `merge-base(base_ref, head_ref)` to `head_ref`.

`working_tree` requires at least one Git commit.

Read the analysis:

```bash
curl http://127.0.0.1:8000/api/v1/analyses/replace-with-analysis-uuid
```

Read the Markdown report:

```bash
curl http://127.0.0.1:8000/api/v1/analyses/replace-with-analysis-uuid/report
```

The analysis result includes diff and mapping summary fields:

- `changed_files`
- `changed_python_files`
- `changed_symbols`
- `unmapped_changes`

The analysis result also includes extraction summary fields:

- `scanned_files`
- `parsed_files`
- `parse_failed_files`
- `extracted_symbols`
- `extracted_edges`

Impact-oriented fields remain zero in P3 because impact propagation, scoring, coverage, and test recommendation are not implemented.

## Development Notes

- Keep API schemas aligned with `docs/ADR/0001-v1-scope-and-contracts.md`.
- Keep P1 persistence and status behavior aligned with `docs/ADR/0002-p1-persistence-and-analysis-status.md`.
- Keep P2 parser behavior aligned with `docs/ADR/0003-p2-python-ast-symbol-extraction.md`.
- Keep P3 diff mapping behavior aligned with `docs/ADR/0004-p3-git-diff-and-changed-symbol-mapping.md`.
- Do not add impact propagation, scoring, coverage, or test recommendation logic in P3.
- Do not add multi-language support.
- Backend errors use the ADR error envelope with `error.code`, `error.message`, `error.details`, and `error.request_id`.
