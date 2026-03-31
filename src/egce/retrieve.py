"""Retrieve — BM25 + symbol hybrid search over a code repository.

Given a natural-language query (or a list of keywords / symbol names),
this module finds the most relevant code chunks across the repo and
returns them as ``EvidenceChunk`` objects with full provenance.

The implementation is dependency-free (no external search engine):
- BM25 over source lines (term frequency / inverse document frequency)
- Symbol name matching against the RepoMap index
- Score fusion and reranking
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from egce.repo_map import FileInfo, RepoMap, RepoMapResult


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EvidenceChunk:
    """A single piece of retrieved evidence with provenance."""

    source_uri: str  # relative file path
    source_type: str  # "code" | "doc" | "test" | "config"
    start_line: int
    end_line: int
    content: str
    symbols: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_text(self) -> str:
        header = f"# {self.source_uri}  L{self.start_line}-{self.end_line}"
        if self.symbols:
            header += f"  ({', '.join(self.symbols)})"
        return f"{header}\n{self.content}"


# ---------------------------------------------------------------------------
# Tokenizer (simple whitespace + camelCase + snake_case splitter)
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[0-9]+")
_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, expanding camelCase and snake_case."""
    tokens: list[str] = []
    for word in _WORD_RE.findall(text):
        parts = _SPLIT_RE.findall(word)
        if parts:
            tokens.extend(p.lower() for p in parts)
        else:
            tokens.append(word.lower())
    return tokens


# ---------------------------------------------------------------------------
# BM25 index
# ---------------------------------------------------------------------------

# BM25 parameters
_K1 = 1.5
_B = 0.75


