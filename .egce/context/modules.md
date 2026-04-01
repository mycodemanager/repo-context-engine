# Modules

## src/egce/ — 核心库

| 模块 | 职责 |
|---|---|
| repo_map.py | tree-sitter 扫描，提取文件树 + 函数签名 + import 关系 |
| retrieve.py | BM25 + symbol 混合检索，WorkspaceRetriever 多项目联合检索 |
| compress.py | query-aware 代码片段压缩（保留签名/约束，删除注释/样板）|
| packer.py | 槽位制 token 预算打包，自动加载 .egce/context/ 和活跃 spec |
| verify.py | 自动检测并运行 pytest/ruff/npm test/go test/cargo test + context 过期检查 |
| workspace.py | egce init（扫描 + 生成 .egce/）、egce sync（重扫 + 过期检测）|
| spec.py | spec 管理 + 自包含性验证 + 测试骨架生成 |
| telemetry.py | pipeline token 统计和追踪（JSONL 记录）|
| cli.py | 命令行入口（setup/init/sync/scan/search/pipeline/verify/spec/context）|
| mcp_server.py | Claude Code MCP 原生工具集成（JSON-RPC over stdio）|

## src/egce/extractors/ — 可插拔框架提取器

每个框架一个文件，通过 `@register_extractor` 装饰器注册。
自动检测机制：读依赖文件（pyproject.toml/package.json/go.mod）中的关键词匹配框架。
提取容错：每个 extract_* 方法独立 try/catch，失败写入 AnalysisResult.warnings 而非静默返回空。
覆盖率检查：框架被检测到但提取结果为 0 时自动生成警告，通过 CLI 输出 WARNING。

| 提取器 | 语言 | 提取内容 |
|---|---|---|
| fastapi_ext.py | Python | API 路由 + Pydantic/SQLModel 模型 |
| django_ext.py | Python | URL 路由 + ORM 模型 |
| express_ext.py | JS/TS | HTTP 路由 + TS interface + Mongoose schema |
| react_ext.py | JS/TS | 页面路由 + 组件 + props + API 调用 + Redux/Zustand |
| vue_ext.py | JS/TS | 页面路由 + 组件 + API 调用 + Pinia/Vuex |

通用提取：Docker 基础设施检测、.env.example 环境变量。

## tests/ — 测试

65 个测试，覆盖所有核心功能和端到端集成。

## templates/ — AI 工具指令模板

- CLAUDE.md — Claude Code 项目级指令
- AGENTS.md — Codex 项目级指令
- global-claude-md.md — 全局指令（egce setup 写入 ~/.claude/CLAUDE.md）
