"""CLI entry point for EGCE.

Provides subcommands:
    egce init      — initialize .egce/ directory for a project
    egce sync      — re-scan and update analysis
    egce scan      — scan a repo and print the symbol map
    egce search    — search for relevant code chunks
    egce pipeline  — full pipeline: search → compress → pack
    egce pack      — assemble context from slot files
    egce verify    — run verification checks
    egce spec      — manage requirement specs
    egce context   — view project context files
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("egce")


def cmd_setup(args: argparse.Namespace) -> None:
    """Install EGCE global instructions for AI tools."""
    home = Path.home()

    # --- Claude Code global CLAUDE.md ---
    claude_dir = home / ".claude"
    claude_dir.mkdir(exist_ok=True)
    claude_md = claude_dir / "CLAUDE.md"

    # Load the global instruction template
    template_path = Path(__file__).parent.parent.parent / "templates" / "global-claude-md.md"
    if not template_path.exists():
        # Fallback: use pkg_resources or embedded content
        template_path = None

    egce_block_start = "<!-- EGCE-START -->"
    egce_block_end = "<!-- EGCE-END -->"

    if template_path and template_path.exists():
        egce_content = template_path.read_text()
    else:
        egce_content = _EMBEDDED_GLOBAL_INSTRUCTIONS

    new_block = f"{egce_block_start}\n{egce_content}\n{egce_block_end}"

    if claude_md.exists():
        existing = claude_md.read_text()
        if egce_block_start in existing:
            # Update existing block
            import re
            pattern = re.escape(egce_block_start) + r".*?" + re.escape(egce_block_end)
            updated = re.sub(pattern, new_block, existing, flags=re.DOTALL)
            claude_md.write_text(updated)
            print(f"Updated EGCE instructions in {claude_md}", file=sys.stderr)
        else:
            # Append
            claude_md.write_text(existing.rstrip() + "\n\n" + new_block + "\n")
            print(f"Added EGCE instructions to {claude_md}", file=sys.stderr)
    else:
        claude_md.write_text(new_block + "\n")
        print(f"Created {claude_md} with EGCE instructions", file=sys.stderr)

    # --- Claude Code MCP config ---
    settings_path = claude_dir / "settings.json"
    mcp_configured = False
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            if "mcpServers" in settings and "egce" in settings["mcpServers"]:
                mcp_configured = True
        except (json.JSONDecodeError, KeyError):
            pass

    if not mcp_configured:
        print(f"\nTo also enable EGCE as a native Claude Code tool, add to {settings_path}:", file=sys.stderr)
        print('  "mcpServers": { "egce": { "command": "python3", "args": ["-m", "egce.mcp_server"] } }',
              file=sys.stderr)

    print("\nSetup complete. Open Claude Code and start chatting.", file=sys.stderr)


_EMBEDDED_GLOBAL_INSTRUCTIONS = """\
# EGCE — Evidence-Grounded Context Engine

You have EGCE installed globally. Use it to manage code project context.

## When the user wants to start working on a project

When the user provides repository URLs or points to existing local repositories:

1. If repositories are not yet cloned, ask where to create the workspace and clone them
2. Determine the workspace root (the directory containing all project repos)
3. Run `egce init <workspace_path>` to scan all projects and generate analysis
4. Check stderr for WARNING lines — if a framework is detected but extraction is empty, investigate
5. Read the generated `.egce/analysis/` files in each project
6. Based on the analysis, generate `.egce/context/` files (architecture.md, modules.md, api-contracts.md, data-models.md, conventions.md)
7. Show the user the generated context and ask them to review

## When working on an existing project with .egce/ directory

1. Read `.egce/context/` to understand the project
2. Use `egce search "<query>" .` to find relevant code
3. Use `egce pipeline "<task>" .` to get compressed context for a specific task

## When the user describes a requirement

1. Read `.egce/context/` for existing architecture and conventions
2. Run `egce search` in each project to find related existing code
3. Output a structured spec (YAML) to workspace `.egce/specs/` with precise API definitions, frontend changes, affected files, testing requirements
4. Run `egce spec validate <id>` to check completeness (frontend-backend alignment, field definitions, test cases)
5. Fix any validation errors
6. Ask the user to review and approve

## When developing from a spec