@dataclass
class _Document:
    """A chunk of source code for indexing."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    tokens: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    source_type: str = "code"


class _BM25Index:
    """Simple in-memory BM25 index."""

    def __init__(self) -> None:
        self.docs: list[_Document] = []
        self.df: dict[str, int] = {}  # document frequency
        self.avg_dl: float = 0.0

    def build(self, docs: list[_Document]) -> None:
        self.docs = docs
        n = len(docs)
        if n == 0:
            return

        total_len = 0
        df: dict[str, int] = {}
        for doc in docs:
            total_len += len(doc.tokens)
            seen: set[str] = set()
            for tok in doc.tokens:
                if tok not in seen:
                    df[tok] = df.get(tok, 0) + 1
                    seen.add(tok)
        self.df = df
        self.avg_dl = total_len / n

    def search(self, query_tokens: list[str], top_k: int = 20) -> list[tuple[_Document, float]]:
        if not self.docs:
            return []

        n = len(self.docs)
        scores: list[float] = [0.0] * n

        for qt in query_tokens:
            doc_freq = self.df.get(qt, 0)
            if doc_freq == 0:
                continue
            idf = math.log((n - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

            for i, doc in enumerate(self.docs):
                tf = doc.tokens.count(qt)
                dl = len(doc.tokens)
                denom = tf + _K1 * (1 - _B + _B * dl / self.avg_dl) if self.avg_dl > 0 else tf + _K1
                score = idf * (tf * (_K1 + 1)) / denom
                scores[i] += score

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: list[tuple[_Document, float]] = []
        for idx, score in ranked[:top_k]:
            if score > 0:
                results.append((self.docs[idx], score))
        return results


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


def _classify_source(path: str) -> str:
    """Classify a file path into a source type."""
    p = path.lower()
    if "test" in p:
        return "test"
    if p.endswith((".md", ".rst", ".txt")):
        return "doc"
    if p.endswith((".toml", ".yaml", ".yml", ".json", ".cfg", ".ini")):
        return "config"
    return "code"


def _chunk_file(file_path: Path, rel_path: str, chunk_lines: int = 40, overlap: int = 10) -> list[_Document]:
    """Split a source file into overlapping chunks."""
    try:
        lines = file_path.read_text(errors="replace").splitlines()
    except (OSError, PermissionError):
        return []

    if not lines:
        return []

    source_type = _classify_source(rel_path)
    chunks: list[_Document] = []

    # For small files, keep as one chunk
    if len(lines) <= chunk_lines:
        content = "\n".join(lines)
        tokens = _tokenize(content)
        chunks.append(_Document(
            file_path=rel_path,
            start_line=1,
            end_line=len(lines),
            content=content,
            tokens=tokens,
            source_type=source_type,
        ))
        return chunks

    # Sliding window
    start = 0
    while start < len(lines):
        end = min(start + chunk_lines, len(lines))
        content = "\n".join(lines[start:end])
        tokens = _tokenize(content)
        chunks.append(_Document(
            file_path=rel_path,
            start_line=start + 1,
            end_line=end,
            content=content,
            tokens=tokens,
            source_type=source_type,
        ))
        if end >= len(lines):
            break
        start += chunk_lines - overlap

    return chunks


class Retriever:
    """Hybrid BM25 + symbol search over a code repository.

    Usage::

        retriever = Retriever("/path/to/repo")
        retriever.index()
        chunks = retriever.search("dependency injection validator")
    """

    def __init__(
        self,
        root: str | Path,
        *,
        chunk_lines: int = 40,
        overlap: int = 10,
        ignore_dirs: set[str] | None = None,
        extensions: dict[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.chunk_lines = chunk_lines
        self.overlap = overlap
        self._bm25 = _BM25Index()
        self._symbol_map: dict[str, list[_Document]] = {}  # symbol_name → docs
        self._repo_result: RepoMapResult | None = None
        self._ignore_dirs = ignore_dirs
        self._extensions = extensions
        self._indexed = False

        # All source extensions to scan (broader than just tree-sitter supported)
        self._all_extensions: set[str] = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
            ".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json",
            ".cfg", ".ini", ".sh", ".bash",
        }

    def index(
        self,
        *,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> None:
        """Build the search index by scanning the repository."""
        import os
        from egce.repo_map import _DEFAULT_IGNORE_DIRS, _match_pattern

        ignore_dirs = self._ignore_dirs or _DEFAULT_IGNORE_DIRS

        # 1) Chunk all source files for BM25
        all_docs: list[_Document] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            dirnames.sort()
            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                if fpath.suffix not in self._all_extensions:
                    continue
                rel = str(fpath.relative_to(self.root))
                if include and not any(_match_pattern(rel, p) for p in include):
                    continue
                if exclude and any(_match_pattern(rel, p) for p in exclude):
                    continue
                chunks = _chunk_file(fpath, rel, self.chunk_lines, self.overlap)
                all_docs.extend(chunks)

        self._bm25.build(all_docs)

        # 2) Build symbol map from tree-sitter parse
        repo = RepoMap(self.root, ignore_dirs=ignore_dirs, extensions=self._extensions)
        self._repo_result = repo.scan(include=include, exclude=exclude)

        self._symbol_map.clear()
        for fi in self._repo_result.files:
            for sym in fi.symbols:
                self._register_symbol(sym, fi, all_docs)
                for child in sym.children:
                    self._register_symbol(child, fi, all_docs)

        self._indexed = True

    def _register_symbol(self, sym, fi: FileInfo, all_docs: list[_Document]) -> None:
        """Map a symbol name to the documents that contain it."""
        name_lower = sym.name.lower()
        if name_lower not in self._symbol_map:
            self._symbol_map[name_lower] = []
        # find chunks that cover this symbol's line
        for doc in all_docs:
            if doc.file_path == fi.path and doc.start_line <= sym.line <= doc.end_line:
                if doc not in self._symbol_map[name_lower]:
                    self._symbol_map[name_lower].append(doc)

    @property
    def repo_map_result(self) -> RepoMapResult | None:
        return self._repo_result

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        bm25_weight: float = 0.6,
        symbol_weight: float = 0.4,
    ) -> list[EvidenceChunk]:
        """Search for code chunks relevant to the query.

        Returns ranked EvidenceChunk list with provenance.
        """
        if not self._indexed:
            raise RuntimeError("Call index() before search()")

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # --- BM25 search ---
        bm25_results = self._bm25.search(query_tokens, top_k=top_k * 3)

        # --- Symbol search ---
        symbol_hits: dict[int, float] = {}  # doc index → bonus score
        for qt in query_tokens:
            matched_docs = self._symbol_map.get(qt, [])
            for doc in matched_docs:
                try:
                    idx = self._bm25.docs.index(doc)
                    symbol_hits[idx] = symbol_hits.get(idx, 0) + 1.0
                except ValueError:
                    pass

        # --- Fuse scores ---
        fused: dict[int, float] = {}
        if bm25_results:
            max_bm25 = bm25_results[0][1] if bm25_results else 1.0
            for doc, score in bm25_results:
                idx = self._bm25.docs.index(doc)
                normalized = score / max_bm25 if max_bm25 > 0 else 0
                fused[idx] = fused.get(idx, 0) + normalized * bm25_weight

        max_sym = max(symbol_hits.values()) if symbol_hits else 1.0
        for idx, score in symbol_hits.items():
            normalized = score / max_sym if max_sym > 0 else 0
            fused[idx] = fused.get(idx, 0) + normalized * symbol_weight

        # --- Rank and deduplicate ---
        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)

        seen_ranges: set[tuple[str, int, int]] = set()
        results: list[EvidenceChunk] = []

        for idx, score in ranked:
            if len(results) >= top_k:
                break
            doc = self._bm25.docs[idx]
            key = (doc.file_path, doc.start_line, doc.end_line)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)

            # find symbols in this chunk
            chunk_symbols: list[str] = []
            if self._repo_result:
                for fi in self._repo_result.files:
                    if fi.path == doc.file_path:
                        for sym in fi.symbols:
                            if doc.start_line <= sym.line <= doc.end_line:
                                chunk_symbols.append(sym.name)
                            for child in sym.children:
                                if doc.start_line <= child.line <= doc.end_line:
                                    chunk_symbols.append(f"{sym.name}.{child.name}")

            results.append(EvidenceChunk(
                source_uri=doc.file_path,
                source_type=doc.source_type,
                start_line=doc.start_line,
                end_line=doc.end_line,
                content=doc.content,
                symbols=chunk_symbols,
                score=round(score, 4),
            ))

        return results


# ---------------------------------------------------------------------------
# Multi-project workspace retriever
# ---------------------------------------------------------------------------


class WorkspaceRetriever:
    """Index and search across multiple projects in a workspace.

    Usage::

        wr = WorkspaceRetriever.from_workspace("~/workspace/my-project")
        wr.index()
        chunks = wr.search("authentication", top_k=10)
        # → chunks have source_uri like "backend:src/auth.py"
    """

    def __init__(self) -> None:
        self._retrievers: dict[str, Retriever] = {}
        self._repo_results: dict[str, RepoMapResult] = {}

    @classmethod
    def from_workspace(cls, workspace_root: str | Path) -> "WorkspaceRetriever":
        """Create from a workspace directory containing workspace.yaml."""
        root = Path(workspace_root).resolve()
        wr = cls()

        ws_yaml = root / ".egce" / "workspace.yaml"
        if ws_yaml.exists():
            # Parse workspace.yaml for project paths
            for line in ws_yaml.read_text().splitlines():
                line = line.strip()
                if line.startswith("path:"):
                    proj_path = line.split(":", 1)[1].strip()
                    full_path = root / proj_path
                    if full_path.exists():
                        name = full_path.name
                        wr._retrievers[name] = Retriever(full_path)
        else:
            # Auto-detect: scan for git repos in subdirectories
            for entry in sorted(root.iterdir()):
                if entry.is_dir() and (entry / ".git").exists():
                    wr._retrievers[entry.name] = Retriever(entry)

        # If nothing found, treat root as single project
        if not wr._retrievers:
            wr._retrievers[root.name] = Retriever(root)

        return wr

    def index(
        self,
        *,
        exclude: Sequence[str] | None = None,
    ) -> None:
        """Index all projects."""
        for name, ret in self._retrievers.items():
            ret.index(exclude=exclude)
            if ret.repo_map_result:
                self._repo_results[name] = ret.repo_map_result

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        **kwargs,
    ) -> list[EvidenceChunk]:
        """Search across all projects, merge and re-rank results.

        Results have ``source_uri`` prefixed with project name
        (e.g. "backend:src/auth.py").
        """
        all_chunks: list[EvidenceChunk] = []

        for name, ret in self._retrievers.items():
            chunks = ret.search(query, top_k=top_k, **kwargs)
            for c in chunks:
                # Prefix with project name
                prefixed = EvidenceChunk(
                    source_uri=f"{name}:{c.source_uri}",
                    source_type=c.source_type,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    content=c.content,
                    symbols=c.symbols,
                    score=c.score,
                )
                all_chunks.append(prefixed)

        # Re-rank by score across all projects
        all_chunks.sort(key=lambda c: c.score, reverse=True)
        return all_chunks[:top_k]

    @property
    def repo_map_results(self) -> dict[str, RepoMapResult]:
        return dict(self._repo_results)

    def focused_text(self, focus_files: set[str]) -> str:
        """Build a combined focused repo map across all projects."""
        parts: list[str] = []
        for name, result in self._repo_results.items():
            # Extract focus files for this project
            project_focus = set()
            for f in focus_files:
                if f.startswith(f"{name}:"):
                    project_focus.add(f[len(name) + 1:])
            if project_focus:
                text = result.focused_text(project_focus)
                parts.append(f"# Project: {name}\n\n{text}")
        return "\n\n".join(parts)
