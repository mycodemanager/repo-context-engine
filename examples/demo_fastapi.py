#!/usr/bin/env python3
"""Realistic demo: scan FastAPI → produce tiered repo maps → pack → verify.

Shows how EGCE handles a real medium-sized project (FastAPI: ~1100 files,
~100K lines) and demonstrates the compression ratio at different levels.

Usage:
    python examples/demo_fastapi.py /path/to/fastapi
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from egce import ContextPacker, RepoMap, Verifier
from egce.packer import Priority, count_tokens


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}\n")


def main() -> None:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fastapi"
    repo_path = str(Path(repo_path).resolve())

    print("=" * 60)
    print("  EGCE Real-World Demo — FastAPI")
    print("=" * 60)
    print(f"\n  Repository: {repo_path}")

    # ── Step 1: Full scan ────────────────────────────────────────
    section("Step 1: Full repository scan")

    repo = RepoMap(repo_path)
    full_result = repo.scan()

    total_files = len(full_result.files)
    total_lines = sum(f.lines for f in full_result.files)
    total_symbols = sum(
        len(f.symbols) + sum(len(s.children) for s in f.symbols)
        for f in full_result.files
    )
    total_imports = sum(len(f.imports) for f in full_result.files)

    full_text = full_result.to_text()
    full_tokens = count_tokens(full_text)

    print(f"  Total files:   {total_files}")
    print(f"  Total lines:   {total_lines:,}")
    print(f"  Total symbols: {total_symbols}")
    print(f"  Total imports: {total_imports}")
    print(f"  Full repo map: {full_tokens:,} tokens")

    # estimate raw token cost of all source files
    raw_tokens = total_lines * 4  # rough: ~4 tokens per line
    print(f"  Raw source (est.): ~{raw_tokens:,} tokens")
    print(f"  Repo map compression: {full_tokens / raw_tokens:.1%} of raw source")

    # ── Step 2: Tiered scanning ──────────────────────────────────
    section("Step 2: Tiered scanning — core library only")

    core_result = repo.scan(
        include=["fastapi/*"],
        exclude=["docs_src/*", "tests/*", "docs/*", "scripts/*"],
    )
    core_text = core_result.to_text()
    core_tokens = count_tokens(core_text)
    core_files = len(core_result.files)
    core_symbols = sum(
        len(f.symbols) + sum(len(s.children) for s in f.symbols)
        for f in core_result.files
    )

    print(f"  Core files:    {core_files}")
    print(f"  Core symbols:  {core_symbols}")
    print(f"  Core repo map: {core_tokens:,} tokens")
    print(f"  vs full:       {core_tokens / full_tokens:.1%}")

    # show a preview
    preview_lines = core_text.splitlines()[:60]
    print(f"\n  Preview (first 60 lines):")
    print("  " + "\n  ".join(preview_lines))
    if len(core_text.splitlines()) > 60:
        print(f"  ... ({len(core_text.splitlines()) - 60} more lines)")

    # ── Step 3: Depth=1 scan (file-level only, no methods) ───────
    section("Step 3: Shallow scan — file-level symbols only (depth=1)")

    shallow_text = core_result.to_text(max_depth=1)
    shallow_tokens = count_tokens(shallow_text)

    print(f"  Shallow repo map: {shallow_tokens:,} tokens")
    print(f"  vs core depth=2:  {shallow_tokens / core_tokens:.1%}")
    print(f"  vs full:          {shallow_tokens / full_tokens:.1%}")

    # ── Step 4: Pack into realistic prompt ───────────────────────
    section("Step 4: Pack into a realistic prompt (budget: 8000 tokens)")

    packer = ContextPacker(token_budget=8000)

    packer.set_slot(
        "system",
        "You are a senior Python developer working on the FastAPI project.\n"
        "Follow the existing code style. Always include type hints.\n"
        "Prefer minimal, targeted changes.",
    )

    packer.set_slot(
        "task",
        "Issue: POST requests with body containing nested Pydantic models\n"
        "sometimes lose field validators when the model is reused across\n"
        "multiple routes. Investigate the dependency injection and model\n"
        "handling in the routing layer. Propose a fix.",
    )

    packer.set_slot(
        "pinned_facts",
        "- FastAPI uses Pydantic v2 (pydantic-core in Rust)\n"
        "- Dependency injection is handled via Depends()\n"
        "- Route handlers are in fastapi/routing.py\n"
        "- Model serialization goes through fastapi/_compat.py",
    )

    packer.set_slot("repo_map", core_text)

    packer.set_slot(
        "evidence",
        "# fastapi/routing.py (relevant excerpt)\n"
        "# ... dependency resolution happens in solve_dependencies()\n"
        "# which calls request.body() and feeds it to the model validator\n"
        "# The issue may be in how model_fields are cached across routes\n",
    )

    packer.set_slot(
        "output_contract",
        "Respond with:\n"
        "1. Root cause analysis (2-3 sentences)\n"
        "2. A unified diff patch\n"
        "3. Which tests to run to verify the fix",
    )

    prompt = packer.build()
    stats = packer.stats()

    print(f"  Token budget:      {stats['budget']}")
    print(f"  Total before trim: {stats['total_before_trim']:,}")
    print(f"  Over budget:       {stats['over_budget']:,}")
    print()
    print(f"  Slot breakdown:")
    for name, info in stats["slots"].items():
        bar = "█" * min(50, info["tokens"] // 50)
        print(f"    {name:20s}  {info['tokens']:>6,} tok  {info['priority']:>8s}  {bar}")
    print()
    print(f"  Final prompt: {count_tokens(prompt):,} tokens")

    # ── Step 5: Verify ───────────────────────────────────────────
    section("Step 5: Run verification")

    v = Verifier(repo_path, timeout=10)
    # only run ruff (skip pytest — FastAPI needs many deps)
    from egce.verify import CheckKind

    result = v.run(kinds={CheckKind.LINT})

    for c in result.checks:
        status = "PASS ✓" if c.passed else "FAIL ✗"
        print(f"  [{status}] {c.command}  ({c.duration_s}s)")
        if not c.passed and c.summary:
            print(f"         {c.summary}")

    if result.checks:
        feedback = result.to_feedback()
        packer.set_slot("verifier_feedback", feedback, priority=Priority.HIGH)
        repacked = packer.build()
        print(f"\n  Repacked with feedback: {count_tokens(repacked):,} tokens")

    # ── Summary ──────────────────────────────────────────────────
    section("Summary — Compression results")

    print(f"  Raw source:         ~{raw_tokens:,} tokens (estimated)")
    print(f"  Full repo map:       {full_tokens:,} tokens  ({full_tokens / raw_tokens:.1%} of raw)")
    print(f"  Core repo map:       {core_tokens:,} tokens  ({core_tokens / raw_tokens:.1%} of raw)")
    print(f"  Shallow core map:    {shallow_tokens:,} tokens  ({shallow_tokens / raw_tokens:.1%} of raw)")
    print(f"  Final packed prompt: {count_tokens(prompt):,} tokens  ({count_tokens(prompt) / raw_tokens:.2%} of raw)")
    print()
    print(f"  Compression pipeline:")
    print(f"    ~{raw_tokens:,} tokens (raw source)")
    print(f"    → {core_tokens:,} tokens (core repo map, {core_tokens / raw_tokens:.1%})")
    print(f"    → {count_tokens(prompt):,} tokens (packed prompt, {count_tokens(prompt) / raw_tokens:.2%})")
    print(f"    = {raw_tokens / count_tokens(prompt):.0f}x compression")
    print()
    print("  Done.")


if __name__ == "__main__":
    main()
