# B-Impact

B-Impact is the V1 implementation for a Python repository change-impact analyzer. P5.5 provides repository registration, SQLite persistence, analysis task lifecycle storage, Python file scanning, AST-based symbol extraction, Git diff reading, changed symbol mapping, baseline impact propagation, deterministic final impact scoring, and a frontend workbench that can create repositories, run analyses, and display real summary, impact, and report data without implementing call graph propagation, coverage, test recommendation ranking, or historical snapshot graphs.

The implementation follows:

- `AGENTS.md`
- `docs/PROJECT_SPEC.md`
- `docs/ADR/0001-v1-scope-and-contracts.md`
- `docs/ADR/0002-p1-persistence-and-analysis-status.md`
- `docs/ADR/0003-p2-python-ast-symbol-extraction.md`
- `docs/ADR/0004-p3-git-diff-and-changed-symbol-mapping.md`
- `docs/ADR/0005-p4-baseline-impact-propagation.md`
- `docs/ADR/0006-p5-impact-scoring-and-finalization.md`

## Current Scope

P5.5 includes:

- FastAPI backend under `backend/`
- Pydantic schemas aligned with ADR 0001 through ADR 0006
- SQLAlchemy ORM models for `Repository`, `Analysis`, `CodeFile`, `Symbol`, `Edge`, `ChangeSpan`, `ChangedSymbol`, `ImpactedSymbol`, `Impact`, and `TestRecommendation`
- SQLite persistence for repository, analysis, scanned file, symbol, edge, change span, changed symbol, and impacted symbol records
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
- Baseline impact propagation from changed symbols
- Reverse dependency traversal for `imports` and `inherits`
- Parent/child structural cascade for `contains`
- Persisted impacted symbol candidates with path, hop count, reason, and test flag
- Deterministic final impact scoring with seed scores, structural edge weights, hop decay, and test-symbol bonus
- Persisted final `Impact` rows with `score`, `confidence`, `reasons`, `explanation_path`, and `reasons_json`
- Multi-path merge into one final ranked result per target symbol
- Versioned API routes under `/api/v1`
- React + Vite frontend under `frontend/`
- Frontend workbench with repository creation, analysis creation, local recent-item history, analysis summary display, final impact list, and Markdown report viewer
- Health endpoint, repository registration, analysis creation, analysis detail, and Markdown report routes
- Backend tests for health, repository validation, analysis creation/querying, report output, symbol extraction, import edges, local parse failures, Git diff modes, changed symbol mapping, propagation over imports/inherits/contains, cycle handling, hop limits, impacted test detection, scoring weights, hop decay, multi-path merge, and added/deleted file behavior

P5.5 does not include:

- call graph extraction
- coverage-backed test recommendation
- test recommendation generation
- historical ref-specific symbol graphs
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

Local development note: migrations are deferred while the model surface is still changing. If you have a database created before P5.5, recreate it by removing `backend/data/b-impact.sqlite3` and starting the backend again.

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

Current frontend capability:

- create a repository from a local path
- run a real analysis against the current P5 backend
- reload a prior analysis by ID
- keep recent repositories and analyses in browser-local storage
- display summary metrics, ranked impacts, warnings, and the Markdown report

Current frontend limits:

- recent repository and analysis history is browser-local, not server-side list data
- there is no graph view, test suggestion panel, or coverage visualization yet
- there is no multi-page route structure yet; P5.5 is a focused single-page workbench

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

The accepted response returns `PENDING`. P5 then scans Python files, extracts symbols and supported edges, reads Git diff data, maps changed Python line ranges to symbols, generates baseline impacted symbol candidates, scores final impacts, records local parse failures or unmapped changes, and stores the analysis as `COMPLETED` unless orchestration or persistence fails. P5.5 renders those persisted results directly in the frontend workbench.

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

The analysis result includes diff, mapping, propagation, and scoring summary fields:

- `changed_files`
- `changed_python_files`
- `changed_symbols`
- `unmapped_changes`
- `impacted_symbols`
- `top_impacts`
- `high_confidence_impacts`
- `impacted_tests`
- `propagation_paths`

The analysis result also includes extraction summary fields:

- `scanned_files`
- `parsed_files`
- `parse_failed_files`
- `extracted_symbols`
- `extracted_edges`

Propagation and scoring rules in P5:

- `imports`: propagate in reverse from imported module to importer module
- `inherits`: propagate in reverse from base class to subclass
- `contains`: propagate both parent -> child and child -> parent as a structural cascade
- `max_depth`: limits breadth-first traversal hop count
- changed non-module symbol seed: `1.00`
- changed module symbol seed: `0.70`
- hop decay: `0.85`
- test symbol bonus: `0.05`
- `imports` weight: `0.80`
- `inherits` weight: `0.75`
- `contains` weight: `0.40`
- confidence thresholds: `high >= 0.75`, `medium >= 0.45`, otherwise `low`
- multiple paths merge into one final impact; public score keeps the best path score, then applies the optional test-symbol bonus

P5 and P5.5 return:

- `changed_symbols`: changed symbol records from diff mapping
- `impacted_symbols`: baseline candidate impacted symbols with source symbol, path, hop count, and traversed edge types
- `impacts`: final ranked impacts with `score`, `confidence`, merged reasons, explanation path, and explainable `reasons_json`

## Development Notes

- Keep API schemas aligned with `docs/ADR/0001-v1-scope-and-contracts.md`.
- Keep P1 persistence and status behavior aligned with `docs/ADR/0002-p1-persistence-and-analysis-status.md`.
- Keep P2 parser behavior aligned with `docs/ADR/0003-p2-python-ast-symbol-extraction.md`.
- Keep P3 diff mapping behavior aligned with `docs/ADR/0004-p3-git-diff-and-changed-symbol-mapping.md`.
- Keep P4 baseline propagation behavior aligned with `docs/ADR/0005-p4-baseline-impact-propagation.md`.
- Keep P5 final scoring behavior aligned with `docs/ADR/0006-p5-impact-scoring-and-finalization.md`.
- Do not add call graph propagation, coverage-backed scoring, test recommendation generation, or multi-language support in P5.5.
- Backend errors use the ADR error envelope with `error.code`, `error.message`, `error.details`, and `error.request_id`.
