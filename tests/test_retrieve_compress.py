"""Tests for retrieve and compress modules."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ======================================================================
# retrieve tests
# ======================================================================


class TestRetriever:
    """Test BM25 + symbol hybrid search."""

    @pytest.fixture()
    def sample_repo(self, tmp_path: Path) -> Path:
        """Create a small sample repo with multiple files."""
        (tmp_path / "auth.py").write_text(textwrap.dedent("""\
            import hashlib
            from typing import Optional

            class Authenticator:
                def __init__(self, secret: str):
                    self.secret = secret

                def validate_token(self, token: str) -> bool:
                    return hashlib.sha256(token.encode()).hexdigest() == self.secret

                def generate_token(self, user_id: str) -> str:
                    return hashlib.sha256(f"{user_id}:{self.secret}".encode()).hexdigest()

            def login(username: str, password: str) -> Optional[str]:
                auth = Authenticator("secret")
                if auth.validate_token(password):
                    return auth.generate_token(username)
                return None
        """))

        (tmp_path / "router.py").write_text(textwrap.dedent("""\
            from auth import Authenticator

            class Router:
                def __init__(self):
                    self.routes = {}

                def add_route(self, path: str, handler):
                    self.routes[path] = handler

                def dispatch(self, path: str, request):
                    handler = self.routes.get(path)
                    if handler:
                        return handler(request)
                    raise ValueError(f"Route not found: {path}")
        """))

        (tmp_path / "models.py").write_text(textwrap.dedent("""\
            from dataclasses import dataclass

            @dataclass
            class User:
                id: str
                name: str
                email: str

            @dataclass
            class Session:
                token: str
                user_id: str
                expires_at: str
        """))

        (tmp_path / "utils.py").write_text(textwrap.dedent("""\
            import os
            import logging

            logger = logging.getLogger(__name__)

            def read_config(path: str) -> dict:
                logger.info(f"Reading config from {path}")
                return {}

            def format_response(data: dict) -> str:
                return str(data)
        """))

        return tmp_path

    def test_basic_search(self, sample_repo: Path) -> None:
        """BM25 search finds relevant files."""
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()
        results = r.search("authenticate token validation", top_k=5)

        assert len(results) > 0
        # auth.py should be the top result
        assert results[0].source_uri == "auth.py"
        assert results[0].score > 0

    def test_symbol_search(self, sample_repo: Path) -> None:
        """Symbol names boost results."""
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()
        results = r.search("Authenticator validate", top_k=5)

        assert len(results) > 0
        assert any("Authenticator" in c.symbols for c in results)

    def test_search_returns_provenance(self, sample_repo: Path) -> None:
        """Results include file path, line numbers, source type."""
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()
        results = r.search("router dispatch", top_k=3)

        assert len(results) > 0
        chunk = results[0]
        assert chunk.source_uri == "router.py"
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert chunk.source_type == "code"

    def test_search_ranking(self, sample_repo: Path) -> None:
        """More relevant files rank higher."""
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()
        results = r.search("User email Session token", top_k=5)

        # models.py should be near the top
        top_files = [c.source_uri for c in results[:3]]
        assert "models.py" in top_files

    def test_empty_query(self, sample_repo: Path) -> None:
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()
        results = r.search("", top_k=5)
        assert results == []

    def test_index_with_exclude(self, sample_repo: Path) -> None:
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index(exclude=["utils.py"])
        results = r.search("config logging", top_k=5)

        # utils.py is excluded, so it shouldn't appear
        for c in results:
            assert c.source_uri != "utils.py"

    def test_repo_map_available(self, sample_repo: Path) -> None:
        """After indexing, repo_map_result should be available."""
        from egce.retrieve import Retriever

        r = Retriever(sample_repo)
        r.index()

        assert r.repo_map_result is not None
        assert len(r.repo_map_result.files) > 0

    def test_evidence_chunk_to_text(self) -> None:
        from egce.retrieve import EvidenceChunk

        c = EvidenceChunk(
            source_uri="foo.py",
            source_type="code",
            start_line=10,
            end_line=20,
            content="def hello(): pass",
            symbols=["hello"],
            score=0.95,
        )
        text = c.to_text()
        assert "foo.py" in text
        assert "L10-20" in text
        assert "hello" in text


# ======================================================================
# compress tests
# ======================================================================


class TestCompress:
    """Test query-aware code compression."""

    def test_basic_compression(self) -> None:
        """Compression reduces token count while keeping relevant lines."""
        from egce.compress import compress_chunks
        from egce.retrieve import EvidenceChunk

        code = textwrap.dedent("""\
            import os
            import sys
            # This is a comment about nothing
            # Another useless comment

            class Validator:
                def __init__(self):
                    pass

                def validate(self, data: dict) -> bool:
                    # Check if data is valid
                    # More comments here
                    # And here
                    if not data:
                        raise ValueError("Empty data")
                    return True

                def format_output(self, result):
                    # Just formatting
                    logger.info("formatting")
                    print(result)
                    return str(result)

            def helper():
                pass

            def another_helper():
                pass
        """)

        chunk = EvidenceChunk(
            source_uri="validator.py",
            source_type="code",
            start_line=1,
            end_line=30,
            content=code,
            symbols=["Validator"],
        )

        compressed = compress_chunks([chunk], "validate data validator", target_ratio=0.5)
        assert len(compressed) == 1

        original_lines = code.splitlines()
        compressed_lines = compressed[0].content.splitlines()
        assert len(compressed_lines) < len(original_lines)

        # Key structural elements should survive
        text = compressed[0].content
        assert "class Validator" in text
        assert "def validate" in text
        assert "raise ValueError" in text

    def test_keeps_imports_and_signatures(self) -> None:
        from egce.compress import compress_chunks
        from egce.retrieve import EvidenceChunk

        code = textwrap.dedent("""\
            import hashlib
            from typing import Optional

            def authenticate(token: str) -> bool:
                # This function authenticates
                # It does many things
                # Like checking stuff
                # And more stuff
                # Really a lot of stuff
                return hashlib.sha256(token.encode()).hexdigest() == "secret"
        """)

        chunk = EvidenceChunk(
            source_uri="auth.py", source_type="code",
            start_line=1, end_line=10, content=code,
        )

        compressed = compress_chunks([chunk], "authenticate token", target_ratio=0.4)
        text = compressed[0].content
        assert "import hashlib" in text
        assert "def authenticate" in text
        assert "return" in text

    def test_omission_markers(self) -> None:
        """Compressed output includes [...N lines omitted...] markers."""
        from egce.compress import compress_chunks
        from egce.retrieve import EvidenceChunk

        # Generate a long chunk with lots of irrelevant lines
        lines = ["# irrelevant line"] * 30
        lines[0] = "def important_function(x: int) -> bool:"
        lines[1] = "    return x > 0"
        code = "\n".join(lines)

        chunk = EvidenceChunk(
            source_uri="test.py", source_type="code",
            start_line=1, end_line=30, content=code,
        )

        compressed = compress_chunks([chunk], "important function", target_ratio=0.2)
        assert "omitted" in compressed[0].content

    def test_short_chunk_not_compressed(self) -> None:
        """Chunks with <= 5 lines are not compressed."""
        from egce.compress import compress_chunks
        from egce.retrieve import EvidenceChunk

        code = "def foo():\n    return 1\n"
        chunk = EvidenceChunk(
            source_uri="small.py", source_type="code",
            start_line=1, end_line=2, content=code,
        )

        compressed = compress_chunks([chunk], "foo")
        assert compressed[0].content == code

    def test_provenance_preserved(self) -> None:
        """Compression preserves source_uri and line numbers."""
        from egce.compress import compress_chunks
        from egce.retrieve import EvidenceChunk

        chunk = EvidenceChunk(
            source_uri="router.py", source_type="code",
            start_line=42, end_line=80,
            content="def dispatch():\n" + "    pass\n" * 20,
            symbols=["dispatch"],
            score=0.9,
        )

        compressed = compress_chunks([chunk], "dispatch router")
        assert compressed[0].source_uri == "router.py"
        assert compressed[0].start_line == 42
        assert compressed[0].end_line == 80
        assert compressed[0].symbols == ["dispatch"]


# ======================================================================
# focused repo map tests
# ======================================================================


class TestFocusedRepoMap:
    """Test the focused_text() method on RepoMapResult."""

    def test_focused_text_expands_focus_files(self, tmp_path: Path) -> None:
        (tmp_path / "important.py").write_text(textwrap.dedent("""\
            import os

            class Core:
                def run(self): pass
        """))
        (tmp_path / "other.py").write_text(textwrap.dedent("""\
            def helper(): pass
        """))
        (tmp_path / "another.py").write_text(textwrap.dedent("""\
            class Misc:
                def do_thing(self): pass
        """))

        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan()
        focused = result.focused_text({"important.py"})

        # important.py should have full detail
        assert "class Core" in focused
        assert "def run" in focused
        assert "import os" in focused

        # other files should appear in summary
        assert "other.py" in focused
        assert "another.py" in focused

    def test_focused_text_compact_others(self, tmp_path: Path) -> None:
        """Non-focused files should be compact (no symbol detail)."""
        (tmp_path / "main.py").write_text("def main(): pass\ndef other(): pass\n")
        (tmp_path / "lib.py").write_text("class Lib:\n    def method(self): pass\n")

        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan()
        focused = result.focused_text({"main.py"})

        # lib.py listed in summary without method detail
        assert "lib.py" in focused
        # "def method" should NOT appear (it's in non-focused lib.py)
        assert "def method" not in focused
        # main.py should have full detail
        assert "def main()" in focused
