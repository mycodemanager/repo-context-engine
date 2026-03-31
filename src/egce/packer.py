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
    ("system", 0.10, Priority.CRITICAL),
    ("task", 0.10, Priority.HIGH),
    ("pinned_facts", 0.10, Priority.HIGH),
    ("repo_map", 0.10, Priority.NORMAL),
    ("evidence", 0.40, Priority.NORMAL),
    ("memory", 0.10, Priority.LOW),
    ("verifier_feedback", 0.05, Priority.HIGH),
    ("output_contract", 0.05, Priority.CRITICAL),
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
