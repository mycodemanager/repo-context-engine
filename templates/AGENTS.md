# EGCE — Evidence-Grounded Context Engine

This project has EGCE installed (`pip install egce`). Use it to search,
understand, and verify code in this repository.

## Tools

### Search for relevant code
```
egce search "<natural language query>" .
```
Returns ranked code chunks with file paths, line numbers, and relevance scores.
Use this when you need to find code related to a specific topic or task.

### Get a compressed context snapshot
```
egce pipeline "<task description>" .
```
Runs the full pipeline: search → compress → pack. Returns a token-budgeted
context block with the most relevant code for your task.

### Scan repository structure
```
egce scan .
```
Returns the file tree with class/function signatures and import relationships.
Use this to understand the overall codebase structure.

### Verify changes
```
egce verify .
```
Auto-detects and runs tests (pytest, npm test, go test, cargo test) and
linters (ruff, eslint, clippy). Use this after making any code changes.

## Workflow for code tasks

1. Run `egce search` or `egce pipeline` to find relevant code
2. Read and understand the relevant files
3. Make minimal, targeted changes
4. Run `egce verify .` to confirm tests and lint pass
5. If verification fails, fix the issues and re-verify
