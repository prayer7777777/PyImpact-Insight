from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api import schemas
from app.core.errors import ApiError
from app.db import models
from app.services.analysis_service import AnalysisService
from app.services.repository_service import RepositoryService


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


def create_repository(repo_path: Path, session_factory: sessionmaker[Session]) -> dict:
    with session_factory() as session:
        result = RepositoryService(session).create_repository(
            schemas.RepositoryCreate(
                name="sample-service",
                repo_path=str(repo_path),
                main_branch="main",
            )
        )
    return result.model_dump(mode="json")


def create_analysis(
    repository_id: str,
    session_factory: sessionmaker[Session],
    *,
    diff_mode: str = "working_tree",
    include_untracked: bool = False,
    max_depth: int = 4,
    commit_from: str | None = None,
    commit_to: str | None = None,
    base_ref: str | None = None,
    head_ref: str | None = None,
) -> dict:
    payload = {
        "repository_id": repository_id,
        "diff_mode": diff_mode,
        "include_untracked": include_untracked,
        "options": {"max_depth": max_depth, "include_tests": True, "use_coverage": False},
    }
    if commit_from is not None:
        payload["commit_from"] = commit_from
    if commit_to is not None:
        payload["commit_to"] = commit_to
    if base_ref is not None:
        payload["base_ref"] = base_ref
    if head_ref is not None:
        payload["head_ref"] = head_ref

    with session_factory() as session:
        accepted = AnalysisService(session).create_analysis(schemas.AnalysisCreate(**payload))
    return accepted.model_dump(mode="json")


def get_analysis_result(analysis_id: str, session_factory: sessionmaker[Session]) -> dict:
    with session_factory() as session:
        result = AnalysisService(session).get_analysis(analysis_id)
    return result.model_dump(mode="json")


def get_report_content(analysis_id: str, session_factory: sessionmaker[Session]) -> str:
    with session_factory() as session:
        return AnalysisService(session).get_report(analysis_id)


def test_create_repository_success(tmp_path: Path, test_session_factory: sessionmaker[Session]) -> None:
    repo_path = make_git_repository(tmp_path / "repo")

    body = create_repository(repo_path, test_session_factory)
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

    with pytest.raises(ApiError) as exc_info:
        create_repository(non_git_path, test_session_factory)

    assert exc_info.value.code == "NOT_A_GIT_REPOSITORY"


def test_create_and_get_analysis_success(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    repo_record = create_repository(repo_path, test_session_factory)
    repository_id = repo_record["repository_id"]
    accepted = create_analysis(repository_id, test_session_factory)
    assert accepted["repository_id"] == repository_id
    assert accepted["status"] == "PENDING"

    result = get_analysis_result(accepted["analysis_id"], test_session_factory)
    assert result["status"] == "COMPLETED"
    assert result["summary"]["changed_files"] == 0
    assert result["warnings"][0]["code"] == "P5_LIMITED_IMPACT_ENGINE"

    with test_session_factory() as session:
        stored = session.get(models.Analysis, accepted["analysis_id"])
        assert stored is not None
        assert stored.status == "COMPLETED"
        assert stored.repository_id == repository_id


def test_report_returns_markdown_from_persisted_records(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    repo_record = create_repository(repo_path, test_session_factory)
    analysis_record = create_analysis(repo_record["repository_id"], test_session_factory)
    analysis_id = analysis_record["analysis_id"]

    report = get_report_content(analysis_id, test_session_factory)

    assert "# Change Impact Analysis Report" in report
    assert "sample-service" in report
    assert analysis_id in report
    assert "P5 does not run calls analysis" in report


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
    session_factory: sessionmaker[Session],
    *,
    diff_mode: str = "working_tree",
    include_untracked: bool = False,
    max_depth: int = 4,
    commit_from: str | None = None,
    commit_to: str | None = None,
    base_ref: str | None = None,
    head_ref: str | None = None,
) -> dict:
    repo_record = create_repository(repo_path, session_factory)
    return create_analysis(
        repo_record["repository_id"],
        session_factory,
        diff_mode=diff_mode,
        include_untracked=include_untracked,
        max_depth=max_depth,
        commit_from=commit_from,
        commit_to=commit_to,
        base_ref=base_ref,
        head_ref=head_ref,
    )


def test_analysis_scans_and_extracts_basic_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    write_sample_python_package(repo_path)

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = get_analysis_result(accepted["analysis_id"], test_session_factory)

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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)

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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)

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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = get_analysis_result(accepted["analysis_id"], test_session_factory)

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


def analysis_result(analysis_id: str, session_factory: sessionmaker[Session]) -> dict:
    return get_analysis_result(analysis_id, session_factory)


def changed_symbol_keys(result: dict) -> set[str]:
    return {item["symbol_key"] for item in result["changed_symbols"]}


def impacted_symbol_keys(result: dict) -> set[str]:
    return {item["symbol_key"] for item in result["impacted_symbols"]}


