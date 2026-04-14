from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import schemas
from app.db import models
from tests.api_client import request


def make_git_repository(path: Path) -> Path:
    path.mkdir()
    git_dir = path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return path


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
    assert result["warnings"][0]["code"] == "P2_NO_IMPACT_ENGINE"

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
    assert "P2 does not run Git diff" in report_response.text


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


def run_analysis_for_repo(repo_path: Path) -> dict:
    repo_response = asyncio.run(create_repository(repo_path))
    repository_id = repo_response.json()["repository_id"]
    analysis_response = asyncio.run(
        request(
            "POST",
            "/api/v1/analyses",
            json={"repository_id": repository_id, "diff_mode": "working_tree"},
        )
    )
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
