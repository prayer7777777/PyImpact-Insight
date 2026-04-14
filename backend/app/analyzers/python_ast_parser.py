from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from app.api.schemas import EdgeType, ParseStatus, SymbolKind


@dataclass(frozen=True)
class ParsedSymbol:
    kind: SymbolKind
    qualname: str
    name: str
    start_line: int
    end_line: int
    parent_qualname: str | None


@dataclass(frozen=True)
class ParsedEdgeRef:
    edge_type: EdgeType
    src_qualname: str
    dst_qualname: str
    weight: float
    evidence: dict


@dataclass(frozen=True)
class ImportRef:
    src_qualname: str
    candidates: tuple[str, ...]
    line: int
    detail: str


@dataclass(frozen=True)
class InheritRef:
    src_qualname: str
    base_name: str
    line: int
    detail: str


@dataclass(frozen=True)
class ParsedPythonFile:
    path: Path
    relative_path: str
    module_name: str
    content_hash: str
    parse_status: ParseStatus
    error_message: str | None = None
    symbols: list[ParsedSymbol] = field(default_factory=list)
    contains_edges: list[ParsedEdgeRef] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    inherits: list[InheritRef] = field(default_factory=list)


class PythonAstParser:
    def parse_file(self, repo_path: str, path: Path) -> ParsedPythonFile:
        root = Path(repo_path)
        relative_path = path.relative_to(root).as_posix()
        module_name = module_name_from_path(relative_path)
        try:
            source = path.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            return ParsedPythonFile(
                path=path,
                relative_path=relative_path,
                module_name=module_name,
                content_hash=self._hash_failed_file(path),
                parse_status=ParseStatus.PARSE_FAILED,
                error_message=f"{exc.msg} at line {exc.lineno}",
            )
        except OSError as exc:
            return ParsedPythonFile(
                path=path,
                relative_path=relative_path,
                module_name=module_name,
                content_hash="",
                parse_status=ParseStatus.PARSE_FAILED,
                error_message=str(exc),
            )

        extractor = _ModuleExtractor(relative_path, module_name, source)
        extractor.visit(tree)
        return ParsedPythonFile(
            path=path,
            relative_path=relative_path,
            module_name=module_name,
            content_hash=content_hash,
            parse_status=ParseStatus.PARSED,
            symbols=extractor.symbols,
            contains_edges=extractor.contains_edges,
            imports=extractor.imports,
            inherits=extractor.inherits,
        )

    def _hash_failed_file(self, path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""


class _ModuleExtractor(ast.NodeVisitor):
    def __init__(self, relative_path: str, module_name: str, source: str) -> None:
        self.relative_path = relative_path
        self.module_name = module_name
        self.is_package_init = relative_path.endswith("/__init__.py") or relative_path == "__init__.py"
        self.symbols: list[ParsedSymbol] = []
        self.contains_edges: list[ParsedEdgeRef] = []
        self.imports: list[ImportRef] = []
        self.inherits: list[InheritRef] = []
        self._line_count = max(1, len(source.splitlines()))
        self._module_qualname = module_name

    def visit_Module(self, node: ast.Module) -> None:
        self.symbols.append(
            ParsedSymbol(
                kind=SymbolKind.MODULE,
                qualname=self._module_qualname,
                name=self.module_name,
                start_line=1,
                end_line=self._line_count,
                parent_qualname=None,
            )
        )
        for child in node.body:
            if isinstance(child, ast.ClassDef):
                self._extract_class(child)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._extract_top_level_function(child)
            elif isinstance(child, ast.Import | ast.ImportFrom):
                self._extract_import(child)

        for child in ast.walk(node):
            if isinstance(child, ast.Import | ast.ImportFrom) and child not in node.body:
                self._extract_import(child)

    def _extract_class(self, node: ast.ClassDef) -> None:
        qualname = f"{self.module_name}.{node.name}"
        symbol = ParsedSymbol(
            kind=SymbolKind.CLASS,
            qualname=qualname,
            name=node.name,
            start_line=start_line_with_decorators(node),
            end_line=end_line(node),
            parent_qualname=self._module_qualname,
        )
        self.symbols.append(symbol)
        self._add_contains(self._module_qualname, qualname, node.lineno)

        for base in node.bases:
            base_name = dotted_name(base)
            if base_name:
                self.inherits.append(
                    InheritRef(
                        src_qualname=qualname,
                        base_name=base_name,
                        line=getattr(base, "lineno", node.lineno),
                        detail=f"{qualname} inherits from {base_name}",
                    )
                )

        for child in node.body:
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                self._extract_method(child, class_qualname=qualname, class_name=node.name)
            elif isinstance(child, ast.Import | ast.ImportFrom):
                self._extract_import(child)

    def _extract_top_level_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = SymbolKind.TEST_FUNCTION if node.name.startswith("test_") else SymbolKind.FUNCTION
        if isinstance(node, ast.AsyncFunctionDef) and kind != SymbolKind.TEST_FUNCTION:
            kind = SymbolKind.ASYNC_FUNCTION
        qualname = f"{self.module_name}.{node.name}"
        self.symbols.append(
            ParsedSymbol(
                kind=kind,
                qualname=qualname,
                name=node.name,
                start_line=start_line_with_decorators(node),
                end_line=end_line(node),
                parent_qualname=self._module_qualname,
            )
        )
        self._add_contains(self._module_qualname, qualname, node.lineno)

    def _extract_method(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        class_qualname: str,
        class_name: str,
    ) -> None:
        decorator_names = {decorator_name(item) for item in node.decorator_list}
        if "staticmethod" in decorator_names:
            kind = SymbolKind.STATICMETHOD
        elif "classmethod" in decorator_names:
            kind = SymbolKind.CLASSMETHOD
        elif class_name.startswith("Test") and node.name.startswith("test_"):
            kind = SymbolKind.TEST_METHOD
        elif isinstance(node, ast.AsyncFunctionDef):
            kind = SymbolKind.ASYNC_METHOD
        else:
            kind = SymbolKind.METHOD
        qualname = f"{class_qualname}.{node.name}"
        self.symbols.append(
            ParsedSymbol(
                kind=kind,
                qualname=qualname,
                name=node.name,
                start_line=start_line_with_decorators(node),
                end_line=end_line(node),
                parent_qualname=class_qualname,
            )
        )
        self._add_contains(class_qualname, qualname, node.lineno)

    def _extract_import(self, node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.imports.append(
                    ImportRef(
                        src_qualname=self._module_qualname,
                        candidates=(alias.name,),
                        line=node.lineno,
                        detail=f"{self.module_name} imports {alias.name}",
                    )
                )
            return

        base = resolve_import_from_base(
            current_module=self.module_name,
            is_package_init=self.is_package_init,
            module=node.module,
            level=node.level,
        )
        for alias in node.names:
            candidates = import_from_candidates(base, alias.name)
            if candidates:
                self.imports.append(
                    ImportRef(
                        src_qualname=self._module_qualname,
                        candidates=tuple(candidates),
                        line=node.lineno,
                        detail=f"{self.module_name} imports {alias.name} from {base or '.'}",
                    )
                )

    def _add_contains(self, src_qualname: str, dst_qualname: str, line: int) -> None:
        self.contains_edges.append(
            ParsedEdgeRef(
                edge_type=EdgeType.CONTAINS,
                src_qualname=src_qualname,
                dst_qualname=dst_qualname,
                weight=0.40,
                evidence={
                    "edge_type": EdgeType.CONTAINS.value,
                    "file_path": self.relative_path,
                    "line": line,
                    "detail": f"{src_qualname} contains {dst_qualname}",
                },
            )
        )


def module_name_from_path(relative_path: str) -> str:
    path = Path(relative_path)
    if path.name == "__init__.py":
        parts = path.parent.parts
        return ".".join(parts) if parts else "__init__"
    return ".".join(path.with_suffix("").parts)


def start_line_with_decorators(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    lines = [node.lineno]
    lines.extend(decorator.lineno for decorator in node.decorator_list)
    return min(lines)


def end_line(node: ast.AST) -> int:
    return int(getattr(node, "end_lineno", getattr(node, "lineno", 1)))


def decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    return None


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    return None


def resolve_import_from_base(
    *,
    current_module: str,
    is_package_init: bool,
    module: str | None,
    level: int,
) -> str:
    if level == 0:
        return module or ""

    current_parts = current_module.split(".") if current_module else []
    package_parts = current_parts if is_package_init else current_parts[:-1]
    keep_count = max(0, len(package_parts) - (level - 1))
    base_parts = package_parts[:keep_count]
    if module:
        base_parts.extend(module.split("."))
    return ".".join(part for part in base_parts if part)


def import_from_candidates(base: str, alias_name: str) -> list[str]:
    if alias_name == "*":
        return [base] if base else []
    candidates: list[str] = []
    if base:
        candidates.append(f"{base}.{alias_name}")
        candidates.append(base)
    else:
        candidates.append(alias_name)
    return candidates
