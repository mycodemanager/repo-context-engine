"""CLI entry point for EGCE.

Provides subcommands:
    egce scan      — scan a repo and print the symbol map
    egce search    — search for relevant code chunks
    egce pipeline  — full pipeline: search → compress → pack
    egce pack      — assemble context from slot files
    egce verify    — run verification checks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_scan(args: argparse.Namespace) -> None:
    from egce.repo_map import RepoMap

    repo = RepoMap(args.repo, max_file_bytes=args.max_file_bytes)
    result = repo.scan(
        include=args.include.split(",") if args.include else None,
        exclude=args.exclude.split(",") if args.exclude else None,
    )

    if args.json:
        json.dump(result.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        print(result.to_text(max_depth=args.depth))

    # stats
    total_files = len(result.files)
    total_symbols = sum(len(f.symbols) + sum(len(s.children) for s in f.symbols) for f in result.files)
    total_imports = sum(len(f.imports) for f in result.files)
    print(f"\n--- {total_files} files, {total_symbols} symbols, {total_imports} imports ---", file=sys.stderr)


def cmd_pack(args: argparse.Namespace) -> None:
    from egce.packer import ContextPacker

    packer = ContextPacker(token_budget=args.budget)

    # Read slot contents from files or stdin
    for slot_spec in args.slot:
        parts = slot_spec.split("=", 1)
        if len(parts) != 2:
            print(f"Invalid slot spec: {slot_spec!r}  (expected name=filepath)", file=sys.stderr)
            sys.exit(1)
        name, filepath = parts
        path = Path(filepath)
        if filepath == "-":
            content = sys.stdin.read()
        elif path.exists():
            content = path.read_text()
        else:
            print(f"File not found: {filepath}", file=sys.stderr)
            sys.exit(1)
        packer.set_slot(name, content)

    if args.stats:
        json.dump(packer.stats(), sys.stdout, indent=2)
        print()
    else:
        print(packer.build())


def cmd_verify(args: argparse.Namespace) -> None:
    from egce.verify import CheckKind, Verifier

    kinds = None
    if args.only:
        kinds = {CheckKind(k) for k in args.only.split(",")}

    custom_checks = None
    if args.cmd:
        kind = CheckKind(args.kind) if args.kind else CheckKind.CUSTOM
        custom_checks = [(kind, args.cmd)]

    v = Verifier(args.repo, timeout=args.timeout, checks=custom_checks)
    result = v.run(kinds=kinds)

    if args.json:
        import dataclasses

        data = {
            "passed": result.passed,
            "checks": [dataclasses.asdict(c) for c in result.checks],
        }
        json.dump(data, sys.stdout, indent=2, default=str)
        print()
    else:
        for c in result.checks:
            status = "PASS" if c.passed else "FAIL"
            print(f"[{status}] {c.command}  ({c.duration_s}s)")
            if not c.passed and c.summary:
                print(f"       {c.summary}")
        print()
        if result.passed:
            print("All checks passed.")
        else:
            print(f"{len(result.failed_checks)} check(s) failed.")
            sys.exit(1)


def cmd_search(args: argparse.Namespace) -> None:
    from egce.packer import count_tokens
    from egce.retrieve import Retriever

    exclude = args.exclude.split(",") if args.exclude else None

    retriever = Retriever(args.repo)
    retriever.index(exclude=exclude)
    chunks = retriever.search(args.query, top_k=args.top_k)

    if not chunks:
        print("No relevant code found.", file=sys.stderr)
        sys.exit(0)

    if args.json:
        data = []
        for c in chunks:
            data.append({
                "source_uri": c.source_uri,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "score": c.score,
                "symbols": c.symbols,
                "content": c.content,
            })
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        for i, c in enumerate(chunks):
            sym_str = f"  [{', '.join(c.symbols[:5])}]" if c.symbols else ""
            print(f"{i + 1:2d}. {c.source_uri}  L{c.start_line}-{c.end_line}"
                  f"  score={c.score:.3f}  {count_tokens(c.content)} tok{sym_str}")
        print(f"\n--- {len(chunks)} chunks found ---", file=sys.stderr)


def cmd_pipeline(args: argparse.Namespace) -> None:
    from egce.compress import compress_chunks
    from egce.packer import ContextPacker, Priority, count_tokens
    from egce.retrieve import Retriever

    exclude = args.exclude.split(",") if args.exclude else None

    # 1. Index & search
    print("Indexing...", file=sys.stderr)
    retriever = Retriever(args.repo)
    retriever.index(exclude=exclude)

    print(f"Searching: \"{args.task}\"", file=sys.stderr)
    chunks = retriever.search(args.task, top_k=args.top_k)

    if not chunks:
        print("No relevant code found.", file=sys.stderr)
        sys.exit(0)

    # 2. Compress
    compressed = compress_chunks(chunks, args.task, target_ratio=0.5)
    raw_tok = sum(count_tokens(c.content) for c in chunks)
    comp_tok = sum(count_tokens(c.content) for c in compressed)
    print(f"Compressed: {raw_tok} → {comp_tok} tokens", file=sys.stderr)

    # 3. Focused repo map
    repo_result = retriever.repo_map_result
    focus_files = {c.source_uri for c in chunks}
    focused_map = repo_result.focused_text(focus_files) if repo_result else ""

    # 4. Pack
    packer = ContextPacker(token_budget=args.budget)
    packer.set_slot("task", args.task, priority=Priority.HIGH)
    packer.set_slot("repo_map", focused_map, priority=Priority.NORMAL)
    packer.set_slot(
        "evidence",
        "\n\n".join(c.to_text() for c in compressed),
        priority=Priority.NORMAL,
    )

    prompt = packer.build()

    if args.stats:
        stats = packer.stats()
        stats["search_results"] = len(chunks)
        stats["focus_files"] = len(focus_files)
        stats["compression"] = f"{raw_tok} → {comp_tok}"
        json.dump(stats, sys.stdout, indent=2)
        print()
    else:
        print(prompt)
        print(f"\n--- {count_tokens(prompt)} tokens (budget: {args.budget}) ---", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="egce",
        description="Evidence-Grounded Context Engine for large code repositories",
    )
    sub = parser.add_subparsers(dest="command")

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan a repository and output its symbol map")
    p_scan.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    p_scan.add_argument("--json", action="store_true", help="Output as JSON")
    p_scan.add_argument("--depth", type=int, default=2, help="Symbol nesting depth (default: 2)")
    p_scan.add_argument("--include", help="Comma-separated include patterns")
    p_scan.add_argument("--exclude", help="Comma-separated exclude patterns")
    p_scan.add_argument("--max-file-bytes", type=int, default=512_000, help="Skip parsing files larger than this")

    # --- pack ---
    p_pack = sub.add_parser("pack", help="Assemble context from slot files")
    p_pack.add_argument("--budget", type=int, default=8000, help="Token budget (default: 8000)")
    p_pack.add_argument("--slot", action="append", default=[], help="Slot spec: name=filepath (repeatable)")
    p_pack.add_argument("--stats", action="store_true", help="Print token stats instead of the packed prompt")

    # --- verify ---
    p_verify = sub.add_parser("verify", help="Run tests/lint against a repository")
    p_verify.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    p_verify.add_argument("--json", action="store_true", help="Output as JSON")
    p_verify.add_argument("--timeout", type=int, default=120, help="Timeout per check in seconds")
    p_verify.add_argument("--only", help="Comma-separated check kinds: test,lint,typecheck,build")
    p_verify.add_argument("--cmd", nargs=argparse.REMAINDER, help="Custom command to run")
    p_verify.add_argument("--kind", help="Kind for custom command (default: custom)")

    # --- search ---
    p_search = sub.add_parser("search", help="Search for relevant code chunks")
    p_search.add_argument("query", help="Natural language query")
    p_search.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    p_search.add_argument("--top-k", type=int, default=10, help="Number of results (default: 10)")
    p_search.add_argument("--exclude", help="Comma-separated exclude patterns")
    p_search.add_argument("--json", action="store_true", help="Output as JSON")

    # --- pipeline ---
    p_pipe = sub.add_parser("pipeline", help="Full pipeline: search → compress → pack")
    p_pipe.add_argument("task", help="Task description or question")
    p_pipe.add_argument("repo", nargs="?", default=".", help="Path to repository root")
    p_pipe.add_argument("--budget", type=int, default=8000, help="Token budget (default: 8000)")
    p_pipe.add_argument("--top-k", type=int, default=10, help="Number of chunks to retrieve")
    p_pipe.add_argument("--exclude", help="Comma-separated exclude patterns")
    p_pipe.add_argument("--stats", action="store_true", help="Print stats instead of prompt")

    args = parser.parse_args(argv)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    elif args.command == "pack":
        cmd_pack(args)
    elif args.command == "verify":
        cmd_verify(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
