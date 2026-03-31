# EGCE — Research & Development Workflow

This project uses EGCE for context management. Commands available globally via `egce`.

## Tools

```
egce init .              — Initialize project analysis
egce sync .              — Re-scan and update analysis
egce scan .              — View repository structure
egce search "query" .    — Find relevant code chunks
egce pipeline "task" .   — Full pipeline: search → compress → pack
egce verify .            — Run tests and linters
egce spec list           — List requirement specs
egce spec show <id>      — View a spec
```

## Context Files

- `.egce/analysis/` — Auto-generated code analysis (read-only)
- `.egce/context/` — Project documentation (read and maintain)
- `.egce/specs/` — Structured requirement specifications

## Workflow

1. Read `.egce/context/` to understand the project
2. Use `egce search` or `egce pipeline` to find relevant code
3. For new requirements: analyze existing code, output structured spec with exact API definitions
4. For development: follow spec exactly, run `egce verify` after each change
5. After completion: update `.egce/context/` if architecture/APIs/models changed
