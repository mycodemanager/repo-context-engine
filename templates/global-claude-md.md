# EGCE — Evidence-Grounded Context Engine

You have EGCE installed globally. Use it to manage code project context.

## When the user wants to start a new project

When the user provides repository URLs and wants to create a workspace:

1. Ask: "你想把工作区创建在哪个目录？"
2. Create the workspace directory
3. git clone each repository into the workspace
4. Run `egce init <workspace_path>` to scan all projects and generate analysis
5. **Check stderr for WARNING lines** — if a framework is detected but extraction results are empty, investigate whether the code follows standard patterns before proceeding
6. Read the generated `.egce/analysis/` files in each project
7. Based on the analysis, generate `.egce/context/` files (architecture.md, modules.md, api-contracts.md, data-models.md, conventions.md)
8. Show the user the generated context and ask them to review

Example workspace structure after init:
```
workspace/
  .egce/workspace.yaml
  .egce/specs/
  backend/.egce/analysis/    (auto-generated)
  backend/.egce/context/     (AI generates, human reviews)
  frontend/.egce/analysis/
  frontend/.egce/context/
```

## When working on an existing project with .egce/ directory

1. Read `.egce/context/` to understand the project
2. Use `egce search "<query>" .` to find relevant code
3. Use `egce pipeline "<task>" .` to get compressed context for a specific task

## When the user describes a requirement

1. Read `.egce/context/` for existing architecture and conventions
2. Run `egce search` in each project to find related existing code
3. Analyze what exists, what needs to change
4. Output a structured spec (YAML) to the workspace `.egce/specs/` directory:
   - Precise API definitions with field names and types
   - Frontend page/component changes
   - Affected files
   - Testing requirements
5. Run `egce spec validate <id>` to check self-containment:
   - Are all API fields defined?
   - Do frontend calls match backend routes?
   - Are test cases listed?
6. Fix any validation errors before asking user to review
7. Ask the user to review and approve

## When developing from a spec

1. Run `egce spec validate <id>` to confirm spec is complete
2. Run `egce spec test <id> --output-dir tests/` to generate test skeleton
3. Read the spec for exact interface definitions
4. Run `egce pipeline "<task>"` before each task for context
3. Follow `.egce/context/conventions.md` for code style
4. Run `egce verify .` after each task
5. If verify reports stale context, update the relevant `.egce/context/` files before proceeding
6. After all tasks: run `egce sync . --check` and update stale context files

## Commands

```
egce init <path>                    — Initialize project/workspace
egce sync <path>                    — Re-scan and update analysis
egce sync <path> --check            — Check context freshness
egce scan <path>                    — View code structure
egce search "<query>" <path>        — Find relevant code
egce pipeline "<task>" <path>       — Full context pipeline
egce verify <path>                  — Run tests/lint
egce spec list                      — List specs
egce spec show <id>                 — Show spec
egce spec status <id> <s>           — Update spec status
egce spec validate <id>             — Check spec self-containment
egce spec test <id> --output-dir d  — Generate test skeleton from spec
```

All commands support `--verbose` / `-v` for debug logging.
