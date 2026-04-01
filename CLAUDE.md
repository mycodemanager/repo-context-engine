# Project: repo-context-engine

Type: backend (python)

## EGCE Tools

This project uses EGCE for context management. Available commands:

```
egce scan .              # View repository structure
egce search "query" .    # Find relevant code
egce pipeline "task" .   # Full pipeline: search → compress → pack
egce verify .            # Run tests and linters
egce sync .              # Re-scan and update analysis
egce sync . --check      # Check if context files are stale
egce spec list           # List requirement specs
egce spec show <id>      # Show a spec
```

## Project Context

Read `.egce/context/` for project documentation:
- architecture.md — System architecture
- modules.md — Module responsibilities and boundaries
- conventions.md — Development conventions
- api-contracts.md — API interface definitions
- data-models.md — Data model documentation

Read `.egce/analysis/` for auto-generated analysis:
- repo-map.txt — File tree with class/function signatures
- modules.txt — Module structure and dependencies
- api-routes.txt — All API route definitions
- data-models.txt — All data model definitions

## Workflow

### Requirement Analysis
1. Read `.egce/context/` to understand existing architecture
2. Use `egce search` to find related existing code
3. Output a structured spec to `.egce/specs/` (if workspace) or communicate to user

### Development
1. Use `egce pipeline "<task>"` before starting each task
2. Follow conventions in `.egce/context/conventions.md`
3. After changes, run `egce verify .`

### Context Maintenance
After completing work that adds new modules, APIs, or models:
1. Run `egce sync . --check` to find stale context
2. Update relevant `.egce/context/` files
