# API Contracts

EGCE 是本地 CLI 工具，没有 HTTP API。对外暴露两种接口：

## 1. Python API

```python
from egce import RepoMap, Retriever, WorkspaceRetriever, ContextPacker, Verifier, compress_chunks, load_project_context
```

- `RepoMap(root).scan()` → `RepoMapResult`
- `Retriever(root).index()` / `.search(query)` → `list[EvidenceChunk]`
- `WorkspaceRetriever.from_workspace(root).search(query)` → `list[EvidenceChunk]`
- `compress_chunks(chunks, query)` → `list[EvidenceChunk]`
- `ContextPacker(budget).set_slot() / .build()` → `str`
- `load_project_context(packer, root)` — 自动加载 .egce/context/ 和活跃 spec
- `Verifier(root).run()` → `VerifyResult`（含 test、lint、context 过期检查）

## 2. CLI

所有命令通过 `egce` 入口：setup/init/sync/scan/search/pipeline/verify/spec/context

## 3. MCP Server

工具：egce_scan / egce_search / egce_pipeline / egce_verify
协议：JSON-RPC 2.0 over stdio
