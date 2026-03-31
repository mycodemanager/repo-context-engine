# EGCE — Evidence-Grounded Context Engine

This project has EGCE installed. Use it to understand the codebase, find
relevant code, and verify your changes.

## Available commands

### Scan the repository structure
```bash
egce scan .
egce scan . --depth 1                    # top-level symbols only
egce scan . --include "src/*" --exclude "tests/*"
```

### Search for relevant code
```bash
egce search "authentication token validation" .
egce search "database connection pooling" . --top-k 5
egce search "error handling in API routes" . --exclude "tests/*,docs/*"
```

### Full pipeline (search + compress + pack)
```bash
egce pipeline "fix the authentication bug in login flow" .
egce pipeline "add retry logic to HTTP client" . --budget 4000
egce pipeline "refactor database queries for performance" . --exclude "tests/*" --stats
```

### Verify changes (auto-detects test/lint tools)
```bash
egce verify .
egce verify . --only test
egce verify . --only lint
```

## When to use EGCE

- **Before starting a task**: Run `egce scan` to understand the codebase structure,
  or `egce search` to find code relevant to your task.

- **When context is too large**: Run `egce pipeline` to get a compressed, focused
  view of the most relevant code for your task.

- **After making changes**: Run `egce verify` to check if tests and linters pass.

- **When you need to find related code**: Run `egce search` with a description of
  what you're looking for. It uses BM25 + symbol matching to find relevant chunks.

## Workflow

For any non-trivial code task, follow this pattern:

1. `egce search "<description of what you need>"` — find relevant code
2. Read the top results to understand the codebase
3. Make your changes
4. `egce verify .` — check tests and lint
5. If verification fails, read the error output and fix

For complex tasks where you need a comprehensive context snapshot:

1. `egce pipeline "<task description>" . --budget 8000` — get a packed context
2. Use the output to understand the full picture before making changes

## Python API

You can also use EGCE programmatically:

```python
from egce import RepoMap, Retriever, ContextPacker, Verifier, compress_chunks

# Scan
result = RepoMap(".").scan()

# Search
retriever = Retriever(".")
retriever.index()
chunks = retriever.search("your query", top_k=10)

# Compress
compressed = compress_chunks(chunks, "your query")

# Verify
Verifier(".").run()
```
