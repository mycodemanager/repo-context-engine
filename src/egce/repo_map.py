"""RepoMap — scan a code repository and produce a structured symbol map.

Uses tree-sitter to extract file-level structure: classes, functions,
imports, and key symbols.  The output is a lightweight "navigation view"
of the entire codebase that can be serialised into a small number of
tokens for use in an LLM prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import tree_sitter

# ---------------------------------------------------------------------------
# Language registry — lazy-loaded
# ---------------------------------------------------------------------------

_LANG_CACHE: dict[str, tree_sitter.Language] = {}

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# tree-sitter >=0.23 binding packages expose a ``language()`` helper.
_LANG_MODULES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "java": "tree_sitter_java",
}


def _get_language(name: str) -> tree_sitter.Language | None:
    if name in _LANG_CACHE:
        return _LANG_CACHE[name]
    mod_name = _LANG_MODULES.get(name)
    if mod_name is None:
        return None
    try:
        import importlib

        mod = importlib.import_module(mod_name)
        # typescript package exposes language_typescript() / language_tsx()
        if name == "typescript" and hasattr(mod, "language_typescript"):
            lang = tree_sitter.Language(mod.language_typescript())
        else:
            lang = tree_sitter.Language(mod.language())
        _LANG_CACHE[name] = lang
        return lang
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """A single extracted symbol (class, function, method, etc.)."""

    name: str
    kind: str  # "class" | "function" | "method" | "interface" | "struct"
    line: int
    signature: str  # e.g. "def foo(a: int, b: str) -> bool"
    children: list[Symbol] = field(default_factory=list)


@dataclass
class ImportEntry:
    """A single import statement."""

    module: str
    names: list[str] = field(default_factory=list)  # empty → whole-module import
    line: int = 0


@dataclass
class FileInfo:
    """Parsed information for a single source file."""

    path: str  # relative to repo root
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportEntry] = field(default_factory=list)
    lines: int = 0


@dataclass
class RepoMapResult:
    """The complete scan result for a repository."""

    root: str
    files: list[FileInfo] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_text(self, *, max_depth: int = 2) -> str:
        """Render the repo map as a compact text suitable for LLM context."""
        lines: list[str] = [f"# Repo Map: {self.root}", ""]
        for fi in self.files:
            lines.append(f"## {fi.path}  ({fi.language}, {fi.lines} lines)")
            # imports
            for imp in fi.imports:
                if imp.names:
                    lines.append(f"  import {imp.module} :: {', '.join(imp.names)}")
                else:
                    lines.append(f"  import {imp.module}")
            # symbols
            for sym in fi.symbols:
                lines.append(f"  {sym.signature}  [L{sym.line}]")
                if max_depth > 1:
                    for child in sym.children:
                        lines.append(f"    {child.signature}  [L{child.line}]")
            lines.append("")
        return "\n".join(lines)

    def focused_text(
        self,
        focus_files: set[str],
        *,
        max_depth_focused: int = 2,
        show_others: bool = True,
    ) -> str:
        """Render a query-aware repo map.

        Files in ``focus_files`` get full symbol detail (imports + signatures
        + methods).  Other files are listed as a single line with just the
        file name and line count, keeping the overall token cost low while
        still giving the model a sense of what exists.

        Parameters
        ----------
        focus_files : set of relative file paths to expand in detail
        max_depth_focused : nesting depth for focused files (default 2)
        show_others : if True, list non-focused files in a compact block
        """
        lines: list[str] = [f"# Repo Map: {self.root}", ""]

        focused: list[FileInfo] = []
        others: list[FileInfo] = []
        for fi in self.files:
            if fi.path in focus_files:
                focused.append(fi)
            else:
                others.append(fi)

        # Focused files — full detail
        if focused:
            lines.append("## Relevant files (detailed)")
            lines.append("")
            for fi in focused:
                lines.append(f"### {fi.path}  ({fi.language}, {fi.lines} lines)")
                for imp in fi.imports:
                    if imp.names:
                        lines.append(f"  import {imp.module} :: {', '.join(imp.names)}")
                    else:
                        lines.append(f"  import {imp.module}")
                for sym in fi.symbols:
                    lines.append(f"  {sym.signature}  [L{sym.line}]")
                    if max_depth_focused > 1:
                        for child in sym.children:
                            lines.append(f"    {child.signature}  [L{child.line}]")
                lines.append("")

        # Other files — compact listing
        if show_others and others:
            lines.append("## Other files (summary)")
            lines.append("")
            for fi in others:
                n_sym = len(fi.symbols)
                lines.append(f"  {fi.path}  ({fi.lines} lines, {n_sym} symbols)")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-friendly)."""
        import dataclasses

        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Default ignore patterns