def impacts_by_key(result: dict) -> dict[str, dict]:
    return {item["symbol_key"]: item for item in result["impacts"]}


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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)

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
        test_session_factory,
        diff_mode="commit_range",
        commit_from=commit_from,
        commit_to=commit_to,
    )
    result = analysis_result(accepted["analysis_id"], test_session_factory)

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
        test_session_factory,
        diff_mode="refs_compare",
        base_ref="main",
        head_ref="feature",
    )
    result = analysis_result(accepted["analysis_id"], test_session_factory)

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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)

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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)

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


def test_imports_propagation_generates_impacted_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "core.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    (repo_path / "consumer.py").write_text(
        "import core\n\n\ndef use():\n    return core.target()\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add import chain")
    (repo_path / "core.py").write_text("def target():\n    return 'new'\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    keys = impacted_symbol_keys(result)

    assert "consumer.py::consumer" in keys
    assert "consumer.py::consumer.use" in keys
    assert result["summary"]["impacted_symbols"] >= 2
    assert result["summary"]["propagation_paths"] >= 2


def test_inherits_propagation_generates_impacted_symbols(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "base.py").write_text(
        "\n".join(
            [
                "class Base:",
                "    def run(self):",
                "        return 'old'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_path / "child.py").write_text(
        "from base import Base\n\n\nclass Child(Base):\n    pass\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add base and child")
    (repo_path / "base.py").write_text(
        "\n".join(
            [
                "class Base:",
                "    def run(self):",
                "        return 'new'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacted = {item["symbol_key"]: item for item in result["impacted_symbols"]}

    assert "base.py::base.Base" in impacted
    assert "child.py::child.Child" in impacted
    assert "reverse_inherits" in impacted["child.py::child.Child"]["impact_reason"]


def test_contains_cascade_impacts_parent_symbols(
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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacted = {item["symbol_key"]: item for item in result["impacted_symbols"]}

    assert "app.py::app.Service" in impacted
    assert impacted["app.py::app.Service"]["hop_count"] == 1
    assert "reverse_contains" in impacted["app.py::app.Service"]["impact_reason"]


def test_propagation_handles_import_cycles_without_looping(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "a.py").write_text(
        "import b\n\n\ndef run_a():\n    return b.run_b()\n",
        encoding="utf-8",
    )
    (repo_path / "b.py").write_text(
        "import a\n\n\ndef run_b():\n    return 'b'\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add cycle")
    (repo_path / "a.py").write_text(
        "import b\n\n\ndef run_a():\n    return 'changed'\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)

    assert result["status"] == "COMPLETED"
    assert 1 <= result["summary"]["impacted_symbols"] <= 6


def test_propagation_respects_hop_limit(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "core.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    (repo_path / "middle.py").write_text(
        "import core\n\n\ndef use_middle():\n    return core.target()\n",
        encoding="utf-8",
    )
    (repo_path / "top.py").write_text(
        "import middle\n\n\ndef use_top():\n    return middle.use_middle()\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add depth chain")
    (repo_path / "core.py").write_text("def target():\n    return 'new'\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory, max_depth=1)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    keys = impacted_symbol_keys(result)

    assert "middle.py::middle" in keys
    assert "top.py::top" not in keys


def test_test_symbol_is_recorded_as_impacted_target(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    tests_dir = repo_path / "tests"
    tests_dir.mkdir()
    (repo_path / "service.py").write_text("def target():\n    return 'old'\n", encoding="utf-8")
    (tests_dir / "test_service.py").write_text(
        "from service import target\n\n\ndef test_target():\n    assert target() == 'old'\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add service and test")
    (repo_path / "service.py").write_text("def target():\n    return 'new'\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacted = {item["symbol_key"]: item for item in result["impacted_symbols"]}

    assert "tests/test_service.py::tests.test_service.test_target" in impacted
    assert impacted["tests/test_service.py::tests.test_service.test_target"]["is_test"] is True
    assert result["summary"]["impacted_tests"] >= 1

    with test_session_factory() as session:
        rows = session.execute(
            select(models.ImpactedSymbol).where(
                models.ImpactedSymbol.analysis_id == accepted["analysis_id"]
            )
        ).scalars()
        assert any(row.is_test for row in rows)


def test_changed_symbol_self_impact_is_high_and_persisted(
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

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)

    assert result["impacts"]
    assert result["summary"]["top_impacts"] == len(result["impacts"])
    assert result["summary"]["high_confidence_impacts"] >= 1
    assert "app.py::app.target" in impacts
    assert impacts["app.py::app.target"]["score"] == pytest.approx(1.0)
    assert impacts["app.py::app.target"]["confidence"] == "high"
    assert "changed_symbol" in impacts["app.py::app.target"]["reasons"]
    assert impacts["app.py::app.target"]["reasons_json"]["matched_from_changed_symbol"] == (
        "app.py::app.target"
    )
    assert impacts["app.py::app.target"]["reasons_json"]["merged_paths_count"] >= 1

    with test_session_factory() as session:
        rows = session.execute(
            select(models.Impact).where(models.Impact.analysis_id == accepted["analysis_id"])
        ).scalars()
        assert any(row.symbol_key == "app.py::app.target" for row in rows)


def test_imports_and_contains_scores_follow_edge_weights(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "core.py").write_text(
        "\n".join(
            [
                "VERSION = 1",
                "",
                "def helper():",
                "    return VERSION",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_path / "consumer.py").write_text(
        "import core\n\n\ndef use():\n    return core.helper()\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add weighted graph")
    (repo_path / "core.py").write_text(
        "\n".join(
            [
                "VERSION = 2",
                "",
                "def helper():",
                "    return VERSION",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)

    expected_imports_score = round(0.70 * 0.80 * 0.85, 4)
    expected_contains_score = round(0.70 * 0.40 * 0.85, 4)

    assert impacts["consumer.py::consumer"]["score"] == pytest.approx(expected_imports_score)
    assert impacts["core.py::core.helper"]["score"] == pytest.approx(expected_contains_score)
    assert impacts["consumer.py::consumer"]["score"] > impacts["core.py::core.helper"]["score"]


def test_inherits_score_uses_inherits_weight(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "base.py").write_text(
        "\n".join(
            [
                "class Base:",
                "    pass",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_path / "child.py").write_text(
        "from base import Base\n\n\nclass Child(Base):\n    pass\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add base child")
    (repo_path / "base.py").write_text(
        "\n".join(
            [
                "class Base:",
                "    marker = 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)

    expected_inherits_score = round(1.00 * 0.75 * 0.85, 4)
    assert impacts["child.py::child.Child"]["score"] == pytest.approx(expected_inherits_score)


def test_hop_decay_lowers_distant_impacts(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "core.py").write_text("VERSION = 1\n", encoding="utf-8")
    (repo_path / "middle.py").write_text("import core\n", encoding="utf-8")
    (repo_path / "top.py").write_text("import middle\n", encoding="utf-8")
    commit_all(repo_path, "add import chain")
    (repo_path / "core.py").write_text("VERSION = 2\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)

    middle_score = round(0.70 * 0.80 * 0.85, 4)
    top_score = round(0.70 * 0.80 * 0.80 * (0.85**2), 4)

    assert impacts["middle.py::middle"]["score"] == pytest.approx(middle_score)
    assert impacts["top.py::top"]["score"] == pytest.approx(top_score)
    assert impacts["middle.py::middle"]["score"] > impacts["top.py::top"]["score"]


def test_multiple_paths_merge_into_one_final_impact(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    (repo_path / "a.py").write_text("VERSION = 1\n", encoding="utf-8")
    (repo_path / "b.py").write_text("VERSION = 1\n", encoding="utf-8")
    (repo_path / "consumer.py").write_text(
        "import a\nimport b\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add multi source graph")
    (repo_path / "a.py").write_text("VERSION = 2\n", encoding="utf-8")
    (repo_path / "b.py").write_text("VERSION = 2\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)
    consumer = impacts["consumer.py::consumer"]

    assert consumer["score"] == pytest.approx(round(0.70 * 0.80 * 0.85, 4))
    assert consumer["reasons_json"]["merged_paths_count"] == 2
    assert consumer["reasons_json"]["contributing_changed_symbols"] == ["a.py::a", "b.py::b"]
    assert consumer["reasons_json"]["matched_from_changed_symbol"] == "a.py::a"
    assert consumer["explanation_path"] == ["a.py::a", "consumer.py::consumer"]


def test_impacted_test_symbol_is_scored_and_counted(
    tmp_path: Path, test_session_factory: sessionmaker[Session]
) -> None:
    repo_path = make_git_repository(tmp_path / "repo")
    tests_dir = repo_path / "tests"
    tests_dir.mkdir()
    (repo_path / "service.py").write_text("VERSION = 1\n", encoding="utf-8")
    (tests_dir / "test_service.py").write_text(
        "import service\n\n\ndef test_service_version():\n    assert service.VERSION == 1\n",
        encoding="utf-8",
    )
    commit_all(repo_path, "add service and test")
    (repo_path / "service.py").write_text("VERSION = 2\n", encoding="utf-8")

    accepted = run_analysis_for_repo(repo_path, test_session_factory)
    result = analysis_result(accepted["analysis_id"], test_session_factory)
    impacts = impacts_by_key(result)
    test_key = "tests/test_service.py::tests.test_service.test_service_version"

    assert test_key in impacts
    assert impacts[test_key]["score"] > 0.0
    assert impacts[test_key]["reasons_json"]["is_test_symbol"] is True
    assert result["summary"]["impacted_tests"] >= 1
