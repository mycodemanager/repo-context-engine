"""Express.js framework extractor."""

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

# app.get("/path", ...) or router.post("/path", ...)
_ROUTE_RE = re.compile(
    r"(?:\w+)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[\"'`]([^\"'`]+)[\"'`]",
    re.IGNORECASE,
)

# TypeScript interface: interface Foo { ... }
_INTERFACE_RE = re.compile(r"(?:export\s+)?interface\s+(\w+)")

# TypeScript type: type Foo = { ... }
_TYPE_RE = re.compile(r"(?:export\s+)?type\s+(\w+)\s*=\s*\{")

# Field in interface/type: name: type
_TS_FIELD_RE = re.compile(r"^\s+(\w+)(\??)\s*:\s*(.+?)\s*;?\s*$")

# Mongoose schema: new Schema({...})
_MONGOOSE_RE = re.compile(r"(?:new\s+(?:mongoose\.)?Schema|mongoose\.model)\s*\(\s*[\"']?(\w+)?")


@register_extractor
class ExpressExtractor(FrameworkExtractor):
    name = "express"
    language = "javascript"
    project_type = "backend"
    detect_markers = [
        ("package.json", "express"),
    ]

    def extract_routes(self, root: Path, files: dict[str, str]) -> list[RouteInfo]:
        routes: list[RouteInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".js", ".ts", ".mjs")):
                continue
            for i, line in enumerate(content.splitlines()):
                m = _ROUTE_RE.search(line)
                if m:
                    method = m.group(1).upper()
                    path = m.group(2)
                    routes.append(RouteInfo(
                        method=method,
                        path=path,
                        file=rel,
                        line=i + 1,
                    ))
        return routes

    def extract_models(self, root: Path, files: dict[str, str]) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".ts", ".js")):
                continue
            lines = content.splitlines()
            for i, line in enumerate(lines):
                # TypeScript interfaces
                m = _INTERFACE_RE.search(line)
                if m:
                    name = m.group(1)
                    fields = _extract_ts_fields(lines, i + 1)
                    models.append(ModelInfo(
                        name=name, file=rel, line=i + 1,
                        kind="interface", fields=fields,
                    ))
                    continue

                # TypeScript type aliases
                m = _TYPE_RE.search(line)
                if m:
                    name = m.group(1)
                    fields = _extract_ts_fields(lines, i + 1)
                    models.append(ModelInfo(
                        name=name, file=rel, line=i + 1,
                        kind="type", fields=fields,
                    ))
                    continue

                # Mongoose models
                m = _MONGOOSE_RE.search(line)
                if m and m.group(1):
                    models.append(ModelInfo(
                        name=m.group(1), file=rel, line=i + 1,
                        kind="schema", base_class="mongoose.Schema",
                    ))
        return models


def _extract_ts_fields(lines: list[str], start: int) -> list[ModelFieldInfo]:
    fields: list[ModelFieldInfo] = []
    brace_depth = 1
    for i in range(start, min(start + 50, len(lines))):
        line = lines[i]
        brace_depth += line.count("{") - line.count("}")
        if brace_depth <= 0:
            break
        m = _TS_FIELD_RE.match(line)
        if m:
            fname = m.group(1)
            optional = m.group(2) == "?"
            ftype = m.group(3).rstrip(";").strip()
            fields.append(ModelFieldInfo(name=fname, type=ftype, required=not optional))
    return fields