# ---------------------------------------------------------------------------

_DEFAULT_IGNORE_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",       # rust / java
    ".next",
    ".nuxt",
    "vendor",
}


# ---------------------------------------------------------------------------
# Tree-sitter extraction helpers (per-language)
# ---------------------------------------------------------------------------


def _extract_python(root_node: tree_sitter.Node, source: bytes) -> tuple[list[Symbol], list[ImportEntry]]:
    symbols: list[Symbol] = []
    imports: list[ImportEntry] = []

    for child in root_node.children:
        if child.type == "import_statement":
            text = source[child.start_byte : child.end_byte].decode(errors="replace")
            # e.g. "import os" or "import os, sys"
            parts = text.replace("import ", "").split(",")
            for p in parts:
                imports.append(ImportEntry(module=p.strip(), line=child.start_point.row + 1))

        elif child.type == "import_from_statement":
            text = source[child.start_byte : child.end_byte].decode(errors="replace")
            # "from foo import bar, baz"
            if " import " in text:
                mod_part, name_part = text.split(" import ", 1)
                mod = mod_part.replace("from ", "").strip()
                names = [n.strip() for n in name_part.split(",")]
                imports.append(ImportEntry(module=mod, names=names, line=child.start_point.row + 1))

        elif child.type in ("function_definition", "decorated_definition"):
            sym = _parse_python_func(child, source)
            if sym:
                symbols.append(sym)

        elif child.type == "class_definition":
            sym = _parse_python_class(child, source)
            if sym:
                symbols.append(sym)

    return symbols, imports


def _parse_python_func(node: tree_sitter.Node, source: bytes) -> Symbol | None:
    # decorated_definition wraps the actual function
    actual = node
    if node.type == "decorated_definition":
        for c in node.children:
            if c.type == "function_definition":
                actual = c
                break
        else:
            return None
    name_node = actual.child_by_field_name("name")
    if name_node is None:
        return None
    name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
    params_node = actual.child_by_field_name("parameters")
    params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
    ret_node = actual.child_by_field_name("return_type")
    ret = f" -> {source[ret_node.start_byte : ret_node.end_byte].decode(errors='replace')}" if ret_node else ""
    sig = f"def {name}{params}{ret}"
    return Symbol(name=name, kind="function", line=actual.start_point.row + 1, signature=sig)


def _parse_python_class(node: tree_sitter.Node, source: bytes) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
    superclasses = node.child_by_field_name("superclasses")
    bases = ""
    if superclasses:
        bases = source[superclasses.start_byte : superclasses.end_byte].decode(errors="replace")
    sig = f"class {name}{bases}" if bases else f"class {name}"
    sym = Symbol(name=name, kind="class", line=node.start_point.row + 1, signature=sig)

    # methods
    body = node.child_by_field_name("body")
    if body:
        for child in body.children:
            if child.type in ("function_definition", "decorated_definition"):
                m = _parse_python_func(child, source)
                if m:
                    m.kind = "method"
                    sym.children.append(m)
    return sym


