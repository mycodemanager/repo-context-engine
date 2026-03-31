"""FastAPI framework extractor."""

from __future__ import annotations

import re
from pathlib import Path

from egce.extractors.base import (
    FrameworkExtractor,
    ModelFieldInfo,
    ModelInfo,
    RouteInfo,
    register_extractor,
)

# Patterns for FastAPI route decorators
_ROUTE_RE = re.compile(
    r"@\s*(?:\w+)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# Pattern for function def right after decorator
_FUNC_RE = re.compile(r"(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)")

# Pydantic / SQLModel model
_MODEL_CLASS_RE = re.compile(
    r"class\s+(\w+)\s*\(\s*(BaseModel|SQLModel|BaseSettings)\s*(?:,\s*\w+)*\s*\)\s*:"
)

# Field annotation: name: type
_FIELD_RE = re.compile(r"^\s{4}(\w+)\s*:\s*(.+?)(?:\s*=.*)?$")


@register_extractor
class FastAPIExtractor(FrameworkExtractor):
    name = "fastapi"
    language = "python"
    project_type = "backend"
    detect_markers = [
        ("pyproject.toml", "fastapi"),
        ("requirements.txt", "fastapi"),
        ("setup.py", "fastapi"),
    ]

    def extract_routes(self, root: Path, files: dict[str, str]) -> list[RouteInfo]:
        routes: list[RouteInfo] = []
        for rel, content in files.items():
            if not rel.endswith(".py"):
                continue
            lines = content.splitlines()
            for i, line in enumerate(lines):
                m = _ROUTE_RE.search(line)
                if m:
                    method = m.group(1).upper()
                    path = m.group(2)
                    func_name = ""
                    params: list[str] = []

                    # look for function def in next few lines
                    for j in range(i + 1, min(i + 5, len(lines))):
                        fm = _FUNC_RE.search(lines[j])
                        if fm:
                            func_name = fm.group(1)
                            raw_params = fm.group(2)
                            params = _parse_params(raw_params)
                            break

                    routes.append(RouteInfo(
                        method=method,
                        path=path,
                        file=rel,
                        line=i + 1,
                        function_name=func_name,
                        params=params,
                    ))
        return routes

    def extract_models(self, root: Path, files: dict[str, str]) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for rel, content in files.items():
            if not rel.endswith(".py"):
                continue
            lines = content.splitlines()
            for i, line in enumerate(lines):
                m = _MODEL_CLASS_RE.search(line)
                if m:
                    name = m.group(1)
                    base = m.group(2)
                    fields = _extract_fields(lines, i + 1)
                    models.append(ModelInfo(
                        name=name,
                        file=rel,
                        line=i + 1,
                        kind="model" if base == "BaseModel" else "entity" if base == "SQLModel" else "config",
                        base_class=base,
                        fields=fields,
                    ))
        return models


def _parse_params(raw: str) -> list[str]:
    """Parse function parameters into param descriptions."""
    params: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part or part == "self" or part.startswith("*"):
            continue
        # skip dependencies like Depends(...)
        if "Depends(" in part or "Security(" in part:
            continue
        if ":" in part:
            pname, ptype = part.split(":", 1)
            pname = pname.strip()
            ptype = ptype.split("=")[0].strip()
            params.append(f"{pname}: {ptype}")
    return params


def _extract_fields(lines: list[str], start: int) -> list[ModelFieldInfo]:
    """Extract field annotations from a class body."""
    fields: list[ModelFieldInfo] = []
    for i in range(start, min(start + 50, len(lines))):
        line = lines[i]
        if line and not line[0].isspace() and not line.startswith("#"):
            break  # left class body
        m = _FIELD_RE.match(line)
        if m:
            fname = m.group(1)
            ftype = m.group(2).strip()
            if fname.startswith("_"):
                continue
            optional = "Optional" in ftype or "None" in ftype or "| None" in ftype
            fields.append(ModelFieldInfo(name=fname, type=ftype, required=not optional))
    return fields
