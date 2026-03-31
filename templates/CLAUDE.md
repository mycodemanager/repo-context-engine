# EGCE — Research & Development Workflow

This project uses EGCE (Evidence-Grounded Context Engine) for context management.
All commands are globally available via `egce`.

## Quick Reference

```bash
egce init .              # Initialize project (first time)
egce sync .              # Re-scan and update analysis
egce sync . --check      # Check if context is stale
egce scan .              # View repo structure
egce search "query" .    # Find relevant code
egce pipeline "task" .   # Full context pipeline
egce verify .            # Run tests/lint
egce spec list           # List requirement specs
egce spec show <id>      # View a spec
egce spec status <id> <status>  # Update spec status
```

## Project Context

- `.egce/analysis/` — Auto-generated analysis (do not edit, regenerate with `egce sync`)
- `.egce/context/` — Human-reviewed project documentation (edit and commit)
- `.egce/specs/` — Requirement specifications

## Workflow by Phase

### Phase 1: Workspace Setup

When user provides repository URLs:
1. Ask where to create the workspace
2. Create the directory and git clone each repository
3. Run `egce init` in the workspace root
4. Read `.egce/analysis/` files for each project
5. Generate `.egce/context/` files based on analysis results
6. Ask user to review the generated context

### Phase 2: Requirement Analysis

When user describes a new requirement:
1. Read `.egce/context/` to understand existing architecture, modules, and APIs
2. Run `egce search "<requirement keywords>"` in each project to find related code
3. Analyze what exists, what needs to change, and what needs to be created
4. Output a structured spec (YAML) with:
   - Precise API definitions (method, path, request/response fields with types)
   - Frontend page changes (which page, what components, what interactions)
   - Affected files list for both frontend and backend
   - Testing requirements
5. Save spec to workspace `.egce/specs/` directory
6. Ask user to review and approve the spec

IMPORTANT: The spec must be precise enough for AI to execute without guessing.
Every API field must have a name and type. Every page change must specify the component.

### Phase 3: Development

When user approves a spec (status: approved):
1. Update spec status to `in_progress`
2. Process tasks one by one, in order
3. For each task:
   a. Run `egce pipeline "<task description>"` to get relevant context
   b. Read the spec for exact API/field/component definitions
   c. Write code following `.egce/context/conventions.md`
   d. Run `egce verify .` after completing the task
   e. If verification fails, read errors and fix
   f. Mark task as done in the spec
4. After all tasks complete, update spec status to `done`

IMPORTANT: Follow the spec exactly. Do not change API paths, field names, or
response formats from what the spec defines. The frontend and backend must match.

### Phase 4: Context Maintenance

After completing a spec:
1. Run `egce sync . --check` to find stale context
2. If new modules were added → update `context/modules.md`
3. If new APIs were added → update `context/api-contracts.md`
4. If new data models were added → update `context/data-models.md`
5. If new conventions emerged → update `context/conventions.md`
6. Commit updated `.egce/context/` files with the code

### Phase 5: Verification & Handoff

1. Run `egce verify .` one final time
2. Summarize what was done, what was changed, and what to test
3. If there are follow-up items, note them for the next cycle