def _extract_js_ts(root_node: tree_sitter.Node, source: bytes) -> tuple[list[Symbol], list[ImportEntry]]:
    symbols: list[Symbol] = []
    imports: list[ImportEntry] = []

    for child in root_node.children:
        if child.type == "import_statement":
            text = source[child.start_byte : child.end_byte].decode(errors="replace").rstrip(";")
            # crude but workable: "import { a, b } from 'mod'"
            if " from " in text:
                parts = text.split(" from ")
                mod = parts[-1].strip().strip("'\"")
                name_part = parts[0].replace("import", "").strip().strip("{} ")
                names = [n.strip() for n in name_part.split(",")] if name_part else []
                imports.append(ImportEntry(module=mod, names=names, line=child.start_point.row + 1))
            else:
                mod = text.replace("import", "").strip().strip("'\"")
                imports.append(ImportEntry(module=mod, line=child.start_point.row + 1))

        elif child.type in ("function_declaration", "export_statement"):
            sym = _parse_js_func(child, source)
            if sym:
                symbols.append(sym)

        elif child.type == "class_declaration":
            sym = _parse_js_class(child, source)
            if sym:
                symbols.append(sym)

        elif child.type == "lexical_declaration":
            # const foo = (...) => { ... }
            sym = _parse_js_arrow(child, source)
            if sym:
                symbols.append(sym)

    return symbols, imports


def _parse_js_func(node: tree_sitter.Node, source: bytes) -> Symbol | None:
    actual = node
    # export_statement wraps function_declaration
    if node.type == "export_statement":
        for c in node.children:
            if c.type == "function_declaration":
                actual = c
                break
        else:
            return None
    name_node = actual.child_by_field_name("name")
    if name_node is None:
        return None
    name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
    params_node = actual.child_by_field_name("parameters")
    params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
    sig = f"function {name}{params}"
    return Symbol(name=name, kind="function", line=actual.start_point.row + 1, signature=sig)


def _parse_js_class(node: tree_sitter.Node, source: bytes) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
    sig = f"class {name}"
    sym = Symbol(name=name, kind="class", line=node.start_point.row + 1, signature=sig)
    body = node.child_by_field_name("body")
    if body:
        for child in body.children:
            if child.type == "method_definition":
                mname_node = child.child_by_field_name("name")
                if mname_node:
                    mname = source[mname_node.start_byte : mname_node.end_byte].decode(errors="replace")
                    params_node = child.child_by_field_name("parameters")
                    params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
                    sym.children.append(
                        Symbol(name=mname, kind="method", line=child.start_point.row + 1, signature=f"{mname}{params}")
                    )
    return sym


def _parse_js_arrow(node: tree_sitter.Node, source: bytes) -> Symbol | None:
    """Try to extract `const foo = (...) => ...`."""
    for decl in node.children:
        if decl.type == "variable_declarator":
            name_node = decl.child_by_field_name("name")
            value_node = decl.child_by_field_name("value")
            if name_node and value_node and value_node.type == "arrow_function":
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                params_node = value_node.child_by_field_name("parameters")
                params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
                sig = f"const {name} = {params} =>"
                return Symbol(name=name, kind="function", line=node.start_point.row + 1, signature=sig)
    return None


def _extract_go(root_node: tree_sitter.Node, source: bytes) -> tuple[list[Symbol], list[ImportEntry]]:
    symbols: list[Symbol] = []
    imports: list[ImportEntry] = []

    for child in root_node.children:
        if child.type == "import_declaration":
            for spec in _iter_descendants(child, "import_spec"):
                path_node = spec.child_by_field_name("path")
                if path_node:
                    mod = source[path_node.start_byte : path_node.end_byte].decode(errors="replace").strip('"')
                    imports.append(ImportEntry(module=mod, line=spec.start_point.row + 1))

        elif child.type == "function_declaration":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                params_node = child.child_by_field_name("parameters")
                params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
                sig = f"func {name}{params}"
                symbols.append(Symbol(name=name, kind="function", line=child.start_point.row + 1, signature=sig))

        elif child.type == "method_declaration":
            name_node = child.child_by_field_name("name")
            recv_node = child.child_by_field_name("receiver")
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                recv = source[recv_node.start_byte : recv_node.end_byte].decode(errors="replace") if recv_node else ""
                params_node = child.child_by_field_name("parameters")
                params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
                sig = f"func {recv} {name}{params}" if recv else f"func {name}{params}"
                symbols.append(Symbol(name=name, kind="method", line=child.start_point.row + 1, signature=sig))

        elif child.type == "type_declaration":
            for spec in child.children:
                if spec.type == "type_spec":
                    tname = spec.child_by_field_name("name")
                    ttype = spec.child_by_field_name("type")
                    if tname:
                        n = source[tname.start_byte : tname.end_byte].decode(errors="replace")
                        kind = "struct" if ttype and ttype.type == "struct_type" else "interface" if ttype and ttype.type == "interface_type" else "class"
                        sig = f"type {n} {ttype.type.replace('_type', '')}" if ttype else f"type {n}"
                        symbols.append(Symbol(name=n, kind=kind, line=spec.start_point.row + 1, signature=sig))

    return symbols, imports


