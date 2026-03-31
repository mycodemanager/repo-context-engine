#!/usr/bin/env python3
"""End-to-end demo: scan a repo → pack context → verify.

Usage:
    python examples/demo.py /path/to/some/python/repo

This script shows the three core EGCE capabilities working together:
1. RepoMap scans the repo and produces a symbol map
2. ContextPacker assembles a prompt with slotted budget
3. Verifier runs tests/lint and produces feedback
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from egce import ContextPacker, RepoMap, Verifier
from egce.packer import Priority, count_tokens


def main() -> None:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."
    repo_path = str(Path(repo_path).resolve())

    print(f"=== EGCE Demo ===\n")
    print(f"Repository: {repo_path}\n")

    # ── Step 1: Scan ─────────────────────────────────────────────
    print("─── Step 1: Scanning repository ───")
    repo = RepoMap(repo_path)
    result = repo.scan()

    total_files = len(result.files)
    total_symbols = sum(
        len(f.symbols) + sum(len(s.children) for s in f.symbols)
        for f in result.files
    )
    total_imports = sum(len(f.imports) for f in result.files)
    total_lines = sum(f.lines for f in result.files)

    print(f"  Files:   {total_files}")
    print(f"  Symbols: {total_symbols}")
    print(f"  Imports: {total_imports}")
    print(f"  Lines:   {total_lines}")

    repo_map_text = result.to_text()
    map_tokens = count_tokens(repo_map_text)
    print(f"  Repo map: {map_tokens} tokens")
    print()

    # Show first 30 lines of the repo map
    preview = "\n".join(repo_map_text.splitlines()[:30])
    print(preview)
    if repo_map_text.count("\n") > 30:
        print(f"  ... ({repo_map_text.count(chr(10)) - 30} more lines)")
    print()

    # ── Step 2: Pack ─────────────────────────────────────────────
    print("─── Step 2: Packing context ───")

    packer = ContextPacker(token_budget=4000)
    packer.set_slot("system", "You are a code assistant working on this repository.")
    packer.set_slot(
        "task",
        "Find and fix the bug described in the issue. "
        "Write a minimal patch and explain your reasoning.",
    )
    packer.set_slot("repo_map", repo_map_text)
    packer.set_slot(
        "output_contract",
        "Respond with:\n1. Root cause analysis (2-3 sentences)\n"
        "2. A unified diff patch\n3. Which tests to run to verify",
    )

    stats = packer.stats()
    print(f"  Token budget: {stats['budget']}")
    print(f"  Total before trim: {stats['total_before_trim']}")
    print(f"  Over budget: {stats['over_budget']}")
    print(f"  Slots:")
    for name, info in stats["slots"].items():
        print(f"    {name:20s}  {info['tokens']:>5} tokens  ({info['priority']})")
    print()

    packed = packer.build()
    print(f"  Final packed prompt: {count_tokens(packed)} tokens")
    print()

    # ── Step 3: Verify ───────────────────────────────────────────
    print("─── Step 3: Running verification ───")

    verifier = Verifier(repo_path, timeout=60)
    vresult = verifier.run()

    if not vresult.checks:
        print("  No checks detected for this repository.")
        print("  (Tip: needs pyproject.toml, package.json, go.mod, or Cargo.toml)")
    else:
        for c in vresult.checks:
            status = "PASS ✓" if c.passed else "FAIL ✗"
            print(f"  [{status}] {c.command}  ({c.duration_s}s)")
            if not c.passed and c.summary:
                print(f"           {c.summary}")
        print()

        # Feed verification results back into the packer
        feedback = vresult.to_feedback()
        packer.set_slot("verifier_feedback", feedback, priority=Priority.HIGH)
        repacked = packer.build()
        print(f"  Repacked with feedback: {count_tokens(repacked)} tokens")

    # ── Summary ──────────────────────────────────────────────────
    print()
    print("─── Summary ───")
    print(f"  Repo: {total_files} files, {total_lines} lines of code")
    print(f"  Compressed to: {map_tokens} token repo map")
    print(f"  Packed into: {count_tokens(packed)} token prompt (budget: {packer.token_budget})")
    if vresult.checks:
        passed = sum(1 for c in vresult.checks if c.passed)
        print(f"  Verification: {passed}/{len(vresult.checks)} checks passed")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
