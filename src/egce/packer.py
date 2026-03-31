"""ContextPacker — assemble LLM prompts using slotted token budgets.

Instead of concatenating everything in order, the packer allocates a
fixed token budget across named slots.  Each slot has a priority: when
the total exceeds the budget, lower-priority slots are truncated first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

import tiktoken

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

_ENC: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _ENC
    if _ENC is None:
        _ENC = tiktoken.get_encoding("cl100k_base")
    return _ENC


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text))


# ---------------------------------------------------------------------------
# Slot
# ---------------------------------------------------------------------------


class Priority(IntEnum):
    """Higher value = higher priority (kept when budget is tight)."""

    LOW = 10
    NORMAL = 50
    HIGH = 80
    CRITICAL = 100


@dataclass
class Slot:
    """A named region inside the final prompt.

    Parameters
    ----------
    name : slot identifier (e.g. "system", "evidence", "repo_map")
    content : raw text content
    priority : how important this slot is when trimming
    budget_pct : suggested share of the total budget (0.0–1.0)
    """

    name: str
    content: str = ""
    priority: Priority = Priority.NORMAL
    budget_pct: float = 0.0
    _tokens: int | None = field(default=None, repr=False)

    @property
    def tokens(self) -> int:
        if self._tokens is None:
            self._tokens = count_tokens(self.content)
        return self._tokens

    def set_content(self, text: str) -> None:
        self.content = text
        self._tokens = None  # invalidate cache


# ---------------------------------------------------------------------------
# Default slot presets
# ---------------------------------------------------------------------------

DEFAULT_SLOTS: list[tuple[str, float, Priority]] = [
    ("system", 0.08, Priority.CRITICAL),
    ("task", 0.08, Priority.HIGH),
    ("pinned_facts", 0.08, Priority.HIGH),
    ("project_context", 0.12, Priority.HIGH),
    ("spec", 0.08, Priority.HIGH),
    ("repo_map", 0.10, Priority.NORMAL),
    ("evidence", 0.35, Priority.NORMAL),
    ("memory", 0.05, Priority.LOW),
    ("verifier_feedback", 0.03, Priority.HIGH),
    ("output_contract", 0.03, Priority.CRITICAL),
]


# ---------------------------------------------------------------------------
# Packer
# ---------------------------------------------------------------------------


class ContextPacker:
    """Build a prompt from named slots within a token budget.

    Usage::

        packer = ContextPacker(token_budget=8000)
        packer.set_slot("system", "You are a helpful assistant.")
        packer.set_slot("evidence", big_evidence_text)
        prompt = packer.build()
    """

    def __init__(
        self,
        token_budget: int = 8000,
        *,
        slots: list[tuple[str, float, Priority]] | None = None,
        truncator: Callable[[str, int], str] | None = None,
    ) -> None:
        self.token_budget = token_budget
        self._truncator = truncator or _default_truncate
        self._slots: dict[str, Slot] = {}

        for name, pct, pri in (slots or DEFAULT_SLOTS):
            self._slots[name] = Slot(name=name, priority=pri, budget_pct=pct)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_slot(self, name: str, content: str, *, priority: Priority | None = None) -> None:
        """Set (or create) a slot's content."""
        if name in self._slots:
            self._slots[name].set_content(content)
            if priority is not None:
                self._slots[name].priority = priority
        else:
            self._slots[name] = Slot(
                name=name,
                content=content,
                priority=priority or Priority.NORMAL,
                budget_pct=0.0,
            )

    def get_slot(self, name: str) -> Slot | None:
        return self._slots.get(name)

    @property
    def slots(self) -> list[Slot]:
        return list(self._slots.values())

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> str:
        """Assemble the final prompt, trimming lower-priority slots if needed."""
        active = [s for s in self._slots.values() if s.content]
        if not active:
            return ""

        total_tokens = sum(s.tokens for s in active)

        # If everything fits, no trimming needed
        if total_tokens <= self.token_budget:
            return self._render(active)

        # Otherwise: trim slots from lowest priority upward
        active.sort(key=lambda s: s.priority)
        remaining_budget = self.token_budget

        # First pass: allocate guaranteed budget for critical slots
        guaranteed: dict[str, int] = {}
        for s in active:
            slot_budget = int(self.token_budget * s.budget_pct) if s.budget_pct > 0 else 0
            guaranteed[s.name] = max(slot_budget, 0)

        # Second pass: trim or keep
        final_slots: list[Slot] = []
        # Process from highest to lowest priority
        for s in sorted(active, key=lambda s: s.priority, reverse=True):
            if s.tokens <= remaining_budget:
                final_slots.append(s)
                remaining_budget -= s.tokens
            else:
                # Truncate to fit
                if remaining_budget > 50:  # keep at least ~50 tokens
                    truncated = self._truncator(s.content, remaining_budget)
                    truncated_slot = Slot(
                        name=s.name,
                        content=truncated,
                        priority=s.priority,
                        budget_pct=s.budget_pct,
                    )
                    final_slots.append(truncated_slot)
                    remaining_budget -= truncated_slot.tokens
                # else: drop entirely

        return self._render(final_slots)

    def stats(self) -> dict:
        """Return token usage statistics per slot."""
        active = [s for s in self._slots.values() if s.content]
        total = sum(s.tokens for s in active)
        return {
            "budget": self.token_budget,
            "total_before_trim": total,
            "over_budget": max(0, total - self.token_budget),
            "slots": {s.name: {"tokens": s.tokens, "priority": s.priority.name, "pct": s.budget_pct} for s in active},
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _render(self, slots: list[Slot]) -> str:
        """Render slots in a fixed canonical order."""
        order = [name for name, _, _ in DEFAULT_SLOTS]
        # put known slots first in canonical order, then extras
        ordered: list[Slot] = []
        seen = set()
        for name in order:
            for s in slots:
                if s.name == name:
                    ordered.append(s)
                    seen.add(s.name)
        for s in slots:
            if s.name not in seen:
                ordered.append(s)

        parts: list[str] = []
        for s in ordered:
            parts.append(f"<{s.name}>\n{s.content}\n</{s.name}>")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Default truncation
# ---------------------------------------------------------------------------


def _default_truncate(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens by cutting from the end."""
    enc = _encoder()
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    # Keep the first max_tokens-10 tokens and append a marker
    truncated = enc.decode(tokens[: max_tokens - 5])
    return truncated + "\n... [truncated]"


# ---------------------------------------------------------------------------
# Auto-load .egce/ context and specs
# ---------------------------------------------------------------------------


def load_project_context(packer: ContextPacker, root: str) -> None:
    """Load .egce/context/ files and active spec into a packer.

    Scans one or more project roots for .egce/ directories and injects
    their content into the ``project_context`` and ``spec`` slots.

    Parameters
    ----------
    packer : the ContextPacker to populate
    root : project root or workspace root path
    """
    from pathlib import Path

    root = Path(root).resolve()
    context_parts: list[str] = []
    spec_parts: list[str] = []

    # Collect all .egce dirs (workspace may have multiple)
    egce_dirs: list[tuple[str, Path]] = []

    # Check workspace level
    ws_egce = root / ".egce"
    if ws_egce.exists():
        # Check for workspace.yaml → multi-project
        ws_yaml = ws_egce / "workspace.yaml"
        if ws_yaml.exists():
            # Scan sub-projects
            for entry in sorted(root.iterdir()):
                sub_egce = entry / ".egce"
                if entry.is_dir() and sub_egce.exists():
                    egce_dirs.append((entry.name, sub_egce))
            # Also load workspace-level specs
            ws_specs = ws_egce / "specs"
            if ws_specs.exists():
                spec_parts.extend(_load_active_specs(ws_specs))
        else:
            # Single project
            egce_dirs.append((root.name, ws_egce))

    # Load context from each project
    for project_name, egce_dir in egce_dirs:
        context_dir = egce_dir / "context"
        if context_dir.exists():
            parts = _load_context_dir(context_dir, project_name, len(egce_dirs) > 1)
            context_parts.extend(parts)

        # Project-level specs
        specs_dir = egce_dir / "specs"
        if specs_dir.exists():
            spec_parts.extend(_load_active_specs(specs_dir))

    # Set slots
    if context_parts:
        packer.set_slot("project_context", "\n\n".join(context_parts), priority=Priority.HIGH)

    if spec_parts:
        packer.set_slot("spec", "\n\n".join(spec_parts), priority=Priority.HIGH)


def _load_context_dir(context_dir, project_name: str, multi_project: bool) -> list[str]:
    """Read all .md files from a context directory."""
    parts: list[str] = []
    # Try config-defined priority order first
    config_path = context_dir.parent / "config.yaml"
    ordered_files: list[str] = []
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("- context/") and line.endswith(".md"):
                fname = line.split("context/")[-1]
                ordered_files.append(fname)

    # Fall back to sorted directory listing
    if not ordered_files:
        ordered_files = sorted(f.name for f in context_dir.iterdir() if f.suffix == ".md")

    for fname in ordered_files:
        fpath = context_dir / fname
        if fpath.exists():
            content = fpath.read_text().strip()
            # Skip template files that haven't been filled in
            if content and "<!-- " not in content.split("\n")[-1]:
                prefix = f"[{project_name}] " if multi_project else ""
                parts.append(f"## {prefix}{fname}\n\n{content}")

    return parts


def _load_active_specs(specs_dir) -> list[str]:
    """Load specs with status in_progress or approved."""
    parts: list[str] = []
    for f in sorted(specs_dir.iterdir()):
        if f.suffix not in (".yaml", ".yml"):
            continue
        content = f.read_text()
        # Quick check for active status
        for line in content.splitlines()[:15]:
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip()
                if status in ("approved", "in_progress"):
                    parts.append(f"## Spec: {f.stem}\n\n```yaml\n{content}\n```")
                break
    return parts