def _extract_rust(root_node: tree_sitter.Node, source: bytes) -> tuple[list[Symbol], list[ImportEntry]]:
    symbols: list[Symbol] = []
    imports: list[ImportEntry] = []

    for child in root_node.children:
        if child.type == "use_declaration":
            text = source[child.start_byte : child.end_byte].decode(errors="replace").rstrip(";")
            mod = text.replace("use ", "").strip()
            imports.append(ImportEntry(module=mod, line=child.start_point.row + 1))

        elif child.type == "function_item":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                params_node = child.child_by_field_name("parameters")
                params = source[params_node.start_byte : params_node.end_byte].decode(errors="replace") if params_node else "()"
                ret = child.child_by_field_name("return_type")
                ret_str = f" -> {source[ret.start_byte : ret.end_byte].decode(errors='replace')}" if ret else ""
                sig = f"fn {name}{params}{ret_str}"
                symbols.append(Symbol(name=name, kind="function", line=child.start_point.row + 1, signature=sig))

        elif child.type == "struct_item":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                symbols.append(Symbol(name=name, kind="struct", line=child.start_point.row + 1, signature=f"struct {name}"))

        elif child.type == "impl_item":
            tname = child.child_by_field_name("type")
            if tname:
                type_name = source[tname.start_byte : tname.end_byte].decode(errors="replace")
                body = child.child_by_field_name("body")
                if body:
                    for item in body.children:
                        if item.type == "function_item":
                            fname_node = item.child_by_field_name("name")
                            if fname_node:
                                fname = source[fname_node.start_byte : fname_node.end_byte].decode(errors="replace")
                                p_node = item.child_by_field_name("parameters")
                                p = source[p_node.start_byte : p_node.end_byte].decode(errors="replace") if p_node else "()"
                                sig = f"impl {type_name} :: fn {fname}{p}"
                                symbols.append(Symbol(name=fname, kind="method", line=item.start_point.row + 1, signature=sig))

    return symbols, imports


def _extract_java(root_node: tree_sitter.Node, source: bytes) -> tuple[list[Symbol], list[ImportEntry]]:
    symbols: list[Symbol] = []
    imports: list[ImportEntry] = []

    for child in root_node.children:
        if child.type == "import_declaration":
            text = source[child.start_byte : child.end_byte].decode(errors="replace")
            mod = text.replace("import", "").replace(";", "").strip()
            imports.append(ImportEntry(module=mod, line=child.start_point.row + 1))

        elif child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = source[name_node.start_byte : name_node.end_byte].decode(errors="replace")
                sym = Symbol(name=name, kind="class", line=child.start_point.row + 1, signature=f"class {name}")
                body = child.child_by_field_name("body")
                if body:
                    for item in body.children:
                        if item.type == "method_declaration":
                            mname_node = item.child_by_field_name("name")
                            if mname_node:
                                mname = source[mname_node.start_byte : mname_node.end_byte].decode(errors="replace")
                                p_node = item.child_by_field_name("parameters")
                                params = source[p_node.start_byte : p_node.end_byte].decode(errors="replace") if p_node else "()"
                                rtype = item.child_by_field_name("type")
                                ret = source[rtype.start_byte : rtype.end_byte].decode(errors="replace") if rtype else "void"
                                sig = f"{ret} {mname}{params}"
                                sym.children.append(Symbol(name=mname, kind="method", line=item.start_point.row + 1, signature=sig))
                symbols.append(sym)

    return symbols, imports


