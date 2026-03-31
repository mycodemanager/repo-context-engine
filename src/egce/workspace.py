"""Workspace initialization and management.

Handles:
- egce init: scan project, detect framework, generate .egce/ structure
- egce sync: re-scan and update analysis, check context freshness
- workspace.yaml: multi-project workspace configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from egce.extractors.base import AnalysisResult, run_analysis
from egce.repo_map import RepoMap


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class ProjectConfig:
    name: str
    path: str
    language: str = ""
    framework: str = ""


@dataclass
class WorkspaceConfig:
    name: str
    projects: list[ProjectConfig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

_CONTEXT_TEMPLATES = {
    "architecture.md": (
        "# Architecture\n\n"
        "<!-- Describe the overall architecture of this project. -->\n"
        "<!-- This file will be populated by AI after reviewing the analysis results. -->\n"
    ),
    "modules.md": (
        "# Modules\n\n"
        "<!-- Describe the major modules/packages and their responsibilities. -->\n"
    ),
    "conventions.md": (
        "# Development Conventions\n\n"
        "<!-- Describe naming conventions, code style, patterns used in this project. -->\n"
    ),
    "api-contracts.md": (
        "# API Contracts\n\n"
        "<!-- Describe the API interfaces this project exposes or consumes. -->\n"
    ),
    "data-models.md": (
        "# Data Models\n\n"
        "<!-- Describe the core data models, their fields, and relationships. -->\n"
    ),
}

_FRONTEND_CONTEXT_TEMPLATES = {
    "components.md": (
        "# Components\n\n"
        "<!-- Describe the component architecture, design system, and key components. -->\n"
    ),
}

_GITIGNORE_CONTENT = """\
# EGCE auto-generated analysis (regenerate with: egce sync)
analysis/
# Session files (local only)
sessions/
"""


def init_project(
    root: str | Path,
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> dict:
    """Initialize .egce/ directory for a single project.

    Returns a summary dict with stats.
    """
    root = Path(root).resolve()
    egce_dir = root / ".egce"
    analysis_dir = egce_dir / "analysis"
    context_dir = egce_dir / "context"
    specs_dir = egce_dir / "specs"
    sessions_dir = egce_dir / "sessions"

    # Create directories
    for d in [egce_dir, analysis_dir, context_dir, specs_dir, sessions_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # .gitignore for analysis/
    gitignore = egce_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_CONTENT)

    # Run analysis (framework detection + extraction)
    analysis = run_analysis(root, include=include, exclude=exclude)

    # Run repo map scan
    repo = RepoMap(root)
    scan_result = repo.scan(include=include, exclude=exclude)
    repo_map_text = scan_result.to_text()

    # Write analysis files
    (analysis_dir / "repo-map.txt").write_text(repo_map_text)

    # Module analysis from repo map
    modules_text = _build_modules_text(scan_result)
    (analysis_dir / "modules.txt").write_text(modules_text)

    # API routes
    routes_text = analysis.render_routes()
    if routes_text:
        (analysis_dir / "api-routes.txt").write_text(routes_text)

    # Data models
    models_text = analysis.render_models()
    if models_text:
        (analysis_dir / "data-models.txt").write_text(models_text)

    # Pages (frontend)
    pages_text = analysis.render_pages()
    if pages_text:
        (analysis_dir / "pages.txt").write_text(pages_text)

    # Components (frontend)
    components_text = analysis.render_components()
    if components_text:
        (analysis_dir / "components.txt").write_text(components_text)

    # API calls (frontend)
    api_calls_text = analysis.render_api_calls()
    if api_calls_text:
        (analysis_dir / "api-calls.txt").write_text(api_calls_text)

    # State stores (frontend)
    stores_text = analysis.render_stores()
    if stores_text:
        (analysis_dir / "stores.txt").write_text(stores_text)

    # Infrastructure
    infra_text = analysis.render_infra()
    if infra_text:
        (analysis_dir / "infrastructure.txt").write_text(infra_text)

    # Env vars
    env_text = analysis.render_env_vars()
    if env_text:
        (analysis_dir / "env-vars.txt").write_text(env_text)

    # Dependencies summary
    deps_text = _build_deps_text(root)
    if deps_text:
        (analysis_dir / "dependencies.txt").write_text(deps_text)

    # Generate config.yaml
    config = _build_config(root, analysis, include, exclude)
    (egce_dir / "config.yaml").write_text(config)

    # Create context templates (only if files don't exist)
    templates = dict(_CONTEXT_TEMPLATES)
    if analysis.project_type in ("frontend", "fullstack"):
        templates.update(_FRONTEND_CONTEXT_TEMPLATES)
    for fname, content in templates.items():
        fpath = context_dir / fname
        if not fpath.exists():
            fpath.write_text(content)

    # Generate CLAUDE.md
    claude_md = _build_claude_md(analysis)
    claude_path = root / "CLAUDE.md"
    if not claude_path.exists():
        claude_path.write_text(claude_md)

    # Stats
    n_files = len(scan_result.files)
    n_symbols = sum(len(f.symbols) + sum(len(s.children) for s in f.symbols) for f in scan_result.files)
    n_routes = len(analysis.routes)
    n_models = len(analysis.models)
    n_pages = len(analysis.pages)
    n_components = len(analysis.components)

    return {
        "project": root.name,
        "language": analysis.language,
        "framework": analysis.framework,
        "project_type": analysis.project_type,
        "files": n_files,
        "symbols": n_symbols,
        "routes": n_routes,
        "models": n_models,
        "pages": n_pages,
        "components": n_components,
        "infra": len(analysis.infra),
        "env_vars": len(analysis.env_vars),
    }


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync_project(
    root: str | Path,
    *,
    check_only: bool = False,
    diff: bool = False,
) -> dict:
    """Re-scan project and update analysis. Optionally check context freshness.

    Returns a dict with update stats and optional warnings.
    """
    root = Path(root).resolve()
    egce_dir = root / ".egce"
    analysis_dir = egce_dir / "analysis"

    if not egce_dir.exists():
        raise FileNotFoundError(f"No .egce/ directory found in {root}. Run 'egce init' first.")

    # Read existing config
    config_path = egce_dir / "config.yaml"
    include = None
    exclude = None
    if config_path.exists():
        include, exclude = _parse_config_scan(config_path.read_text())

    # Run fresh analysis
    analysis = run_analysis(root, include=include, exclude=exclude)
    repo = RepoMap(root)
    scan_result = repo.scan(include=include, exclude=exclude)

    warnings: list[str] = []

    if check_only or diff:
        # Compare with existing analysis
        warnings = _check_context_freshness(root, analysis, scan_result)
        if check_only:
            return {"warnings": warnings, "updated": False}

    # Write updated analysis
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "repo-map.txt").write_text(scan_result.to_text())
    (analysis_dir / "modules.txt").write_text(_build_modules_text(scan_result))

    if analysis.routes:
        (analysis_dir / "api-routes.txt").write_text(analysis.render_routes())
    if analysis.models:
        (analysis_dir / "data-models.txt").write_text(analysis.render_models())
    if analysis.pages:
        (analysis_dir / "pages.txt").write_text(analysis.render_pages())
    if analysis.components:
        (analysis_dir / "components.txt").write_text(analysis.render_components())
    if analysis.api_calls:
        (analysis_dir / "api-calls.txt").write_text(analysis.render_api_calls())
    if analysis.stores:
        (analysis_dir / "stores.txt").write_text(analysis.render_stores())

    infra_text = analysis.render_infra()
    if infra_text:
        (analysis_dir / "infrastructure.txt").write_text(infra_text)
    env_text = analysis.render_env_vars()
    if env_text:
        (analysis_dir / "env-vars.txt").write_text(env_text)

    return {
        "warnings": warnings,
        "updated": True,
        "files": len(scan_result.files),
        "routes": len(analysis.routes),
        "models": len(analysis.models),
    }


def _check_context_freshness(root: Path, analysis: AnalysisResult, scan_result) -> list[str]:
    """Compare analysis results against context/ files and report staleness."""
    warnings: list[str] = []
    context_dir = root / ".egce" / "context"

    # Check api-contracts.md against actual routes
    api_file = context_dir / "api-contracts.md"
    if api_file.exists() and analysis.routes:
        api_text = api_file.read_text()
        for route in analysis.routes:
            if route.path not in api_text:
                warnings.append(f"Route {route.method} {route.path} not mentioned in context/api-contracts.md")

    # Check modules.md against actual file structure
    modules_file = context_dir / "modules.md"
    if modules_file.exists():
        modules_text = modules_file.read_text()
        top_dirs = set()
        for fi in scan_result.files:
            parts = fi.path.split("/")
            if len(parts) > 1:
                top_dirs.add(parts[0])
        for d in top_dirs:
            if d not in modules_text and d not in ("tests", "test", "docs", "scripts"):
                warnings.append(f"Directory '{d}/' not mentioned in context/modules.md")

    # Check data-models.md against actual models
    dm_file = context_dir / "data-models.md"
    if dm_file.exists() and analysis.models:
        dm_text = dm_file.read_text()
        for model in analysis.models:
            if model.name not in dm_text:
                warnings.append(f"Model '{model.name}' not mentioned in context/data-models.md")

    return warnings


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def init_workspace(root: str | Path) -> dict:
    """Initialize a multi-project workspace.

    Detects git repos in subdirectories and creates workspace.yaml.
    """
    root = Path(root).resolve()
    egce_dir = root / ".egce"
    egce_dir.mkdir(parents=True, exist_ok=True)

    projects: list[dict] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / ".git").exists():
            # This is a git repo — init it
            stats = init_project(entry)
            projects.append(stats)

    # Write workspace.yaml
    ws_lines = [f"workspace: {root.name}", "projects:"]
    for p in projects:
        ws_lines.append(f"  - name: {p['project']}")
        ws_lines.append(f"    path: ./{p['project']}")
        ws_lines.append(f"    language: {p['language']}")
        if p.get("framework"):
            ws_lines.append(f"    framework: {p['framework']}")
    ws_lines.append("")
    (egce_dir / "workspace.yaml").write_text("\n".join(ws_lines))

    # Create workspace specs dir
    (egce_dir / "specs").mkdir(exist_ok=True)
    (egce_dir / "sessions").mkdir(exist_ok=True)

    return {
        "workspace": root.name,
        "projects": projects,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_modules_text(scan_result) -> str:
    """Build a module analysis from the repo map scan."""
    # Group files by top-level directory
    modules: dict[str, list] = {}
    for fi in scan_result.files:
        parts = fi.path.split("/")
        mod = parts[0] if len(parts) > 1 else "(root)"
        if mod not in modules:
            modules[mod] = []
        modules[mod].append(fi)

    lines = ["# Module Structure", ""]
    for mod, files in sorted(modules.items()):
        n_files = len(files)
        n_symbols = sum(len(f.symbols) for f in files)
        n_lines = sum(f.lines for f in files)
        lines.append(f"## {mod}/")
        lines.append(f"  files: {n_files}, symbols: {n_symbols}, lines: {n_lines}")

        # List key files (those with most symbols)
        top_files = sorted(files, key=lambda f: len(f.symbols), reverse=True)[:5]
        for f in top_files:
            if f.symbols:
                sym_names = ", ".join(s.name for s in f.symbols[:3])
                lines.append(f"  {f.path}: {sym_names}")
        lines.append("")

    return "\n".join(lines)


def _build_deps_text(root: Path) -> str:
    """Extract key dependencies from project dependency files."""
    lines = ["# Dependencies", ""]

    # Python
    for fname in ("pyproject.toml", "requirements.txt"):
        fpath = root / fname
        if fpath.exists():
            content = fpath.read_text(errors="replace")
            lines.append(f"## {fname}")
            # Extract dependency names (simplified)
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("["):
                    if ">=" in line or "==" in line or line.startswith("-"):
                        continue
                    if "=" in line and '"' in line:
                        # pyproject.toml dependency line
                        dep = line.strip().strip('",').strip()
                        if dep and not dep.startswith("["):
                            lines.append(f"  {dep}")
            lines.append("")
            break

    # Node.js
    pkg = root / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section, {})
                if deps:
                    lines.append(f"## {section}")
                    for name, ver in sorted(deps.items()):
                        lines.append(f"  {name}: {ver}")
                    lines.append("")
        except (json.JSONDecodeError, OSError):
            pass

    # Go
    gomod = root / "go.mod"
    if gomod.exists():
        lines.append("## go.mod")
        for line in gomod.read_text(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("//") and not line.startswith("module") and line not in ("require (", ")"):
                lines.append(f"  {line}")
        lines.append("")

    return "\n".join(lines) if len(lines) > 2 else ""


def _build_config(root: Path, analysis: AnalysisResult, include, exclude) -> str:
    """Generate config.yaml content."""
    lines = [
        f"project: {root.name}",
        f"language: {analysis.language}",
    ]
    if analysis.framework:
        lines.append(f"framework: {analysis.framework}")
    lines.append(f"project_type: {analysis.project_type}")
    lines.append("")
    lines.append("scan:")
    if include:
        lines.append(f"  include: {list(include)}")
    if exclude:
        lines.append(f"  exclude: {list(exclude)}")
    if not include and not exclude:
        lines.append("  # include: ['src/*']")
        lines.append("  # exclude: ['tests/*', 'docs/*']")
    lines.append("")
    lines.append("context_priority:")
    lines.append("  - context/architecture.md")
    lines.append("  - context/api-contracts.md")
    lines.append("  - context/modules.md")
    lines.append("  - context/conventions.md")
    lines.append("  - context/data-models.md")
    if analysis.project_type in ("frontend", "fullstack"):
        lines.append("  - context/components.md")
    lines.append("")
    return "\n".join(lines)


def _build_claude_md(analysis: AnalysisResult) -> str:
    """Generate project-specific CLAUDE.md."""
    project_type = analysis.project_type
    framework = analysis.framework or analysis.language

    md = f"""# Project: {analysis.project_name}

