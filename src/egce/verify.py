"""Verifier — run compilation, tests, and linters against a codebase.

The verifier executes external tools (pytest, ruff, mypy, npm test, go
test, etc.) and returns structured results that can be fed back into the
context packer's ``verifier_feedback`` slot.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CheckKind(str, Enum):
    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    BUILD = "build"
    CONTEXT = "context"
    CUSTOM = "custom"


@dataclass
class CheckResult:
    """Result of a single verification check."""

    kind: CheckKind
    command: str
    passed: bool
    duration_s: float = 0.0
    stdout: str = ""
    stderr: str = ""
    summary: str = ""  # short human-readable summary


@dataclass
class VerifyResult:
    """Aggregate result of all verification checks."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_feedback(self, *, max_chars: int = 3000) -> str:
        """Render as compact feedback text for LLM context."""
        if self.passed:
            names = ", ".join(c.command for c in self.checks)
            return f"All checks passed: {names}"

        lines: list[str] = ["## Verification Failures", ""]
        budget = max_chars
        for c in self.failed_checks:
            header = f"### [{c.kind.value}] `{c.command}` — FAILED"
            lines.append(header)
            budget -= len(header) + 2

            detail = c.summary or c.stderr or c.stdout
            if len(detail) > budget:
                detail = detail[:budget] + "\n... [truncated]"
            lines.append(detail)
            lines.append("")
            budget -= len(detail) + 2
            if budget <= 0:
                lines.append("... [more failures omitted]")
                break

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

_DETECT_RULES: list[tuple[str, CheckKind, list[str]]] = [
    # (marker file, kind, command)
    ("pyproject.toml", CheckKind.TEST, [sys.executable, "-m", "pytest", "--tb=short", "-q"]),
    ("setup.py", CheckKind.TEST, [sys.executable, "-m", "pytest", "--tb=short", "-q"]),
    ("package.json", CheckKind.TEST, ["npm", "test"]),
    ("go.mod", CheckKind.TEST, ["go", "test", "./..."]),
    ("Cargo.toml", CheckKind.TEST, ["cargo", "test"]),
]

_DETECT_LINT: list[tuple[str, CheckKind, list[str]]] = [
    ("pyproject.toml", CheckKind.LINT, [sys.executable, "-m", "ruff", "check", "."]),
    ("package.json", CheckKind.LINT, ["npx", "eslint", "."]),
    ("Cargo.toml", CheckKind.LINT, ["cargo", "clippy"]),
]


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class Verifier:
    """Run verification checks against a repository.

    Usage::

        v = Verifier("/path/to/repo")
        result = v.run()
        if not result.passed:
            print(result.to_feedback())
    """

    def __init__(
        self,
        root: str | Path,
        *,
        timeout: int = 120,
        checks: list[tuple[CheckKind, list[str]]] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.timeout = timeout
        self._custom_checks = checks

    def run(self, *, kinds: set[CheckKind] | None = None) -> VerifyResult:
        """Execute all applicable checks and return aggregated results.

        Parameters
        ----------
        kinds : if provided, only run checks of these kinds
        """
        checks = self._resolve_checks()
        if kinds:
            checks = [(k, cmd) for k, cmd in checks if k in kinds]

        result = VerifyResult()
        for kind, cmd in checks:
            cr = self._run_one(kind, cmd)
            result.checks.append(cr)

        # Context freshness check
        if kinds is None or CheckKind.CONTEXT in kinds:
            cr = self._run_context_check()
            if cr is not None:
                result.checks.append(cr)

        return result

    def run_command(self, kind: CheckKind, cmd: list[str] | str) -> CheckResult:
        """Run a single custom command."""
        if isinstance(cmd, str):
            cmd = cmd.split()
        return self._run_one(kind, cmd)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_context_check(self) -> CheckResult | None:
        """Check if .egce/context/ files are stale relative to actual code."""
        if not (self.root / ".egce" / "context").exists():
            return None

        t0 = time.monotonic()
        try:
            from egce.workspace import check_context

            warnings = check_context(self.root)
            duration = time.monotonic() - t0
            if warnings:
                summary = f"{len(warnings)} stale context item(s)"
                detail = "\n".join(f"  {w}" for w in warnings)
                return CheckResult(
                    kind=CheckKind.CONTEXT,
                    command="egce sync --check",
                    passed=False,
                    duration_s=round(duration, 2),
                    stderr=detail,
                    summary=summary,
                )
            return CheckResult(
                kind=CheckKind.CONTEXT,
                command="egce sync --check",
                passed=True,
                duration_s=round(duration, 2),
                summary="Context files are up to date",
            )
        except Exception as e:
            duration = time.monotonic() - t0
            return CheckResult(
                kind=CheckKind.CONTEXT,
                command="egce sync --check",
                passed=False,
                duration_s=round(duration, 2),
                summary=f"Context check failed: {e}",
            )

    def _resolve_checks(self) -> list[tuple[CheckKind, list[str]]]:
        """Determine which checks to run based on repo contents."""
        if self._custom_checks:
            return list(self._custom_checks)

        checks: list[tuple[CheckKind, list[str]]] = []
        for marker, kind, cmd in _DETECT_RULES:
            if (self.root / marker).exists():
                checks.append((kind, cmd))
                break  # one test runner is enough
        for marker, kind, cmd in _DETECT_LINT:
            if (self.root / marker).exists():
                checks.append((kind, cmd))
                break
        return checks

    def _run_one(self, kind: CheckKind, cmd: list[str]) -> CheckResult:
        cmd_str = " ".join(cmd)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            duration = time.monotonic() - t0
            passed = proc.returncode == 0
            summary = _make_summary(kind, passed, proc.stdout, proc.stderr)
            return CheckResult(
                kind=kind,
                command=cmd_str,
                passed=passed,
                duration_s=round(duration, 2),
                stdout=proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                stderr=proc.stderr[-5000:] if len(proc.stderr) > 5000 else proc.stderr,
                summary=summary,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            return CheckResult(
                kind=kind,
                command=cmd_str,
                passed=False,
                duration_s=round(duration, 2),
                summary=f"Timed out after {self.timeout}s",
            )
        except FileNotFoundError:
            return CheckResult(
                kind=kind,
                command=cmd_str,
                passed=False,
                summary=f"Command not found: {cmd[0]}",
            )


def _make_summary(kind: CheckKind, passed: bool, stdout: str, stderr: str) -> str:
    """Extract a short summary from command output."""
    if passed:
        return "Passed"

    output = stderr or stdout
    lines = output.strip().splitlines()

    if kind == CheckKind.TEST:
        # pytest: last few lines usually have the summary
        for line in reversed(lines):
            if "failed" in line.lower() or "error" in line.lower() or "FAILED" in line:
                return line.strip()

    if kind == CheckKind.LINT:
        # count issues
        error_lines = [line for line in lines if "error" in line.lower() or "warning" in line.lower()]
        if error_lines:
            return f"{len(error_lines)} issue(s) found. First: {error_lines[0].strip()}"

    # fallback: last non-empty line
    for line in reversed(lines):
        if line.strip():
            return line.strip()[:200]

    return "Failed (no output)"
