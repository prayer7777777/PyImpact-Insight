from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_COVERAGE_PATHS = (
    "coverage.json",
    "coverage/coverage.json",
)


@dataclass(frozen=True)
class CoverageLoadResult:
    status: str
    source_path: str | None
    contexts_by_file: dict[str, dict[int, tuple[str, ...]]]

    @property
    def has_contexts(self) -> bool:
        return any(line_contexts for line_contexts in self.contexts_by_file.values())


def load_coverage_contexts(repo_path: str) -> CoverageLoadResult:
    root = Path(repo_path)
    for relative_path in SUPPORTED_COVERAGE_PATHS:
        candidate = root / relative_path
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CoverageLoadResult(status="unusable", source_path=relative_path, contexts_by_file={})

        files = payload.get("files")
        if not isinstance(files, dict):
            return CoverageLoadResult(status="unusable", source_path=relative_path, contexts_by_file={})

        contexts_by_file: dict[str, dict[int, tuple[str, ...]]] = {}
        for file_path, file_payload in files.items():
            if not isinstance(file_path, str) or not isinstance(file_payload, dict):
                continue
            raw_contexts = file_payload.get("contexts", {})
            if not isinstance(raw_contexts, dict):
                continue

            line_contexts: dict[int, tuple[str, ...]] = {}
            for line_number, contexts in raw_contexts.items():
                try:
                    line_int = int(line_number)
                except (TypeError, ValueError):
                    continue
                if not isinstance(contexts, list):
                    continue
                normalized_contexts = tuple(
                    context
                    for context in contexts
                    if isinstance(context, str) and context.strip()
                )
                if normalized_contexts:
                    line_contexts[line_int] = normalized_contexts

            if line_contexts:
                normalized_path = Path(file_path).as_posix()
                contexts_by_file[normalized_path] = line_contexts

        return CoverageLoadResult(
            status="loaded" if contexts_by_file else "unusable",
            source_path=relative_path,
            contexts_by_file=contexts_by_file,
        )

    return CoverageLoadResult(status="missing", source_path=None, contexts_by_file={})
