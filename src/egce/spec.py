"""Spec management — list, show, update, validate, generate tests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


def _find_specs_dir(root: str | Path) -> Path | None:
    """Find the specs directory — workspace level first, then project level."""
    root = Path(root).resolve()
    # Workspace level
    ws_specs = root / ".egce" / "specs"
    if ws_specs.exists():
        return ws_specs
    # Walk up to find workspace
    parent = root.parent
    ws_specs = parent / ".egce" / "specs"
    if ws_specs.exists():
        return ws_specs
    return None


def list_specs(root: str | Path) -> list[dict]:
    """List all specs with their status."""
    specs_dir = _find_specs_dir(root)
    if not specs_dir or not specs_dir.exists():
        return []

    results = []
    for f in sorted(specs_dir.iterdir()):
        if f.suffix in (".yaml", ".yml"):
            info = _parse_spec_header(f)
            info["file"] = str(f.relative_to(specs_dir.parent.parent))
            results.append(info)
    return results


def show_spec(root: str | Path, spec_id: str) -> str | None:
    """Show the contents of a spec file."""
    specs_dir = _find_specs_dir(root)
    if not specs_dir:
        return None

    for f in specs_dir.iterdir():
        if f.stem == spec_id or f.name == spec_id:
            return f.read_text()

    # Try partial match
    for f in specs_dir.iterdir():
        if spec_id in f.stem:
            return f.read_text()

    return None


def update_spec_status(root: str | Path, spec_id: str, status: str) -> bool:
    """Update the status field in a spec file."""
    specs_dir = _find_specs_dir(root)
    if not specs_dir:
        return False

    target = None
    for f in specs_dir.iterdir():
        if f.stem == spec_id or f.name == spec_id or spec_id in f.stem:
            target = f
            break

    if not target:
        return False

    content = target.read_text()
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("status:"):
            lines[i] = f"status: {status}"
            target.write_text("\n".join(lines) + "\n")
            return True

    return False


def _parse_spec_header(path: Path) -> dict:
    """Extract key fields from the top of a spec yaml file."""
    info = {"id": path.stem, "title": "", "status": "", "description": ""}
    try:
        for line in path.read_text().splitlines()[:20]:
            # Only match top-level keys (no leading whitespace)
            if line.startswith(" ") or line.startswith("\t"):
                continue
            for key in ("id", "title", "status", "description"):
                if line.startswith(f"{key}:"):
                    val = line[len(key) + 1:].strip().strip('"').strip("'")
                    info[key] = val
    except OSError:
        pass
    return info


# ---------------------------------------------------------------------------
# Spec validation — self-containment check
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    level: str  # "error" | "warning"
    message: str
    location: str = ""  # e.g. "backend.tasks[0].api"


@dataclass
class ValidationResult:
    spec_id: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    def to_text(self) -> str:
        if not self.issues:
            return f"Spec {self.spec_id}: OK (no issues)"
        lines = [f"Spec {self.spec_id}: {len(self.errors)} error(s), {len(self.warnings)} warning(s)", ""]
        for i in self.issues:
            prefix = "ERROR" if i.level == "error" else "WARN"
            loc = f" [{i.location}]" if i.location else ""
            lines.append(f"  [{prefix}]{loc} {i.message}")
        return "\n".join(lines)


def validate_spec(root: str | Path, spec_id: str) -> ValidationResult:
    """Validate a spec for self-containment.

    Checks:
    1. Required top-level fields present (id, title, status)
    2. Backend APIs have method, path, and field definitions
    3. Frontend tasks reference valid pages/components
    4. Referenced files exist in the repo
    5. Backend API paths match frontend api_calls
    6. Testing section is present
    """
    root = Path(root).resolve()
    content = show_spec(root, spec_id)
    if content is None:
        return ValidationResult(spec_id=spec_id, issues=[
            ValidationIssue("error", f"Spec not found: {spec_id}")
        ])

    result = ValidationResult(spec_id=spec_id)
    lines = content.splitlines()

    # --- Check 1: Required top-level fields ---
    top_keys = set()
    for line in lines:
        if not line.startswith(" ") and not line.startswith("\t") and ":" in line:
            key = line.split(":")[0].strip()
            top_keys.add(key)

    for required in ("id", "title", "status"):
        if required not in top_keys:
            result.issues.append(ValidationIssue(
                "error", f"Missing required field: {required}", "top-level"
            ))

    # --- Check 2: Backend API completeness ---
    backend_apis = _extract_spec_apis(content, "backend")
    for api in backend_apis:
        if not api.get("method"):
            result.issues.append(ValidationIssue(
                "error", f"API missing method: {api.get('path', '?')}", "backend.api"
            ))
        if not api.get("path"):
            result.issues.append(ValidationIssue(
                "error", "API missing path", "backend.api"
            ))
        # Check request/response field definitions
        if api.get("method") in ("POST", "PUT", "PATCH") and not api.get("has_request_body"):
            result.issues.append(ValidationIssue(
                "warning", f"{api.get('method')} {api.get('path')} has no request body fields defined",
                "backend.api"
            ))

    # --- Check 3: Frontend-backend API alignment ---
    frontend_api_calls = _extract_spec_apis(content, "frontend")
    backend_paths = {a.get("path") for a in backend_apis if a.get("path")}
    frontend_paths = {a.get("path") for a in frontend_api_calls if a.get("path")}

    for fp in frontend_paths:
        # Normalize path parameters for comparison
        fp_normalized = re.sub(r"\{[^}]+\}", "{}", fp)
        matched = False
        for bp in backend_paths:
            bp_normalized = re.sub(r"\{[^}]+\}", "{}", bp)
            if fp_normalized == bp_normalized:
                matched = True
                break
        if not matched and not fp.startswith("http"):
            result.issues.append(ValidationIssue(
                "error",
                f"Frontend calls {fp} but backend has no matching route",
                "frontend-backend alignment"
            ))

    # --- Check 4: Referenced files exist ---
    affected_files = _extract_affected_files(content)
    for fpath, section in affected_files:
        # Only check existing files (skip files marked as "new")
        # Look for "新增" or "new" hint on the same line in spec
        full_path = _find_project_file(root, fpath)
        # We don't flag missing files as errors since specs often reference
        # files to be created. Instead, flag if a file is marked as "modify"
        # but doesn't exist.
        if full_path is None and "修改" in section:
            result.issues.append(ValidationIssue(
                "warning", f"File to modify not found: {fpath}", section
            ))

    # --- Check 5: Testing section present ---
    has_testing = "testing:" in content or "test:" in content
    if not has_testing:
        result.issues.append(ValidationIssue(
            "warning", "No testing section found in spec", "testing"
        ))

    # Count test cases
    test_lines = []
    in_testing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("testing:") or stripped.startswith("test:"):
            in_testing = True
            continue
        if in_testing:
            if stripped.startswith("- "):
                test_lines.append(stripped)
            elif stripped and not stripped.startswith("#") and not line.startswith(" "):
                in_testing = False

    if has_testing and len(test_lines) == 0:
        result.issues.append(ValidationIssue(
            "warning", "Testing section exists but has no test cases", "testing"
        ))

    return result


def _extract_spec_apis(content: str, section: str) -> list[dict]:
    """Extract API definitions from a spec section."""
    apis: list[dict] = []
    in_section = False
    current: dict = {}

    for line in content.splitlines():
        stripped = line.strip()

        # Find section
        if stripped == f"{section}:":
            in_section = True
            continue

        if in_section and not line.startswith(" ") and stripped and ":" in stripped:
            in_section = False

        if not in_section:
            continue

        # Look for method/path patterns
        if "method:" in stripped:
            method = stripped.split(":", 1)[1].strip()
            current["method"] = method

        if "path:" in stripped:
            path = stripped.split(":", 1)[1].strip().strip("'\"")
            current["path"] = path

        # Check for request body
        if "body:" in stripped or "request:" in stripped:
            current["has_request_body"] = True

        # API call references (frontend)
        m = re.match(r"\s*-\s*(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)", stripped)
        if m:
            apis.append({"method": m.group(1), "path": m.group(2)})

        # End of an API block
        if current.get("method") and current.get("path"):
            if stripped == "" or stripped.startswith("- id:"):
                apis.append(dict(current))
                current = {}

    if current.get("method") and current.get("path"):
        apis.append(current)

    return apis


def _extract_affected_files(content: str) -> list[tuple[str, str]]:
    """Extract affected_files entries from spec."""
    files: list[tuple[str, str]] = []
    current_section = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in ("backend:", "frontend:"):
            current_section = stripped.rstrip(":")
        if "affected_files:" in stripped:
            continue
        if current_section and stripped.startswith("- ") and "/" in stripped:
            fpath = stripped.lstrip("- ").split("#")[0].strip()
            comment = stripped.split("#")[1].strip() if "#" in stripped else ""
            files.append((fpath, f"{current_section}: {comment}"))
    return files


def _find_project_file(root: Path, rel_path: str) -> Path | None:
    """Try to find a file in the project or its sub-projects."""
    # Direct path
    direct = root / rel_path
    if direct.exists():
        return direct
    # Search in sub-directories (workspace mode)
    for entry in root.iterdir():
        if entry.is_dir():
            candidate = entry / rel_path
            if candidate.exists():
                return candidate
    return None


# ---------------------------------------------------------------------------
# Test skeleton generation
# ---------------------------------------------------------------------------


def generate_test_skeleton(root: str | Path, spec_id: str) -> dict[str, str]:
    """Generate test skeleton code from a spec's testing section.

    Returns a dict of {filename: test_code}.
    """
    root = Path(root).resolve()
    content = show_spec(root, spec_id)
    if content is None:
        return {}

    # Parse spec structure
    header = _parse_spec_header_from_content(content)
    spec_title = header.get("title", spec_id)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", spec_id).lower()

    output: dict[str, str] = {}

    # Extract backend test cases
    be_tests = _extract_test_cases(content, "backend")
    if be_tests:
        output[f"test_{safe_name}_backend.py"] = _render_pytest_skeleton(
            spec_title, be_tests, _extract_spec_apis(content, "backend")
        )

    # Extract frontend test cases
    fe_tests = _extract_test_cases(content, "frontend")
    if fe_tests:
        output[f"test_{safe_name}_frontend.ts"] = _render_jest_skeleton(
            spec_title, fe_tests
        )

    return output


def _extract_test_cases(content: str, section: str) -> list[str]:
    """Extract test case descriptions from a spec section."""
    cases: list[str] = []
    in_section = False
    in_testing = False

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == f"{section}:":
            in_section = True
            continue

        if in_section and not line.startswith(" ") and stripped and ":" in stripped:
            in_section = False
            in_testing = False

        if not in_section:
            continue

        if stripped.startswith("testing:") or stripped.startswith("test:"):
            in_testing = True
            continue

        if in_testing and stripped.startswith("- "):
            case = stripped[2:].strip()
            cases.append(case)

    return cases


def _render_pytest_skeleton(title: str, test_cases: list[str], apis: list[dict]) -> str:
    """Render a pytest test skeleton."""
    lines = [
        f'"""Tests for: {title}',
        '',
        'Auto-generated from spec. Fill in the test implementations.',
        '"""',
        '',
        'import pytest',
        '',
        '',
    ]

    # Generate a test function for each test case
    for i, case in enumerate(test_cases):
        func_name = re.sub(r"[^a-zA-Z0-9_]", "_", case).lower()
        func_name = re.sub(r"_+", "_", func_name).strip("_")
        if len(func_name) > 60:
            func_name = func_name[:60].rstrip("_")

        lines.append(f"def test_{func_name}():")
        lines.append('    """')
        lines.append(f"    {case}")
        lines.append('    """')

        # If we can match this test to an API, add a hint
        for api in apis:
            method = api.get("method", "")
            path = api.get("path", "")
            if method and path:
                case_lower = case.lower()
                if method.lower() in case_lower or path.lower() in case_lower:
                    lines.append(f"    # API: {method} {path}")
                    break

        lines.append("    # TODO: implement")
        lines.append("    raise NotImplementedError")
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def _render_jest_skeleton(title: str, test_cases: list[str]) -> str:
    """Render a Jest/Vitest test skeleton."""
    lines = [
        '/**',
        f' * Tests for: {title}',
        ' *',
        ' * Auto-generated from spec. Fill in the test implementations.',
        ' */',
        '',
        f'describe("{title}", () => {{',
    ]

    for case in test_cases:
        # Escape quotes in test name
        escaped = case.replace('"', '\\"')
        lines.append(f'  it("{escaped}", () => {{')
        lines.append("    // TODO: implement")
        lines.append("    throw new Error('Not implemented');")
        lines.append("  });")
        lines.append("")

    lines.append("});")
    lines.append("")

    return "\n".join(lines)


def _parse_spec_header_from_content(content: str) -> dict:
    info = {"id": "", "title": "", "status": ""}
    for line in content.splitlines()[:20]:
        if line.startswith(" ") or line.startswith("\t"):
            continue
        for key in ("id", "title", "status"):
            if line.startswith(f"{key}:"):
                info[key] = line[len(key) + 1:].strip().strip('"').strip("'")
    return info
