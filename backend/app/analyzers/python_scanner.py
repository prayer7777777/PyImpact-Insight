from __future__ import annotations

import os
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}


def scan_python_files(repo_path: str) -> list[Path]:
    root = Path(repo_path)
    python_files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        current_path = Path(current_root)
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                python_files.append(current_path / filename)
    return sorted(python_files, key=lambda path: path.relative_to(root).as_posix())