_EXTRACTORS = {
    "python": _extract_python,
    "javascript": _extract_js_ts,
    "typescript": _extract_js_ts,
    "go": _extract_go,
    "rust": _extract_rust,
    "java": _extract_java,
}


def _iter_descendants(node: tree_sitter.Node, target_type: str):
    if node.type == target_type:
        yield node
    for c in node.children:
        yield from _iter_descendants(c, target_type)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class RepoMap:
    """Scan a repository and build a symbol map.

    Usage::

        repo = RepoMap("/path/to/repo")
        result = repo.scan()
        print(result.to_text())
    """

    def __init__(
        self,
        root: str | Path,
        *,
        ignore_dirs: set[str] | None = None,
        extensions: dict[str, str] | None = None,
        max_file_bytes: int = 512_000,
    ) -> None:
        self.root = Path(root).resolve()
        self.ignore_dirs = ignore_dirs or _DEFAULT_IGNORE_DIRS
        self.ext_to_lang = extensions or _EXT_TO_LANG
        self.max_file_bytes = max_file_bytes
        self._parsers: dict[str, tree_sitter.Parser] = {}

    def _get_parser(self, lang_name: str) -> tree_sitter.Parser | None:
        if lang_name in self._parsers:
            return self._parsers[lang_name]
        lang = _get_language(lang_name)
        if lang is None:
            return None
        parser = tree_sitter.Parser(lang)
        self._parsers[lang_name] = parser
        return parser

    def scan(
        self,
        *,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> RepoMapResult:
        """Walk the repo and extract symbols from each recognised source file.

        Parameters
        ----------
        include : optional list of relative paths / glob patterns to include
        exclude : optional list of relative paths / glob patterns to exclude
        """
        result = RepoMapResult(root=str(self.root))

        for dirpath, dirnames, filenames in os.walk(self.root):
            # prune ignored dirs in-place
            dirnames[:] = [d for d in dirnames if d not in self.ignore_dirs]
            dirnames.sort()

            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                ext = fpath.suffix
                lang_name = self.ext_to_lang.get(ext)
                if lang_name is None:
                    continue

                rel = str(fpath.relative_to(self.root))

                if include and not any(_match_pattern(rel, p) for p in include):
                    continue
                if exclude and any(_match_pattern(rel, p) for p in exclude):
                    continue

                fi = self._parse_file(fpath, rel, lang_name)
                if fi is not None:
                    result.files.append(fi)

        return result

    def _parse_file(self, fpath: Path, rel: str, lang_name: str) -> FileInfo | None:
        try:
            raw = fpath.read_bytes()
        except (OSError, PermissionError):
            return None

        if len(raw) > self.max_file_bytes:
            # too large — record the file but skip parsing
            line_count = raw.count(b"\n")
            return FileInfo(path=rel, language=lang_name, lines=line_count)

        line_count = raw.count(b"\n") + 1

        parser = self._get_parser(lang_name)
        if parser is None:
            return FileInfo(path=rel, language=lang_name, lines=line_count)

        tree = parser.parse(raw)
        extractor = _EXTRACTORS.get(lang_name)
        if extractor is None:
            return FileInfo(path=rel, language=lang_name, lines=line_count)

        symbols, imports = extractor(tree.root_node, raw)
        return FileInfo(path=rel, language=lang_name, symbols=symbols, imports=imports, lines=line_count)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_pattern(path: str, pattern: str) -> bool:
    """Very simple glob-style matching (supports only leading/trailing *)."""
    if "*" not in pattern:
        return path == pattern or path.startswith(pattern)
    from fnmatch import fnmatch

    return fnmatch(path, pattern)