Type: {project_type} ({framework})

## EGCE Tools

This project uses EGCE for context management. Available commands:

```
egce scan .              # View repository structure
egce search "query" .    # Find relevant code
egce pipeline "task" .   # Full pipeline: search → compress → pack
egce verify .            # Run tests and linters
egce sync .              # Re-scan and update analysis
egce sync . --check      # Check if context files are stale
egce spec list           # List requirement specs
egce spec show <id>      # Show a spec
```

## Project Context

Read `.egce/context/` for project documentation:
- architecture.md — System architecture
- modules.md — Module responsibilities and boundaries
- conventions.md — Development conventions
- api-contracts.md — API interface definitions
- data-models.md — Data model documentation

Read `.egce/analysis/` for auto-generated analysis:
- repo-map.txt — File tree with class/function signatures
- modules.txt — Module structure and dependencies
"""

    if project_type == "backend":
        md += """- api-routes.txt — All API route definitions
- data-models.txt — All data model definitions
"""
    elif project_type in ("frontend", "fullstack"):
        md += """- pages.txt — Page routes
- components.txt — Component inventory
- api-calls.txt — Backend API calls
- stores.txt — State management stores
"""

    md += """
## Workflow

### Requirement Analysis
1. Read `.egce/context/` to understand existing architecture
2. Use `egce search` to find related existing code
3. Output a structured spec to `.egce/specs/` (if workspace) or communicate to user

### Development
1. Use `egce pipeline "<task>"` before starting each task
2. Follow conventions in `.egce/context/conventions.md`
3. After changes, run `egce verify .`

### Context Maintenance
After completing work that adds new modules, APIs, or models:
1. Run `egce sync . --check` to find stale context
2. Update relevant `.egce/context/` files
"""
    return md


def _parse_config_scan(config_text: str) -> tuple:
    """Parse include/exclude from config.yaml (simple YAML parsing)."""
    include = None
    exclude = None
    in_scan = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped == "scan:":
            in_scan = True
            continue
        if in_scan:
            if not line.startswith(" "):
                in_scan = False
                continue
            if "include:" in stripped and "[" in stripped:
                # Simple list parsing: include: ['src/*']
                import re
                items = re.findall(r"[\"']([^\"']+)[\"']", stripped)
                if items:
                    include = items
            elif "exclude:" in stripped and "[" in stripped:
                import re
                items = re.findall(r"[\"']([^\"']+)[\"']", stripped)
                if items:
                    exclude = items
    return include, exclude