1. Run `egce spec validate <id>` to confirm spec is complete
2. Run `egce spec test <id> --output-dir tests/` to generate test skeleton
3. Follow the spec exactly for interface definitions
4. Run `egce pipeline "<task>"` before each task for context
5. Follow `.egce/context/conventions.md` for code style
6. Run `egce verify .` after each task
7. If verify reports stale context, update the relevant `.egce/context/` files before proceeding
8. After all tasks: run `egce sync . --check` and update stale context files

## Commands

egce init, egce sync, egce scan, egce search, egce pipeline, egce verify,
egce spec list/show/status/validate/test, egce context list/show

All commands support --verbose / -v for debug logging.
"""


def cmd_init(args: argparse.Namespace) -> None:
    # Import extractors to trigger registration
    import egce.extractors.fastapi_ext  # noqa: F401
    import egce.extractors.django_ext  # noqa: F401
    import egce.extractors.express_ext  # noqa: F401
    import egce.extractors.react_ext  # noqa: F401
    import egce.extractors.vue_ext  # noqa: F401
    from egce.workspace import init_project, init_workspace

    root = Path(args.repo).resolve()

    # Check if this is a workspace (has multiple git repos)
    sub_repos = [d for d in root.iterdir() if d.is_dir() and (d / ".git").exists()]

    if len(sub_repos) > 1:
        print(f"Detected workspace with {len(sub_repos)} projects", file=sys.stderr)
        result = init_workspace(root)
        print(f"\nWorkspace: {result['workspace']}", file=sys.stderr)
        for p in result["projects"]:
            _print_init_stats(p)
    else:
        result = init_project(
            root,
            include=args.include.split(",") if args.include else None,
            exclude=args.exclude.split(",") if args.exclude else None,
        )
        _print_init_stats(result)

    print("\nDone. AI can now read .egce/analysis/ to generate context files.", file=sys.stderr)


def _print_init_stats(stats: dict) -> None:
    print(f"\n  Project: {stats['project']}", file=sys.stderr)
    print(f"  Type: {stats['project_type']} ({stats.get('framework') or stats['language']})", file=sys.stderr)
    print(f"  Files: {stats['files']}, Symbols: {stats['symbols']}", file=sys.stderr)
    if stats.get("routes"):
        print(f"  API Routes: {stats['routes']}", file=sys.stderr)
    if stats.get("models"):
        print(f"  Data Models: {stats['models']}", file=sys.stderr)
    if stats.get("pages"):
        print(f"  Pages: {stats['pages']}", file=sys.stderr)
    if stats.get("components"):
        print(f"  Components: {stats['components']}", file=sys.stderr)
    if stats.get("infra"):
        print(f"  Infrastructure: {stats['infra']}", file=sys.stderr)
    if stats.get("env_vars"):
        print(f"  Env Vars: {stats['env_vars']}", file=sys.stderr)
    for w in stats.get("warnings") or []:
        print(f"  WARNING: {w}", file=sys.stderr)


def cmd_sync(args: argparse.Namespace) -> None:
    import egce.extractors.fastapi_ext  # noqa: F401
    import egce.extractors.django_ext  # noqa: F401
    import egce.extractors.express_ext  # noqa: F401
    import egce.extractors.react_ext  # noqa: F401
    import egce.extractors.vue_ext  # noqa: F401
    from egce.workspace import sync_project

    root = Path(args.repo).resolve()
    result = sync_project(root, check_only=args.check, diff=args.diff)

    if result.get("warnings"):
        print("Warnings:", file=sys.stderr)
        for w in result["warnings"]:
            print(f"  ⚠ {w}", file=sys.stderr)

    if result.get("updated"):
        print(f"\nUpdated: {result.get('files', 0)} files, "
              f"{result.get('routes', 0)} routes, "
              f"{result.get('models', 0)} models", file=sys.stderr)
    elif args.check:
        if not result.get("warnings"):
            print("All context files are up to date.", file=sys.stderr)


def cmd_spec(args: argparse.Namespace) -> None:
    from egce.spec import (
        generate_test_skeleton,
        list_specs,
        show_spec,
        update_spec_status,
        validate_spec,
    )

    root = Path(args.repo).resolve()

    if args.spec_action == "list":
        specs = list_specs(root)
        if not specs:
            print("No specs found.", file=sys.stderr)
            return
        for s in specs:
            status = s.get("status", "?")
            print(f"  [{status:12s}] {s['id']}  {s.get('title', '')}")

    elif args.spec_action == "show":
        content = show_spec(root, args.spec_id)
        if content:
            print(content)
        else:
            print(f"Spec not found: {args.spec_id}", file=sys.stderr)
            sys.exit(1)

    elif args.spec_action == "status":
        ok = update_spec_status(root, args.spec_id, args.new_status)
        if ok:
            print(f"Updated {args.spec_id} → {args.new_status}", file=sys.stderr)
        else:
            print(f"Spec not found: {args.spec_id}", file=sys.stderr)
            sys.exit(1)

    elif args.spec_action == "validate":
        result = validate_spec(root, args.spec_id)
        print(result.to_text())
        if not result.passed:
            sys.exit(1)

    elif args.spec_action == "test":
        files = generate_test_skeleton(root, args.spec_id)
        if not files:
            print("No test cases found in spec.", file=sys.stderr)
            sys.exit(1)
        for fname, code in files.items():
            if args.output_dir:
                out = Path(args.output_dir)
                out.mkdir(parents=True, exist_ok=True)
                (out / fname).write_text(code)
                print(f"  Generated: {out / fname}", file=sys.stderr)
            else:
                print(f"# === {fname} ===")
                print(code)


def cmd_context(args: argparse.Namespace) -> None:
    root = Path(args.repo).resolve()
    context_dir = root / ".egce" / "context"

    if not context_dir.exists():
        print("No .egce/context/ directory. Run 'egce init' first.", file=sys.stderr)
        sys.exit(1)

    if args.context_action == "list":
        for f in sorted(context_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                size = f.stat().st_size
                print(f"  {f.name:30s}  {size:>6d} bytes")

    elif args.context_action == "show":
        target = context_dir / args.name
        if not target.exists():
            # Try with .md extension
            target = context_dir / f"{args.name}.md"
        if target.exists():
            print(target.read_text())
        else:
            print(f"Context file not found: {args.name}", file=sys.stderr)
            sys.exit(1)


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
    import time as _time

    from egce.compress import compress_chunks
    from egce.packer import ContextPacker, Priority, count_tokens, load_project_context
    from egce.retrieve import Retriever
    from egce.telemetry import Telemetry

    exclude = args.exclude.split(",") if args.exclude else None
    tel = Telemetry(args.repo)
    trace = tel.start_trace(args.task, args.repo)
    trace.token_budget = args.budget
    t_total = _time.monotonic()

    # 1. Index & search
    print("Indexing...", file=sys.stderr)
    t0 = _time.monotonic()
    retriever = Retriever(args.repo)
    retriever.index(exclude=exclude)
    trace.index_time_s = round(_time.monotonic() - t0, 2)

    print(f"Searching: \"{args.task}\"", file=sys.stderr)
    t0 = _time.monotonic()
    chunks = retriever.search(args.task, top_k=args.top_k)
    trace.search_time_s = round(_time.monotonic() - t0, 3)

    if not chunks:
        print("No relevant code found.", file=sys.stderr)
        sys.exit(0)

    trace.chunks_retrieved = len(chunks)
    raw_tok = sum(count_tokens(c.content) for c in chunks)
    trace.chunks_total_tokens = raw_tok

    # 2. Compress
    t0 = _time.monotonic()
    compressed = compress_chunks(chunks, args.task, target_ratio=0.5)
    trace.compress_time_s = round(_time.monotonic() - t0, 3)
    comp_tok = sum(count_tokens(c.content) for c in compressed)
    trace.chunks_after_compression = len(compressed)
    trace.compressed_tokens = comp_tok
    trace.compression_ratio = round(comp_tok / raw_tok, 3) if raw_tok else 0
    print(f"Compressed: {raw_tok} → {comp_tok} tokens", file=sys.stderr)

    # 3. Focused repo map
    repo_result = retriever.repo_map_result
    focus_files = {c.source_uri for c in chunks}
    focused_map = repo_result.focused_text(focus_files) if repo_result else ""
    trace.repo_map_tokens = count_tokens(focused_map)

    # 4. Pack (with auto-loaded project context and spec)
    t0 = _time.monotonic()
    packer = ContextPacker(token_budget=args.budget)
    load_project_context(packer, args.repo)
    ctx_slot = packer.get_slot("project_context")
    spec_slot = packer.get_slot("spec")
    if ctx_slot and ctx_slot.content:
        trace.project_context_tokens = ctx_slot.tokens
        print(f"Loaded project context: {ctx_slot.tokens} tokens", file=sys.stderr)
    if spec_slot and spec_slot.content:
        trace.spec_tokens = spec_slot.tokens
        print(f"Loaded active spec: {spec_slot.tokens} tokens", file=sys.stderr)

    packer.set_slot("task", args.task, priority=Priority.HIGH)
    packer.set_slot("repo_map", focused_map, priority=Priority.NORMAL)
    packer.set_slot(
        "evidence",
        "\n\n".join(c.to_text() for c in compressed),
        priority=Priority.NORMAL,
    )

    prompt = packer.build()
    trace.pack_time_s = round(_time.monotonic() - t0, 3)

    stats = packer.stats()
    trace.total_input_tokens = stats["total_before_trim"]
    trace.packed_tokens = count_tokens(prompt)
    trace.over_budget = stats["over_budget"]
    trace.total_time_s = round(_time.monotonic() - t_total, 2)

    # Save telemetry
    tel.save_trace(trace)

    if args.stats:
        stats["search_results"] = len(chunks)
        stats["focus_files"] = len(focus_files)
        stats["compression"] = f"{raw_tok} → {comp_tok}"
        stats["telemetry"] = {
            "index_time": trace.index_time_s,
            "search_time": trace.search_time_s,
            "compress_time": trace.compress_time_s,
            "pack_time": trace.pack_time_s,
            "total_time": trace.total_time_s,
        }
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
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command")

    # --- setup ---
    sub.add_parser("setup", help="Install EGCE global instructions for AI tools (Claude Code, Cursor, etc.)")

    # --- init ---
    p_init = sub.add_parser("init", help="Initialize .egce/ directory for a project or workspace")
    p_init.add_argument("repo", nargs="?", default=".", help="Path to project or workspace root")
    p_init.add_argument("--include", help="Comma-separated include patterns")
    p_init.add_argument("--exclude", help="Comma-separated exclude patterns")

    # --- sync ---
    p_sync = sub.add_parser("sync", help="Re-scan and update analysis files")
    p_sync.add_argument("repo", nargs="?", default=".", help="Path to project root")
    p_sync.add_argument("--check", action="store_true", help="Check context freshness without updating")
    p_sync.add_argument("--diff", action="store_true", help="Show what changed since last sync")

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

    # --- spec ---
    p_spec = sub.add_parser("spec", help="Manage requirement specs")
    p_spec.add_argument("repo", nargs="?", default=".", help="Path to project root")
    spec_sub = p_spec.add_subparsers(dest="spec_action")
    spec_sub.add_parser("list", help="List all specs")
    p_spec_show = spec_sub.add_parser("show", help="Show a spec")
    p_spec_show.add_argument("spec_id", help="Spec ID or filename")
    p_spec_status = spec_sub.add_parser("status", help="Update spec status")
    p_spec_status.add_argument("spec_id", help="Spec ID")
    p_spec_status.add_argument("new_status", help="New status (draft/approved/in_progress/done)")
    p_spec_validate = spec_sub.add_parser("validate", help="Check spec for self-containment issues")
    p_spec_validate.add_argument("spec_id", help="Spec ID to validate")
    p_spec_test = spec_sub.add_parser("test", help="Generate test skeleton from spec")
    p_spec_test.add_argument("spec_id", help="Spec ID")
    p_spec_test.add_argument("--output-dir", help="Directory to write test files (default: stdout)")

    # --- context ---
    p_ctx = sub.add_parser("context", help="View project context files")
    p_ctx.add_argument("repo", nargs="?", default=".", help="Path to project root")
    ctx_sub = p_ctx.add_subparsers(dest="context_action")
    ctx_sub.add_parser("list", help="List context files")
    p_ctx_show = ctx_sub.add_parser("show", help="Show a context file")
    p_ctx_show.add_argument("name", help="Context file name (e.g. architecture or architecture.md)")

    args = parser.parse_args(argv)

    # Configure logging
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        format="%(name)s: %(message)s",
        level=level,
        stream=sys.stderr,
    )

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    elif args.command == "pack":
        cmd_pack(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "spec":
        cmd_spec(args)
    elif args.command == "context":
        cmd_context(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
