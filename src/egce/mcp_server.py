"""EGCE MCP Server — expose EGCE tools to Claude Code via MCP protocol.

This implements a minimal MCP (Model Context Protocol) server using
JSON-RPC over stdin/stdout. No external dependencies beyond EGCE itself.

Claude Code can be configured to use this server, making EGCE tools
available as native tools in conversations.

Usage:
    python -m egce.mcp_server

Configure in Claude Code settings (~/.claude/settings.json):
    {
      "mcpServers": {
        "egce": {
          "command": "python3",
          "args": ["-m", "egce.mcp_server"]
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
import sys
import traceback

logger = logging.getLogger("egce.mcp")

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _rpc_response(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _rpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "egce_scan",
        "description": (
            "Scan a code repository and return a structured symbol map. "
            "Extracts file tree, class/function signatures, and import relationships. "
            "Use this to understand the structure of a codebase."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository root",
                },
                "include": {
                    "type": "string",
                    "description": "Comma-separated include glob patterns (e.g. 'src/*,lib/*')",
                },
                "exclude": {
                    "type": "string",
                    "description": "Comma-separated exclude glob patterns (e.g. 'tests/*,docs/*')",
                },
                "depth": {
                    "type": "integer",
                    "description": "Symbol nesting depth: 1=top-level only, 2=include methods (default: 2)",
                    "default": 2,
                },
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "egce_search",
        "description": (
            "Search a code repository for code chunks relevant to a query. "
            "Uses BM25 text search + symbol name matching. Returns ranked results "
            "with file paths, line numbers, and matching symbols."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository root",
                },
                "query": {
                    "type": "string",
                    "description": "Natural language query describing what you're looking for",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 10)",
                    "default": 10,
                },
                "exclude": {
                    "type": "string",
                    "description": "Comma-separated exclude patterns (e.g. 'docs/*,tests/*')",
                },
            },
            "required": ["repo_path", "query"],
        },
    },
    {
        "name": "egce_pipeline",
        "description": (
            "Run the full EGCE pipeline: search → compress → build focused repo map → "
            "pack into a prompt. Returns a ready-to-use context block with the most "
            "relevant code for your task, compressed to fit within a token budget."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository root",
                },
                "task": {
                    "type": "string",
                    "description": "Description of the task or question",
                },
                "token_budget": {
                    "type": "integer",
                    "description": "Maximum tokens for the packed context (default: 8000)",
                    "default": 8000,
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of evidence chunks to retrieve (default: 10)",
                    "default": 10,
                },
                "exclude": {
                    "type": "string",
                    "description": "Comma-separated exclude patterns (e.g. 'docs/*,tests/*')",
                },
            },
            "required": ["repo_path", "task"],
        },
    },
    {
        "name": "egce_verify",
        "description": (
            "Run tests and linters against a repository. Auto-detects pytest, ruff, "
            "npm test, go test, cargo test, etc. Returns pass/fail status with error details."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository root",
                },
                "only": {
                    "type": "string",
                    "description": "Comma-separated check kinds to run: test,lint,typecheck,build",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout per check in seconds (default: 120)",
                    "default": 120,
                },
            },
            "required": ["repo_path"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def handle_egce_scan(args: dict) -> str:
    from egce.repo_map import RepoMap

    repo_path = args["repo_path"]
    include = args.get("include", "").split(",") if args.get("include") else None
    exclude = args.get("exclude", "").split(",") if args.get("exclude") else None
    depth = args.get("depth", 2)

    repo = RepoMap(repo_path)
    result = repo.scan(include=include, exclude=exclude)
    text = result.to_text(max_depth=depth)

    n_files = len(result.files)
    n_symbols = sum(len(f.symbols) + sum(len(s.children) for s in f.symbols) for f in result.files)
    n_imports = sum(len(f.imports) for f in result.files)

    return f"{text}\n\n--- {n_files} files, {n_symbols} symbols, {n_imports} imports ---"


def handle_egce_search(args: dict) -> str:
    from egce.retrieve import Retriever

    repo_path = args["repo_path"]
    query = args["query"]
    top_k = args.get("top_k", 10)
    exclude = args.get("exclude", "").split(",") if args.get("exclude") else None

    retriever = Retriever(repo_path)
    retriever.index(exclude=exclude)
    chunks = retriever.search(query, top_k=top_k)

    if not chunks:
        return "No relevant code found for this query."

    parts = [f"Found {len(chunks)} relevant chunks:\n"]
    for i, c in enumerate(chunks):
        sym_str = f"  symbols: {', '.join(c.symbols[:5])}" if c.symbols else ""
        parts.append(f"## {i + 1}. {c.source_uri}  L{c.start_line}-{c.end_line}  (score: {c.score:.3f}){sym_str}")
        parts.append(c.content)
        parts.append("")

    return "\n".join(parts)


def handle_egce_pipeline(args: dict) -> str:
    from egce.compress import compress_chunks
    from egce.packer import ContextPacker, Priority, count_tokens
    from egce.retrieve import Retriever

    repo_path = args["repo_path"]
    task = args["task"]
    token_budget = args.get("token_budget", 8000)
    top_k = args.get("top_k", 10)
    exclude = args.get("exclude", "").split(",") if args.get("exclude") else None

    # 1. Index & search
    retriever = Retriever(repo_path)
    retriever.index(exclude=exclude)
    chunks = retriever.search(task, top_k=top_k)

    # 2. Compress
    compressed = compress_chunks(chunks, task, target_ratio=0.5)

    # 3. Focused repo map
    repo_result = retriever.repo_map_result
    focus_files = {c.source_uri for c in chunks}
    focused_map = repo_result.focused_text(focus_files) if repo_result else ""

    # 4. Pack
    packer = ContextPacker(token_budget=token_budget)
    packer.set_slot("task", task, priority=Priority.HIGH)
    packer.set_slot("repo_map", focused_map, priority=Priority.NORMAL)
    packer.set_slot(
        "evidence",
        "\n\n".join(c.to_text() for c in compressed),
        priority=Priority.NORMAL,
    )

    prompt = packer.build()

    # Summary
    raw_tok = sum(count_tokens(c.content) for c in chunks)
    comp_tok = sum(count_tokens(c.content) for c in compressed)
    prompt_tok = count_tokens(prompt)

    summary = (
        f"# EGCE Pipeline Result\n\n"
        f"- Retrieved: {len(chunks)} chunks, {raw_tok} tokens\n"
    )
    if raw_tok:
        summary += f"- Compressed: {comp_tok} tokens ({comp_tok / raw_tok:.0%} of raw)\n"
    summary += (
        f"- Focus files: {len(focus_files)}\n"
        f"- Packed prompt: {prompt_tok} tokens (budget: {token_budget})\n\n"
    )

    return summary + prompt


def handle_egce_verify(args: dict) -> str:
    from egce.verify import CheckKind, Verifier

    repo_path = args["repo_path"]
    timeout = args.get("timeout", 120)
    kinds = None
    if args.get("only"):
        kinds = {CheckKind(k) for k in args["only"].split(",")}

    v = Verifier(repo_path, timeout=timeout)
    result = v.run(kinds=kinds)

    parts = []
    for c in result.checks:
        status = "PASS" if c.passed else "FAIL"
        parts.append(f"[{status}] {c.command}  ({c.duration_s}s)")
        if not c.passed:
            if c.summary:
                parts.append(f"  Summary: {c.summary}")
            if c.stderr:
                # Limit output to avoid overwhelming
                stderr = c.stderr[-2000:] if len(c.stderr) > 2000 else c.stderr
                parts.append(f"  Stderr:\n{stderr}")

    if result.passed:
        parts.append("\nAll checks passed.")
    else:
        parts.append(f"\n{len(result.failed_checks)} check(s) failed.")

    return "\n".join(parts)


_HANDLERS = {
    "egce_scan": handle_egce_scan,
    "egce_search": handle_egce_search,
    "egce_pipeline": handle_egce_pipeline,
    "egce_verify": handle_egce_verify,
}

# ---------------------------------------------------------------------------
# MCP protocol loop (JSON-RPC over stdin/stdout)
# ---------------------------------------------------------------------------


def _handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return _rpc_response(id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "egce", "version": "0.2.0"},
        })

    elif method == "notifications/initialized":
        return None  # notification, no response

    elif method == "tools/list":
        return _rpc_response(id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = _HANDLERS.get(tool_name)
        if handler is None:
            return _rpc_error(id, -32601, f"Unknown tool: {tool_name}")
        try:
            result_text = handler(tool_args)
            return _rpc_response(id, {
                "content": [{"type": "text", "text": result_text}],
            })
        except Exception as e:
            tb = traceback.format_exc()
            return _rpc_response(id, {
                "content": [{"type": "text", "text": f"Error: {e}\n\n{tb}"}],
                "isError": True,
            })

    elif method == "ping":
        return _rpc_response(id, {})

    else:
        if id is not None:
            return _rpc_error(id, -32601, f"Method not found: {method}")
        return None  # unknown notification, ignore


def main() -> None:
    """Run the MCP server, reading JSON-RPC messages from stdin."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            msg = json.loads(line)
            response = _handle_request(msg)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except json.JSONDecodeError as e:
            logger.debug("Invalid JSON from stdin: %s", e)
            continue
        except KeyboardInterrupt:
            break
        except Exception:
            logger.warning("Unexpected error in MCP server loop", exc_info=True)
            continue


if __name__ == "__main__":
    main()
