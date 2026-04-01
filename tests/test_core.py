"""Tests for the three core EGCE modules."""

from __future__ import annotations

import textwrap
from pathlib import Path


# ======================================================================
# repo_map tests
# ======================================================================


class TestRepoMap:
    """Test RepoMap scanning and symbol extraction."""

    def test_scan_python_file(self, tmp_path: Path) -> None:
        """Parse a Python file and extract classes, functions, imports."""
        code = textwrap.dedent("""\
            import os
            from pathlib import Path

            def hello(name: str) -> str:
                return f"Hello, {name}"

            class Greeter:
                def __init__(self, prefix: str):
                    self.prefix = prefix

                def greet(self, name: str) -> str:
                    return f"{self.prefix} {name}"
        """)
        (tmp_path / "app.py").write_text(code)

        from egce.repo_map import RepoMap

        repo = RepoMap(tmp_path)
        result = repo.scan()

        assert len(result.files) == 1
        fi = result.files[0]
        assert fi.path == "app.py"
        assert fi.language == "python"

        # imports
        assert len(fi.imports) == 2
        assert fi.imports[0].module == "os"
        assert fi.imports[1].module == "pathlib"
        assert "Path" in fi.imports[1].names

        # symbols
        assert len(fi.symbols) == 2
        func = fi.symbols[0]
        assert func.name == "hello"
        assert func.kind == "function"
        assert "name: str" in func.signature

        cls = fi.symbols[1]
        assert cls.name == "Greeter"
        assert cls.kind == "class"
        assert len(cls.children) == 2  # __init__ + greet

    def test_scan_ignores_dirs(self, tmp_path: Path) -> None:
        """Directories like __pycache__ and node_modules are skipped."""
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.py").write_text("x = 1")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lib.js").write_text("export default 1")
        (tmp_path / "real.py").write_text("def main(): pass")

        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan()
        paths = [f.path for f in result.files]
        assert "real.py" in paths
        assert not any("__pycache__" in p for p in paths)
        assert not any("node_modules" in p for p in paths)

    def test_to_text_output(self, tmp_path: Path) -> None:
        """to_text() produces readable output."""
        (tmp_path / "main.py").write_text("def run(): pass\n")

        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan()
        text = result.to_text()
        assert "main.py" in text
        assert "def run()" in text

    def test_scan_exclude(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("x = 1\n")
        (tmp_path / "skip.py").write_text("y = 2\n")

        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan(exclude=["skip.py"])
        paths = [f.path for f in result.files]
        assert "keep.py" in paths
        assert "skip.py" not in paths

    def test_empty_repo(self, tmp_path: Path) -> None:
        from egce.repo_map import RepoMap

        result = RepoMap(tmp_path).scan()
        assert result.files == []
        assert result.to_text().startswith("# Repo Map:")


# ======================================================================
# packer tests
# ======================================================================


class TestPacker:
    """Test ContextPacker token budget and slot logic."""

    def test_basic_packing(self) -> None:
        from egce.packer import ContextPacker

        packer = ContextPacker(token_budget=10000)
        packer.set_slot("system", "You are a helpful assistant.")
        packer.set_slot("task", "Fix the bug.")
        result = packer.build()
        assert "<system>" in result
        assert "<task>" in result
        assert "helpful assistant" in result
        assert "Fix the bug" in result

    def test_slot_ordering(self) -> None:
        """Slots should appear in canonical order regardless of insertion order."""
        from egce.packer import ContextPacker

        packer = ContextPacker(token_budget=10000)
        packer.set_slot("evidence", "some evidence")
        packer.set_slot("system", "system rules")
        packer.set_slot("task", "the task")
        result = packer.build()

        sys_pos = result.index("<system>")
        task_pos = result.index("<task>")
        ev_pos = result.index("<evidence>")
        assert sys_pos < task_pos < ev_pos

    def test_over_budget_trims_low_priority(self) -> None:
        """When over budget, lower-priority slots get trimmed."""
        from egce.packer import ContextPacker, Priority

        packer = ContextPacker(token_budget=100)
        packer.set_slot("system", "Short system.", priority=Priority.CRITICAL)
        packer.set_slot("memory", "x " * 500, priority=Priority.LOW)  # huge
        result = packer.build()

        assert "Short system." in result
        # memory should be truncated or dropped
        assert len(result) < len("x " * 500)

    def test_stats(self) -> None:
        from egce.packer import ContextPacker

        packer = ContextPacker(token_budget=5000)
        packer.set_slot("system", "hello world")
        stats = packer.stats()
        assert stats["budget"] == 5000
        assert "system" in stats["slots"]
        assert stats["slots"]["system"]["tokens"] > 0

    def test_empty_slots_ignored(self) -> None:
        from egce.packer import ContextPacker

        packer = ContextPacker(token_budget=5000)
        result = packer.build()
        assert result == ""

    def test_custom_slot(self) -> None:
        from egce.packer import ContextPacker, Priority

        packer = ContextPacker(token_budget=10000)
        packer.set_slot("custom_data", "extra info", priority=Priority.NORMAL)
        result = packer.build()
        assert "<custom_data>" in result


# ======================================================================
# verify tests
# ======================================================================


class TestVerifier:
    """Test Verifier execution and result parsing."""

    def test_verify_passing_project(self, tmp_path: Path) -> None:
        """A project with a passing test."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "test_ok.py").write_text("def test_pass(): assert True\n")

        from egce.verify import Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run()
        # Should detect pytest
        assert len(result.checks) >= 1
        test_check = result.checks[0]
        assert test_check.passed

    def test_verify_failing_test(self, tmp_path: Path) -> None:
        """A project with a failing test."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "test_fail.py").write_text("def test_bad(): assert False\n")

        from egce.verify import Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run()
        assert not result.passed
        assert len(result.failed_checks) >= 1

    def test_to_feedback(self, tmp_path: Path) -> None:
        """to_feedback() produces usable text."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / "test_fail.py").write_text("def test_bad(): assert 1 == 2\n")

        from egce.verify import Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run()
        feedback = result.to_feedback()
        assert "Failure" in feedback or "FAILED" in feedback or "Failed" in feedback

    def test_custom_command(self, tmp_path: Path) -> None:
        from egce.verify import CheckKind, Verifier

        v = Verifier(tmp_path)
        result = v.run_command(CheckKind.CUSTOM, ["echo", "hello"])
        assert result.passed
        assert "hello" in result.stdout

    def test_command_not_found(self, tmp_path: Path) -> None:
        from egce.verify import CheckKind, Verifier

        v = Verifier(tmp_path)
        result = v.run_command(CheckKind.CUSTOM, ["nonexistent_command_xyz"])
        assert not result.passed
        assert "not found" in result.summary.lower()

    def test_verify_result_aggregation(self) -> None:
        from egce.verify import CheckKind, CheckResult, VerifyResult

        r = VerifyResult(
            checks=[
                CheckResult(kind=CheckKind.TEST, command="pytest", passed=True),
                CheckResult(kind=CheckKind.LINT, command="ruff", passed=False, summary="3 errors"),
            ]
        )
        assert not r.passed
        assert len(r.failed_checks) == 1
        assert r.failed_checks[0].kind == CheckKind.LINT

    def test_context_check_stale(self, tmp_path: Path) -> None:
        """Verify detects stale context when a route is missing from api-contracts.md."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["fastapi"]\n')
        (tmp_path / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/v1/users")
            async def list_users():
                return []
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        init_project(tmp_path)

        # Write context that doesn't mention the route
        (tmp_path / ".egce" / "context" / "api-contracts.md").write_text(
            "# API Contracts\n\nNo APIs documented yet.\n"
        )

        from egce.verify import CheckKind, Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run(kinds={CheckKind.CONTEXT})
        context_checks = [c for c in result.checks if c.kind == CheckKind.CONTEXT]
        assert len(context_checks) == 1
        assert not context_checks[0].passed
        assert "stale" in context_checks[0].summary

    def test_context_check_up_to_date(self, tmp_path: Path) -> None:
        """Verify passes when context mentions all routes."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["fastapi"]\n')
        (tmp_path / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/v1/users")
            async def list_users():
                return []
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        init_project(tmp_path)

        # Write context that mentions the route
        (tmp_path / ".egce" / "context" / "api-contracts.md").write_text(
            "# API Contracts\n\n- GET /api/v1/users — list users\n"
        )

        from egce.verify import CheckKind, Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run(kinds={CheckKind.CONTEXT})
        context_checks = [c for c in result.checks if c.kind == CheckKind.CONTEXT]
        assert len(context_checks) == 1
        assert context_checks[0].passed

    def test_context_check_skips_template_placeholder(self, tmp_path: Path) -> None:
        """Verify skips context files that are still template placeholders."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["fastapi"]\n')
        (tmp_path / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/v1/users")
            async def list_users():
                return []
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        init_project(tmp_path)
        # api-contracts.md is still the template placeholder — should be skipped

        from egce.verify import CheckKind, Verifier

        v = Verifier(tmp_path, timeout=30)
        result = v.run(kinds={CheckKind.CONTEXT})
        context_checks = [c for c in result.checks if c.kind == CheckKind.CONTEXT]
        assert len(context_checks) == 1
        assert context_checks[0].passed
