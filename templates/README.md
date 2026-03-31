# EGCE Integration Templates

This directory contains instruction templates that let AI coding assistants
(Claude Code, Codex, Cursor, etc.) use EGCE tools through natural conversation.

## Files

- **CLAUDE.md** — Drop into your project root. Claude Code will automatically read
  it and know how to use EGCE tools via CLI commands.

- **AGENTS.md** — OpenAI Codex / Agents compatible instruction file.

- **claude-settings-snippet.json** — MCP server config snippet for Claude Code.
  Paste into `~/.claude/settings.json` to register EGCE as a native tool provider.

## Setup

### Option A: Instruction file (works with any AI tool)

```bash
# Copy to your project root
cp CLAUDE.md /path/to/your/project/CLAUDE.md
# or
cp AGENTS.md /path/to/your/project/AGENTS.md
```

The AI will read the file and use `egce` CLI commands automatically.

### Option B: MCP Server (Claude Code native integration)

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "egce": {
      "command": "python3",
      "args": ["-m", "egce.mcp_server"]
    }
  }
}
```

Then in Claude Code, EGCE tools (`egce_scan`, `egce_search`, `egce_pipeline`,
`egce_verify`) appear as native tools — no CLI needed.
