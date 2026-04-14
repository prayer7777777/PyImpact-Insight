from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.api.schemas import DiffMode, FileChangeType


@dataclass(frozen=True)
class GitDiffError(Exception):
    code: str
    message: str
    details: dict[str, str]


@dataclass(frozen=True)
class ChangedLineRange:
    start_line: int
    end_line: int


@dataclass
class ChangedFile:
    path: str
    change_type: FileChangeType
    old_path: str | None = None
    line_ranges: list[ChangedLineRange] = field(default_factory=list)
    is_binary: bool = False
    is_untracked: bool = False

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py") or bool(self.old_path and self.old_path.endswith(".py"))


@dataclass(frozen=True)
class GitDiffResult:
    files: list[ChangedFile]


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


class GitDiffReader:
    def read(
        self,
        *,
        repo_path: str,
        diff_mode: DiffMode,
        commit_from: str | None,
        commit_to: str | None,
        base_ref: str | None,
        head_ref: str | None,
        include_untracked: bool,
    ) -> GitDiffResult:
        root = Path(repo_path)
        self._ensure_head_if_needed(root, diff_mode)
        if diff_mode == DiffMode.WORKING_TREE:
            files = self._read_working_tree(root, include_untracked)
        elif diff_mode == DiffMode.COMMIT_RANGE:
            if commit_from is None or commit_to is None:
                raise GitDiffError(
                    code="INVALID_REQUEST",
                    message="commit_from and commit_to are required for commit_range.",
                    details={},
                )
            patch = self._run_git(
                root,
                ["diff", "--no-ext-diff", "--find-renames", "--unified=0", "--binary", commit_from, commit_to, "--"],
            )
            files = parse_git_patch(patch)
        elif diff_mode == DiffMode.REFS_COMPARE:
            if base_ref is None or head_ref is None:
                raise GitDiffError(
                    code="INVALID_REQUEST",
                    message="base_ref and head_ref are required for refs_compare.",
                    details={},
                )
            merge_base = self._run_git(root, ["merge-base", base_ref, head_ref]).strip()
            patch = self._run_git(
                root,
                ["diff", "--no-ext-diff", "--find-renames", "--unified=0", "--binary", merge_base, head_ref, "--"],
            )
            files = parse_git_patch(patch)
        else:
            raise GitDiffError(
                code="INVALID_DIFF_MODE",
                message=f"Unsupported diff_mode: {diff_mode}",
                details={"diff_mode": str(diff_mode)},
            )
        return GitDiffResult(files=files)

    def _read_working_tree(self, root: Path, include_untracked: bool) -> list[ChangedFile]:
        patch = self._run_git(
            root,
            ["diff", "--no-ext-diff", "--find-renames", "--unified=0", "--binary", "HEAD", "--"],
        )
        files = parse_git_patch(patch)
        if include_untracked:
            files.extend(self._read_untracked_files(root))
        return files

    def _read_untracked_files(self, root: Path) -> list[ChangedFile]:
        output = self._run_git(root, ["ls-files", "--others", "--exclude-standard"])
        files: list[ChangedFile] = []
        for path in [line.strip() for line in output.splitlines() if line.strip()]:
            absolute_path = root / path
            is_binary = _is_binary_file(absolute_path)
            line_ranges: list[ChangedLineRange] = []
            if not is_binary:
                line_count = _count_text_lines(absolute_path)
                line_ranges.append(ChangedLineRange(start_line=1, end_line=line_count))
            files.append(
                ChangedFile(
                    path=path,
                    old_path=None,
                    change_type=FileChangeType.ADDED,
                    line_ranges=line_ranges,
                    is_binary=is_binary,
                    is_untracked=True,
                )
            )
        return files

    def _ensure_head_if_needed(self, root: Path, diff_mode: DiffMode) -> None:
        if diff_mode != DiffMode.WORKING_TREE:
            return
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GitDiffError(
                code="REPOSITORY_HAS_NO_COMMITS",
                message="working_tree diff requires the repository to have at least one commit.",
                details={"repo_path": str(root)},
            )

    def _run_git(self, root: Path, args: list[str]) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        stderr = result.stderr.strip()
        raise GitDiffError(
            code="INVALID_REF",
            message=stderr or "Git command failed while reading diff.",
            details={"command": " ".join(["git", *args])},
        )


def parse_git_patch(patch: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    current: ChangedFile | None = None

    for line in patch.splitlines():
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            if current is not None:
                files.append(_finalize_changed_file(current))
            old_path, new_path = header_match.groups()
            current = ChangedFile(
                path=_unescape_git_path(new_path),
                old_path=_unescape_git_path(old_path),
                change_type=FileChangeType.MODIFIED,
            )
            continue

        if current is None:
            continue

        if line.startswith("new file mode"):
            current.change_type = FileChangeType.ADDED
            current.old_path = None
            continue
        if line.startswith("deleted file mode"):
            current.change_type = FileChangeType.DELETED
            current.path = current.old_path or current.path
            continue
        if line.startswith("rename from "):
            current.old_path = _unescape_git_path(line.removeprefix("rename from "))
            current.change_type = FileChangeType.RENAMED
            continue
        if line.startswith("rename to "):
            current.path = _unescape_git_path(line.removeprefix("rename to "))
            current.change_type = FileChangeType.RENAMED
            continue
        if line.startswith("Binary files ") or line == "GIT binary patch":
            current.is_binary = True
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            current.line_ranges.append(_line_range_from_hunk(current.change_type, hunk_match))

    if current is not None:
        files.append(_finalize_changed_file(current))

    return files


def _line_range_from_hunk(change_type: FileChangeType, hunk_match: re.Match[str]) -> ChangedLineRange:
    old_start = int(hunk_match.group("old_start"))
    old_count = _hunk_count(hunk_match.group("old_count"))
    new_start = int(hunk_match.group("new_start"))
    new_count = _hunk_count(hunk_match.group("new_count"))

    if change_type == FileChangeType.DELETED or new_count == 0:
        start = max(1, old_start)
        count = max(1, old_count)
    else:
        start = max(1, new_start)
        count = max(1, new_count)
    return ChangedLineRange(start_line=start, end_line=start + count - 1)


def _hunk_count(value: str | None) -> int:
    if value is None:
        return 1
    return int(value)


def _finalize_changed_file(file: ChangedFile) -> ChangedFile:
    if file.change_type != FileChangeType.DELETED and file.old_path == file.path:
        file.old_path = None
    if file.is_binary:
        file.line_ranges.clear()
    return file


def _unescape_git_path(path: str) -> str:
    return path.strip().strip('"')


def _is_binary_file(path: Path) -> bool:
    try:
        return b"\0" in path.read_bytes()[:8192]
    except OSError:
        return True


def _count_text_lines(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 1
    except OSError:
        return 1
    return max(1, len(text.splitlines()))
