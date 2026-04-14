# AGENTS.md

## Project identity
- Project: Python repo change-impact analyzer
- Primary goal: map code changes to impacted symbols and tests with explanations
- Stage: V1 only, Python-only

## Non-goals
- No multi-language support
- No deep interprocedural data-flow engine
- No IDE/LSP replacement
- No hidden background services without explicit need

## Working agreements
- Read docs/PROJECT_SPEC.md before changing code
- Keep modules small and single-purpose
- Prefer explicit types and dataclasses / pydantic models where appropriate
- Do not introduce new production dependencies unless clearly justified in the task result
- Always update tests when behavior changes
- Always update docs when APIs or data contracts change
- Keep all user-facing scoring output explainable

## Architecture rules
- backend/app/api: HTTP endpoints and request/response schemas only
- backend/app/services: orchestration only
- backend/app/analyzers: parsing, graph building, diff mapping, scoring
- backend/app/repositories: persistence access only
- backend/app/models: ORM and domain models
- frontend/src/pages: route-level views
- frontend/src/components: reusable UI blocks
- docs/: specifications, ADRs, user manual, soft-copy-prep notes

## Code quality
- Python: use ruff + pytest; add mypy-friendly annotations where reasonable
- Frontend: keep components focused and typed
- Never swallow exceptions silently
- Return structured errors with human-readable messages

## Verification
- For backend changes run: pytest
- For parser/graph/scoring changes add focused fixture tests
- For API changes update OpenAPI docs or response models
- For frontend changes verify key pages render and empty/error states work

## Definition of done
- Code compiles/runs
- Relevant tests pass
- New behavior is documented
- Known limitations are stated explicitly
- Final output includes changed files, why they changed, and what remains risky
