#!/usr/bin/env python3
"""Improved demo: retrieve → compress → focused map → pack.

Demonstrates the full EGCE pipeline on a real repo:
1. Index the repo (BM25 + symbol map)
2. Search for evidence relevant to a task
3. Compress retrieved chunks
4. Build a focused repo map (detailed for relevant files, compact for others)
5. Pack everything into a prompt within token budget
6. Compare against the naive approach

Usage:
    python examples/demo_improved.py /path/to/fastapi
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from egce import ContextPacker, Retriever, compress_chunks
from egce.packer import Priority, count_tokens


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}\n")


TASK_QUERY = (
    "POST requests with body containing nested Pydantic models "
    "sometimes lose field validators when the model is reused across "
    "multiple routes. Investigate dependency injection and model "
    "handling in the routing layer."
)


def main() -> None:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fastapi"
    repo_path = str(Path(repo_path).resolve())

    print("=" * 60)
    print("  EGCE Improved Pipeline Demo")
    print("=" * 60)
    print(f"\n  Repo: {repo_path}")
    print(f"  Task: {TASK_QUERY[:80]}...")

    # ── Step 1: Index ────────────────────────────────────────────
    section("Step 1: Index repository")
    t0 = time.monotonic()
    retriever = Retriever(repo_path)
    retriever.index(
        exclude=["docs/*", "docs_src/*", "scripts/*"],
    )
    t_index = time.monotonic() - t0

    n_docs = len(retriever._bm25.docs)
    n_symbols = len(retriever._symbol_map)
    print(f"  Indexed {n_docs} chunks, {n_symbols} unique symbols in {t_index:.1f}s")

    # ── Step 2: Search ───────────────────────────────────────────
    section("Step 2: BM25 + symbol search")
    t0 = time.monotonic()
    chunks = retriever.search(TASK_QUERY, top_k=10)
    t_search = time.monotonic() - t0

    print(f"  Found {len(chunks)} relevant chunks in {t_search:.3f}s")
    print()

    total_evidence_tokens = 0
    for i, c in enumerate(chunks):
        tokens = count_tokens(c.content)
        total_evidence_tokens += tokens
        sym_str = f"  [{', '.join(c.symbols[:3])}]" if c.symbols else ""
        print(f"  {i + 1:2d}. {c.source_uri}  L{c.start_line}-{c.end_line}"
              f"  score={c.score:.3f}  {tokens} tok{sym_str}")

    print(f"\n  Total evidence (raw): {total_evidence_tokens} tokens")

    # ── Step 3: Compress ─────────────────────────────────────────
    section("Step 3: Query-aware compression")
    compressed = compress_chunks(chunks, TASK_QUERY, target_ratio=0.5)

    compressed_tokens = sum(count_tokens(c.content) for c in compressed)
    ratio = compressed_tokens / total_evidence_tokens if total_evidence_tokens else 0
    print(f"  Before compression: {total_evidence_tokens} tokens")
    print(f"  After compression:  {compressed_tokens} tokens")
    print(f"  Compression ratio:  {ratio:.1%}")

    # Show a sample compressed chunk
    print(f"\n  Sample compressed chunk ({compressed[0].source_uri}):")
    preview = "\n".join(compressed[0].content.splitlines()[:15])
    for line in preview.splitlines():
        print(f"    {line}")
    if len(compressed[0].content.splitlines()) > 15:
        print(f"    ... ({len(compressed[0].content.splitlines()) - 15} more lines)")

    # ── Step 4: Focused repo map ─────────────────────────────────
    section("Step 4: Build focused repo map")

    repo_result = retriever.repo_map_result
    full_map_tokens = count_tokens(repo_result.to_text()) if repo_result else 0

    # Focus on files that appeared in search results
    focus_files = {c.source_uri for c in chunks}
    print(f"  Focus files ({len(focus_files)}):")
    for f in sorted(focus_files):
        print(f"    {f}")

    focused_map = repo_result.focused_text(focus_files) if repo_result else ""
    focused_tokens = count_tokens(focused_map)

    print(f"\n  Full repo map:    {full_map_tokens:,} tokens")
    print(f"  Focused repo map: {focused_tokens:,} tokens")
    print(f"  Reduction:        {focused_tokens / full_map_tokens:.1%}" if full_map_tokens else "")

    # ── Step 5: Pack ─────────────────────────────────────────────
    section("Step 5: Pack into prompt (budget: 8000 tokens)")

    packer = ContextPacker(token_budget=8000)

    packer.set_slot(
        "system",
        "You are a senior Python developer working on FastAPI.\n"
        "Follow existing code style. Include type hints. Minimal changes.",
        priority=Priority.CRITICAL,
    )
    packer.set_slot("task", TASK_QUERY, priority=Priority.HIGH)
    packer.set_slot(
        "pinned_facts",
        "- FastAPI uses Pydantic v2 (pydantic-core in Rust)\n"
        "- Dependency injection via Depends()\n"
        "- Route handlers in fastapi/routing.py\n"
        "- Model serialization in fastapi/_compat.py",
        priority=Priority.HIGH,
    )
    packer.set_slot("repo_map", focused_map, priority=Priority.NORMAL)

    # Join compressed evidence
    evidence_text = "\n\n".join(c.to_text() for c in compressed)
    packer.set_slot("evidence", evidence_text, priority=Priority.NORMAL)

    packer.set_slot(
        "output_contract",
        "Respond with:\n1. Root cause analysis (2-3 sentences)\n"
        "2. A unified diff patch\n3. Which tests to run",
        priority=Priority.CRITICAL,
    )

    prompt = packer.build()
    stats = packer.stats()

    print(f"  Token budget:      {stats['budget']}")
    print(f"  Total before trim: {stats['total_before_trim']:,}")
    print()
    for name, info in stats["slots"].items():
        bar = "█" * min(40, max(1, info["tokens"] // 100))
        print(f"    {name:20s}  {info['tokens']:>6,} tok  {info['priority']:>8s}  {bar}")
    print()
    print(f"  Final prompt: {count_tokens(prompt):,} tokens")

    # ── Comparison ───────────────────────────────────────────────
    section("Comparison: naive vs improved")

    # Naive: stuff full repo map into evidence
    naive_packer = ContextPacker(token_budget=8000)
    naive_packer.set_slot("system", "You are a senior Python developer.", priority=Priority.CRITICAL)
    naive_packer.set_slot("task", TASK_QUERY, priority=Priority.HIGH)
    naive_packer.set_slot("repo_map", repo_result.to_text() if repo_result else "", priority=Priority.NORMAL)
    naive_packer.set_slot("output_contract", "Respond with a fix.", priority=Priority.CRITICAL)
    naive_prompt = naive_packer.build()

    naive_stats = naive_packer.stats()

    print(f"  {'':20s}  {'Naive':>10s}  {'Improved':>10s}")
    print(f"  {'─' * 50}")
    print(f"  {'Input tokens':20s}  {naive_stats['total_before_trim']:>10,}  {stats['total_before_trim']:>10,}")
    print(f"  {'Final prompt':20s}  {count_tokens(naive_prompt):>10,}  {count_tokens(prompt):>10,}")
    print(f"  {'Evidence chunks':20s}  {'0':>10s}  {len(compressed):>10d}")
    print(f"  {'Focus files':20s}  {'0':>10s}  {len(focus_files):>10d}")
    print(f"  {'Has search results':20s}  {'No':>10s}  {'Yes':>10s}")
    print(f"  {'Has compression':20s}  {'No':>10s}  {'Yes':>10s}")

    print(f"\n  Key difference: improved pipeline puts {len(compressed)} relevant code")
    print(f"  chunks with provenance into the prompt, while naive approach")
    print(f"  just truncates the full repo map to fit the budget.")
    print(f"\n  Done.")


if __name__ == "__main__":
    main()
