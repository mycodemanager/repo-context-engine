"""Base classes and registry for framework extractors."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Data models — unified output regardless of tech stack
# ---------------------------------------------------------------------------


@dataclass
class RouteInfo:
    """An API route definition."""

    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str  # /api/v1/users/{id}
    file: str  # relative path
    line: int
    function_name: str = ""
    params: list[str] = field(default_factory=list)  # ["body.name: string", "path.id: int"]
    response: str = ""  # short description of response


@dataclass
class ModelFieldInfo:
    """A single field in a data model."""

    name: str
    type: str
    required: bool = True
    description: str = ""


@dataclass
class ModelInfo:
    """A data model (ORM, Pydantic, interface, struct, etc.)."""

    name: str
    file: str
    line: int
    kind: str = "model"  # model, entity, schema, interface, struct
    base_class: str = ""
    fields: list[ModelFieldInfo] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)


@dataclass
class PageRouteInfo:
    """A frontend page route."""

    path: str  # /users, /dashboard
    component_file: str  # src/pages/Users.tsx
    component_name: str = ""
    line: int = 0


@dataclass
class ComponentInfo:
    """A frontend component."""

    name: str
    file: str
    line: int = 0
    props: list[str] = field(default_factory=list)  # ["name: string", "onClick: () => void"]
    used_in: list[str] = field(default_factory=list)  # files that import this component


@dataclass
class StoreInfo:
    """A state management store."""

    name: str
    file: str
    line: int = 0
    kind: str = "store"  # redux, pinia, zustand, vuex, mobx
    state_fields: list[str] = field(default_factory=list)  # ["users: User[]", "loading: boolean"]
    actions: list[str] = field(default_factory=list)  # ["fetchUsers", "addUser"]


@dataclass
class InfraInfo:
    """Infrastructure dependency."""

    name: str  # postgres, redis, rabbitmq, s3
    kind: str  # database, cache, queue, storage, external_api
    source: str = ""  # where detected (docker-compose.yaml, Dockerfile, etc.)
    details: str = ""  # connection string pattern, port, etc.


@dataclass
class EnvVarInfo:
    """An environment variable."""

    name: str
    source: str = ""  # .env.example, docker-compose.yaml, etc.
    default: str = ""
    description: str = ""


@dataclass
class ApiCallInfo:
    """A frontend API call to a backend endpoint."""

    method: str  # GET, POST, etc.
    path: str  # /api/v1/users
    file: str  # src/services/userApi.ts
    line: int = 0
    function_name: str = ""


@dataclass
class AnalysisResult:
    """Complete analysis output for a project."""

    project_name: str
    language: str
    framework: str = ""
    project_type: str = "backend"  # backend, frontend, fullstack, mobile

    routes: list[RouteInfo] = field(default_factory=list)
    models: list[ModelInfo] = field(default_factory=list)
    pages: list[PageRouteInfo] = field(default_factory=list)
    components: list[ComponentInfo] = field(default_factory=list)
    stores: list[StoreInfo] = field(default_factory=list)
    api_calls: list[ApiCallInfo] = field(default_factory=list)
    infra: list[InfraInfo] = field(default_factory=list)
    env_vars: list[EnvVarInfo] = field(default_factory=list)

    # --------------- rendering ---------------

    def render_routes(self) -> str:
        if not self.routes:
            return ""
        lines = ["# API Routes", ""]
        for r in self.routes:
            lines.append(f"## {r.method} {r.path}")
            lines.append(f"  file: {r.file}  L{r.line}")
            if r.function_name:
                lines.append(f"  handler: {r.function_name}")
            if r.params:
                lines.append("  params:")
                for p in r.params:
                    lines.append(f"    {p}")
            if r.response:
                lines.append(f"  response: {r.response}")
            lines.append("")
        return "\n".join(lines)

    def render_models(self) -> str:
        if not self.models:
            return ""
        lines = ["# Data Models", ""]
        for m in self.models:
            header = f"## {m.name}"
            if m.base_class:
                header += f" ({m.base_class})"
            lines.append(header)
            lines.append(f"  file: {m.file}  L{m.line}")
            lines.append(f"  kind: {m.kind}")
            if m.fields:
                lines.append("  fields:")
                for f in m.fields:
                    req = "" if f.required else " (optional)"
                    lines.append(f"    {f.name}: {f.type}{req}")
            if m.relationships:
                lines.append("  relationships:")
                for rel in m.relationships:
                    lines.append(f"    {rel}")
            lines.append("")
        return "\n".join(lines)

    def render_pages(self) -> str:
        if not self.pages:
            return ""
        lines = ["# Page Routes", ""]
        for p in self.pages:
            lines.append(f"## {p.path}")
            lines.append(f"  component: {p.component_file}")
            if p.component_name:
                lines.append(f"  name: {p.component_name}")
            lines.append("")
        return "\n".join(lines)

    def render_components(self) -> str:
        if not self.components:
            return ""
        lines = ["# Components", ""]
        for c in self.components:
            lines.append(f"## {c.name}")
            lines.append(f"  file: {c.file}  L{c.line}")
            if c.props:
                lines.append("  props:")
                for p in c.props:
                    lines.append(f"    {p}")
            if c.used_in:
                lines.append(f"  used_in: {', '.join(c.used_in)}")
            lines.append("")
        return "\n".join(lines)

    def render_stores(self) -> str:
        if not self.stores:
            return ""
        lines = ["# State Stores", ""]
        for s in self.stores:
            lines.append(f"## {s.name} ({s.kind})")
            lines.append(f"  file: {s.file}  L{s.line}")
            if s.state_fields:
                lines.append("  state:")
                for sf in s.state_fields:
                    lines.append(f"    {sf}")
            if s.actions:
                lines.append("  actions:")
                for a in s.actions:
                    lines.append(f"    {a}")
            lines.append("")
        return "\n".join(lines)

    def render_api_calls(self) -> str:
        if not self.api_calls:
            return ""
        lines = ["# API Calls (to backend)", ""]
        for a in self.api_calls:
            lines.append(f"## {a.method} {a.path}")
            lines.append(f"  file: {a.file}  L{a.line}")
            if a.function_name:
                lines.append(f"  function: {a.function_name}")
            lines.append("")
        return "\n".join(lines)

    def render_infra(self) -> str:
        if not self.infra:
            return ""
        lines = ["# Infrastructure", ""]
        for i in self.infra:
            lines.append(f"## {i.name} ({i.kind})")
            lines.append(f"  source: {i.source}")
            if i.details:
                lines.append(f"  details: {i.details}")
            lines.append("")
        return "\n".join(lines)

    def render_env_vars(self) -> str:
        if not self.env_vars:
            return ""
        lines = ["# Environment Variables", ""]
        for e in self.env_vars:
            default = f" = {e.default}" if e.default else ""
            lines.append(f"  {e.name}{default}")
            if e.description:
                lines.append(f"    # {e.description}")
            if e.source:
                lines.append(f"    source: {e.source}")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extractor base class
# ---------------------------------------------------------------------------


class FrameworkExtractor:
    """Base class for framework-specific extractors.

    Subclasses implement extraction methods for routes, models, pages, etc.
    Only override the methods relevant to the framework.
    """

    name: str = ""
    language: str = ""
    project_type: str = "backend"  # backend, frontend, fullstack, mobile
    detect_markers: list[tuple[str, str]] = []  # [(dep_file, keyword), ...]

    def extract_routes(self, root: Path, files: dict[str, str]) -> list[RouteInfo]:
        return []

    def extract_models(self, root: Path, files: dict[str, str]) -> list[ModelInfo]:
        return []

    def extract_pages(self, root: Path, files: dict[str, str]) -> list[PageRouteInfo]:
        return []

    def extract_components(self, root: Path, files: dict[str, str]) -> list[ComponentInfo]:
        return []

    def extract_stores(self, root: Path, files: dict[str, str]) -> list[StoreInfo]:
        return []

    def extract_api_calls(self, root: Path, files: dict[str, str]) -> list[ApiCallInfo]:
        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[FrameworkExtractor]] = {}


def register_extractor(cls: type[FrameworkExtractor]) -> type[FrameworkExtractor]:
    """Register a framework extractor class."""
    _REGISTRY[cls.name] = cls
    return cls


def get_extractor(name: str) -> FrameworkExtractor | None:
    cls = _REGISTRY.get(name)
    return cls() if cls else None


def list_extractors() -> list[str]:
    return list(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------


def detect_frameworks(root: Path) -> list[FrameworkExtractor]:
    """Auto-detect frameworks used in a project by scanning dependency files."""
    detected: list[FrameworkExtractor] = []

    # Read dependency files once
    dep_contents: dict[str, str] = {}
    for cls in _REGISTRY.values():
        for dep_file, _ in cls.detect_markers:
            if dep_file not in dep_contents:
                fpath = root / dep_file
                if fpath.exists():
                    try:
                        dep_contents[dep_file] = fpath.read_text(errors="replace").lower()
                    except OSError:
                        pass

    for cls in _REGISTRY.values():
        for dep_file, keyword in cls.detect_markers:
            content = dep_contents.get(dep_file, "")
            if keyword.lower() in content:
                detected.append(cls())
                break

    return detected


# ---------------------------------------------------------------------------
# Infrastructure & env scanning (framework-independent)
# ---------------------------------------------------------------------------


def _scan_infra(root: Path) -> list[InfraInfo]:
    """Detect infrastructure from Docker and config files."""
    infra: list[InfraInfo] = []

    # docker-compose.yaml
    for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"):
        fpath = root / name
        if fpath.exists():
            content = fpath.read_text(errors="replace").lower()
            _detect_infra_in_compose(content, name, infra)
            break

    # Dockerfile
    for name in ("Dockerfile", "dockerfile"):
        fpath = root / name
        if fpath.exists():
            content = fpath.read_text(errors="replace").lower()
            if "postgres" in content:
                infra.append(InfraInfo("PostgreSQL", "database", name))
            if "mysql" in content:
                infra.append(InfraInfo("MySQL", "database", name))
            if "redis" in content:
                infra.append(InfraInfo("Redis", "cache", name))
            break

    return _dedupe_infra(infra)


def _detect_infra_in_compose(content: str, source: str, infra: list[InfraInfo]) -> None:
    checks = [
        ("postgres", "PostgreSQL", "database"),
        ("mysql", "MySQL", "database"),
        ("mariadb", "MariaDB", "database"),
        ("mongo", "MongoDB", "database"),
        ("redis", "Redis", "cache"),
        ("rabbitmq", "RabbitMQ", "queue"),
        ("kafka", "Kafka", "queue"),
        ("elasticsearch", "Elasticsearch", "search"),
        ("minio", "MinIO", "storage"),
        ("nginx", "Nginx", "proxy"),
    ]
    for keyword, name, kind in checks:
        if keyword in content:
            infra.append(InfraInfo(name, kind, source))


def _dedupe_infra(infra: list[InfraInfo]) -> list[InfraInfo]:
    seen: set[str] = set()
    result: list[InfraInfo] = []
    for i in infra:
        if i.name not in seen:
            seen.add(i.name)
            result.append(i)
    return result


def _scan_env_vars(root: Path) -> list[EnvVarInfo]:
    """Extract environment variables from .env.example and similar files."""
    env_vars: list[EnvVarInfo] = []
    env_files = [".env.example", ".env.sample", ".env.template", ".env.development"]

    for name in env_files:
        fpath = root / name
        if fpath.exists():
            try:
                for line in fpath.read_text(errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, val = line.partition("=")
                        env_vars.append(EnvVarInfo(
                            name=key.strip(),
                            default=val.strip(),
                            source=name,
                        ))
            except OSError:
                pass
            break  # use first found

    return env_vars


# ---------------------------------------------------------------------------
# Read source files helper
# ---------------------------------------------------------------------------


_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", "target", ".egce", ".tox", ".mypy_cache", ".pytest_cache",
}

_SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".dart", ".vue", ".svelte",
}


def _read_source_files(
    root: Path,
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    max_file_bytes: int = 256_000,
) -> dict[str, str]:
    """Read all source files into a dict of {relative_path: content}."""
    from egce.repo_map import _match_pattern

    files: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            if fpath.suffix not in _SOURCE_EXTS:
                continue
            rel = str(fpath.relative_to(root))
            if include and not any(_match_pattern(rel, p) for p in include):
                continue
            if exclude and any(_match_pattern(rel, p) for p in exclude):
                continue
            try:
                raw = fpath.read_bytes()
                if len(raw) > max_file_bytes:
                    continue
                files[rel] = raw.decode(errors="replace")
            except OSError:
                pass
    return files


# ---------------------------------------------------------------------------
# Run full analysis
# ---------------------------------------------------------------------------


def run_analysis(
    root: str | Path,
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> AnalysisResult:
    """Run all applicable extractors on a project and return unified results."""
    root = Path(root).resolve()
    project_name = root.name

    # Detect frameworks
    extractors = detect_frameworks(root)

    # Determine language and project type
    language = extractors[0].language if extractors else _guess_language(root)
    framework = ", ".join(e.name for e in extractors) if extractors else ""
    project_type = _determine_project_type(extractors)

    result = AnalysisResult(
        project_name=project_name,
        language=language,
        framework=framework,
        project_type=project_type,
    )

    # Read source files
    files = _read_source_files(root, include=include, exclude=exclude)

    # Run each extractor
    for ext in extractors:
        result.routes.extend(ext.extract_routes(root, files))
        result.models.extend(ext.extract_models(root, files))
        result.pages.extend(ext.extract_pages(root, files))
        result.components.extend(ext.extract_components(root, files))
        result.stores.extend(ext.extract_stores(root, files))
        result.api_calls.extend(ext.extract_api_calls(root, files))

    # Framework-independent scans
    result.infra = _scan_infra(root)
    result.env_vars = _scan_env_vars(root)

    return result


def _guess_language(root: Path) -> str:
    """Guess primary language from dependency files."""
    markers = [
        ("pyproject.toml", "python"), ("setup.py", "python"), ("requirements.txt", "python"),
        ("package.json", "javascript"), ("tsconfig.json", "typescript"),
        ("go.mod", "go"), ("Cargo.toml", "rust"),
        ("pom.xml", "java"), ("build.gradle", "java"),
        ("pubspec.yaml", "dart"),
    ]
    for fname, lang in markers:
        if (root / fname).exists():
            return lang
    return "unknown"


def _determine_project_type(extractors: list[FrameworkExtractor]) -> str:
    types = {e.project_type for e in extractors}
    if "frontend" in types and "backend" in types:
        return "fullstack"
    if "frontend" in types:
        return "frontend"
    if "mobile" in types:
        return "mobile"
    return "backend"
