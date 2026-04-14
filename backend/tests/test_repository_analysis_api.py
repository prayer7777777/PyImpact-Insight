from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import schemas
from app.db import models
from tests.api_client import request


def run_git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_git_repository(path: Path) -> Path:
    path.mkdir()
    run_git(path, "init")
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "user.name", "Test User")
    run_git(path, "checkout", "-B", "main")
    run_git(path, "commit", "--allow-empty", "-m", "initial")
    return path


def commit_all(repo_path: Path, message: str) -> str:
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", message)
    return run_git(repo_path, "rev-parse", "HEAD")


def create_repository(repo_path: Path):
    return request(
        "POST",
        "/api/v1/repositories",
        json={"name": "sample-service", "repo_path": str(repo_path), "main_branch": "main"},
    )


def test_create_repository_success(tmp_path: Path, test_session_factory: sessionmaker[Session]) -> None:
    repo_path = make_git_repository(tmp_path / "repo")

    response = asyncio.run(create_repository(repo_path))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "sample-service"
    assert body["repo_path"] == str(repo_path.resolve())
    assert body["language"] == "python"

    with test_session_factory() as session:
        stored = session.get(models.Repository, body["repository_id"])
        assert stored is not None
        assert stored.repo_path == str(repo_path.resolve())


def test_create_repository_rejects_non_git_directory(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    non_git_path = tmp_path / "not-git"
    non_git_path.mkdir()

    response = asyncio.run(create_repository(non_git_path))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_A_GIT_REPOSITORY"


def test_create_and_get_analysis_success(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    repo_response = asyncio.run(create_repository(repo_path))
    repository_id = repo_response.json()["repository_id"]

    analysis_response = asyncio.run(
        request(
            "POST",
            "/api/v1/analyses",
            json={
                "repository_id": repository_id,
                "diff_mode": "working_tree",
                "include_untracked": False,
                "options": {"max_depth": 4, "include_tests": True, "use_coverage": False},
            },
        )
    )

    assert analysis_response.status_code == 202
    accepted = analysis_response.json()
    assert accepted["repository_id"] == repository_id
    assert accepted["status"] == "PENDING"

    result_response = asyncio.run(request("GET", f"/api/v1/analyses/{accepted['analysis_id']}"))

    assert result_response.status_code == 200
    result = result_response.json()
    assert result["status"] == "COMPLETED"
    assert result["summary"]["changed_files"] == 0
    assert result["warnings"][0]["code"] == "P3_NO_IMPACT_ENGINE"

    with test_session_factory() as session:
        stored = session.get(models.Analysis, accepted["analysis_id"])
        assert stored is not None
        assert stored.status == "COMPLETED"
        assert stored.repository_id == repository_id


def test_report_returns_markdown_from_persisted_records(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    repo_response = asyncio.run(create_repository(repo_path))
    repository_id = repo_response.json()["repository_id"]
    analysis_response = asyncio.run(
        request(
            "POST",
            "/api/v1/analyses",
            json={"repository_id": repository_id, "diff_mode": "working_tree"},
        )
    )
    analysis_id = analysis_response.json()["analysis_id"]

    report_response = asyncio.run(request("GET", f"/api/v1/analyses/{analysis_id}/report"))

    assert report_response.status_code == 200
    assert report_response.headers["content-type"].startswith("text/markdown")
    assert "# Change Impact Analysis Report" in report_response.text
    assert "sample-service" in report_response.text
    assert analysis_id in report_response.text
    assert "P3 does not run calls analysis" in report_response.text


def write_sample_python_package(repo_path: Path) -> None:
    package = repo_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "config.py").write_text(
        "\n".join(
            [
                "class Settings:",
                "    def as_dict(self):",
                "        return {}",
            ]
        ),
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        "\n".join(
            [
                "from pkg.config import Settings",
                "",
                "class Service(Settings):",
                "    def run(self):",
                "        return 'ok'",
                "",
                "    @staticmethod",
                "    def build():",
                "        return Service()",
                "",
                "async def load():",
                "    return Service()",
                "",
                "def helper():",
                "    return 'helper'",
                "",
                "def test_helper():",
                "    assert helper() == 'helper'",
            ]
        ),
        encoding="utf-8",
    )
    ignored = repo_path / "node_modules"
    ignored.mkdir()
    (ignored / "ignored.py").write_text("def should_not_scan(): pass", encoding="utf-8")


def run_analysis_for_repo(
    repo_path: Path,
    *,
    diff_mode: str = "working_tree",
    include_untracked: bool = False,
    commit_from: str | None = None,
    commit_to: str | None = None,
    base_ref: str | None = None,
    head_ref: str | None = None,
) -> dict:
    repo_response = asyncio.run(create_repository(repo_path))
    repository_id = repo_response.json()["repository_id"]
    payload = {
        "repository_id": repository_id,
        "diff_mode": diff_mode,
        "include_untracked": include_untracked,
    }
    if commit_from is not None:
        payload["commit_from"] = commit_from
    if commit_to is not None:
        payload["commit_to"] = commit_to
    if base_ref is not None:
        payload["base_ref"] = base_ref
    if head_ref is not None:
        payload["head_ref"] = head_ref
    analysis_response = asyncio.run(
        request(
            "POST",
            "/api/v1/analyses",
            json=payload,
        )
    )
    assert analysis_response.status_code == 202, analysis_response.text
    return analysis_response.json()


def test_analysis_scans_and_extracts_basic_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    write_sample_python_package(repo_path)

    accepted = run_analysis_for_repo(repo_path)
    result_response = asyncio.run(request("GET", f"/api/v1/analyses/{accepted['analysis_id']}"))
    result = result_response.json()

    assert result["status"] == "COMPLETED"
    assert result["summary"]["scanned_files"] == 3
    assert result["summary"]["parsed_files"] == 3
    assert result["summary"]["parse_failed_files"] == 0
    assert result["summary"]["extracted_symbols"] > 0
    assert result["summary"]["extracted_edges"] > 0

    with test_session_factory() as session:
        symbols = session.execute(
            select(models.Symbol).where(models.Symbol.analysis_id == accepted["analysis_id"])
        ).scalars()
        by_qualname = {symbol.qualname: symbol for symbol in symbols}
        assert "pkg.service" in by_qualname
        assert by_qualname["pkg.service"].kind == schemas.SymbolKind.MODULE.value
        assert "pkg.service.helper" in by_qualname
        assert by_qualname["pkg.service.helper"].kind == schemas.SymbolKind.FUNCTION.value
        assert "pkg.service.load" in by_qualname
        assert by_qualname["pkg.service.load"].kind == schemas.SymbolKind.ASYNC_FUNCTION.value
        assert "pkg.service.test_helper" in by_qualname
        assert by_qualname["pkg.service.test_helper"].kind == schemas.SymbolKind.TEST_FUNCTION.value


def test_analysis_persists_class_function_and_method_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    write_sample_python_package(repo_path)

    accepted = run_analysis_for_repo(repo_path)

    with test_session_factory() as session:
        symbols = session.execute(
            select(models.Symbol).where(models.Symbol.analysis_id == accepted["analysis_id"])
        ).scalars()
        by_qualname = {symbol.qualname: symbol for symbol in symbols}

    assert by_qualname["pkg.config.Settings"].kind == schemas.SymbolKind.CLASS.value
    assert by_qualname["pkg.config.Settings.as_dict"].kind == schemas.SymbolKind.METHOD.value
    assert by_qualname["pkg.service.Service"].kind == schemas.SymbolKind.CLASS.value
    assert by_qualname["pkg.service.Service.run"].kind == schemas.SymbolKind.METHOD.value
    assert by_qualname["pkg.service.Service.build"].kind == schemas.SymbolKind.STATICMETHOD.value


def test_analysis_generates_import_edge(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    write_sample_python_package(repo_path)

    accepted = run_analysis_for_repo(repo_path)

    with test_session_factory() as session:
        import_edges = session.execute(
            select(models.Edge).where(
                models.Edge.analysis_id == accepted["analysis_id"],
                models.Edge.edge_type == schemas.EdgeType.IMPORTS.value,
            )
        ).scalars()
        linked_pairs = [
            (session.get(models.Symbol, edge.src_symbol_id), session.get(models.Symbol, edge.dst_symbol_id))
            for edge in import_edges
        ]

    assert any(
        src is not None
        and dst is not None
        and src.qualname == "pkg.service"
        and dst.qualname == "pkg.config"
        for src, dst in linked_pairs
    )


def test_syntax_error_file_is_recorded_without_failing_analysis(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "good.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    (repo_path / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path)
    result_response = asyncio.run(request("GET", f"/api/v1/analyses/{accepted['analysis_id']}"))
    result = result_response.json()

    assert result["status"] == "COMPLETED"
    assert result["summary"]["scanned_files"] == 2
    assert result["summary"]["parsed_files"] == 1
    assert result["summary"]["parse_failed_files"] == 1
    assert any(warning["code"] == "PYTHON_PARSE_FAILED" for warning in result["warnings"])

    with test_session_factory() as session:
        files = session.execute(
            select(models.CodeFile).where(models.CodeFile.analysis_id == accepted["analysis_id"])
        ).scalars()
        by_path = {file.path: file for file in files}

    assert by_path["bad.py"].parse_status == schemas.ParseStatus.PARSE_FAILED.value
    assert by_path["good.py"].parse_status == schemas.ParseStatus.PARSED.value


def analysis_result(analysis_id: str) -> dict:
    result_response = asyncio.run(request("GET", f"/api/v1/analyses/{analysis_id}"))
    assert result_response.status_code == 200, result_response.text
    return result_response.json()


def changed_symbol_keys(result: dict) -> set[str]:
    return {item["symbol_key"] for item in result["changed_symbols"]}


def test_working_tree_diff_maps_changed_lines_to_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'old'\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add app")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'new'\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path)
    result = analysis_result(accepted["analysis_id"])

    assert result["summary"]["changed_files"] == 1
    assert result["summary"]["changed_python_files"] == 1
    assert result["summary"]["changed_symbols"] == 2
    assert changed_symbol_keys(result) == {"app.py::app", "app.py::app.target"}

    with test_session_factory() as session:
        rows = session.execute(
            select(models.ChangedSymbol).where(
                models.ChangedSymbol.analysis_id == accepted["analysis_id"]
            )
        ).scalars()
        assert {row.symbol_key for row in rows} == {"app.py::app", "app.py::app.target"}


def test_commit_range_diff_maps_changed_lines_to_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'old'\n",
        encoding="utf-8",
    )
    commit_from = commit_all(repo_path, "add app")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'new'\n",
        encoding="utf-8",
    )
    commit_to = commit_all(repo_path, "update app")

    accepted = run_analysis_for_repo(
        repo_path,
        diff_mode="commit_range",
        commit_from=commit_from,
        commit_to=commit_to,
    )
    result = analysis_result(accepted["analysis_id"])

    assert result["summary"]["changed_files"] == 1
    assert result["summary"]["changed_symbols"] == 2
    assert "app.py::app.target" in changed_symbol_keys(result)


def test_refs_compare_diff_maps_changed_lines_to_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'base'\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add app")
    run_git(repo_path, "checkout", "-b", "feature")
    (repo_path / "app.py").write_text(
        "def target():\n    return 'feature'\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "feature change")

    accepted = run_analysis_for_repo(
        repo_path,
        diff_mode="refs_compare",
        base_ref="main",
        head_ref="feature",
    )
    result = analysis_result(accepted["analysis_id"])

    assert result["summary"]["changed_files"] == 1
    assert result["summary"]["changed_symbols"] == 2
    assert "app.py::app.target" in changed_symbol_keys(result)


def test_nested_symbol_mapping_prefers_innermost_symbol(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "app.py").write_text(
        "\n".join(
            [
                "class Service:",
                "    def run(self):",
                "        return 'old'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add service")
    (repo_path / "app.py").write_text(
        "\n".join(
            [
                "class Service:",
                "    def run(self):",
                "        return 'new'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path)
    result = analysis_result(accepted["analysis_id"])
    keys = changed_symbol_keys(result)

    assert "app.py::app" in keys
    assert "app.py::app.Service.run" in keys
    assert "app.py::app.Service" not in keys


def test_unmapped_change_is_recorded_for_parse_failed_python_file(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "bad.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    commit_all(repo_path, "add valid file")
    (repo_path / "bad.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path)
    result = analysis_result(accepted["analysis_id"])

    assert result["status"] == "COMPLETED"
    assert result["summary"]["changed_files"] == 1
    assert result["summary"]["changed_python_files"] == 1
    assert result["summary"]["unmapped_changes"] >= 1
    assert result["summary"]["parse_failed_files"] == 1

    with test_session_factory() as session:
        spans = session.execute(
            select(models.ChangeSpan).where(
                models.ChangeSpan.analysis_id == accepted["analysis_id"],
                models.ChangeSpan.path == "bad.py",
            )
        ).scalars()
        assert any(span.is_unmapped for span in spans)


def test_added_and_deleted_python_files_are_recorded(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "old.py").write_text("def old():\n    return 'old'\n", encoding="utf-8")
    commit_all(repo_path, "add old")
    (repo_path / "old.py").unlink()
    (repo_path / "new.py").write_text("def new():\n    return 'new'\n", encoding="utf-8")
    run_git(repo_path, "add", "new.py")

    accepted = run_analysis_for_repo(repo_path)
    result = analysis_result(accepted["analysis_id"])

    assert result["summary"]["changed_files"] == 2
    assert result["summary"]["changed_python_files"] == 2
    assert "new.py::new.new" in changed_symbol_keys(result)

    with test_session_factory() as session:
        spans = session.execute(
            select(models.ChangeSpan).where(
                models.ChangeSpan.analysis_id == accepted["analysis_id"]
            )
        ).scalars()
        by_path = {span.path: span for span in spans}

    assert by_path["new.py"].change_type == schemas.FileChangeType.ADDED.value
    assert by_path["old.py"].change_type == schemas.FileChangeType.DELETED.value
    assert by_path["old.py"].is_unmapped
