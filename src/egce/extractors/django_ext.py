"""Django framework extractor."""

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

# Django URL patterns: path("route/", view_func, ...)
_URL_RE = re.compile(r"path\s*\(\s*[\"']([^\"']*)[\"']\s*,\s*(\w[\w.]*)")

# Django model: class Foo(models.Model):
_MODEL_RE = re.compile(r"class\s+(\w+)\s*\(\s*(?:models\.Model|AbstractUser|AbstractBaseUser)\s*\)\s*:")

# Django field: name = models.CharField(...)
_FIELD_DEF_RE = re.compile(
    r"^\s{4}(\w+)\s*=\s*models\.(\w+)\s*\("
)


@register_extractor
class DjangoExtractor(FrameworkExtractor):
    name = "django"
    language = "python"
    project_type = "backend"
    detect_markers = [
        ("pyproject.toml", "django"),
        ("requirements.txt", "django"),
        ("manage.py", "django"),
    ]

    def extract_routes(self, root: Path, files: dict[str, str]) -> list[RouteInfo]:
        routes: list[RouteInfo] = []
        for rel, content in files.items():
            if not rel.endswith(".py"):
                continue
            if "urls" not in rel and "urlpatterns" not in content:
                continue
            for i, line in enumerate(content.splitlines()):
                m = _URL_RE.search(line)
                if m:
                    path = "/" + m.group(1).strip("/") if m.group(1) else "/"
                    handler = m.group(2)
                    routes.append(RouteInfo(
                        method="ALL",
                        path=path,
                        file=rel,
                        line=i + 1,
                        function_name=handler,
                    ))
        return routes

    def extract_models(self, root: Path, files: dict[str, str]) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for rel, content in files.items():
            if not rel.endswith(".py"):
                continue
            if "models" not in rel and "models.Model" not in content:
                continue
            lines = content.splitlines()
            for i, line in enumerate(lines):
                m = _MODEL_RE.search(line)
                if m:
                    name = m.group(1)
                    fields = _extract_django_fields(lines, i + 1)
                    models.append(ModelInfo(
                        name=name,
                        file=rel,
                        line=i + 1,
                        kind="entity",
                        base_class="models.Model",
                        fields=fields,
                    ))
        return models


def _extract_django_fields(lines: list[str], start: int) -> list[ModelFieldInfo]:
    fields: list[ModelFieldInfo] = []
    for i in range(start, min(start + 50, len(lines))):
        line = lines[i]
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        m = _FIELD_DEF_RE.match(line)
        if m:
            fname = m.group(1)
            ftype = m.group(2)
            if fname.startswith("_"):
                continue
            nullable = "null=True" in line
            fields.append(ModelFieldInfo(
                name=fname,
                type=ftype,
                required=not nullable,
            ))
    return fields
