"""Spec management — list, show, update requirement specifications."""

from __future__ import annotations

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
