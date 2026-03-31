# EGCE — Evidence-Grounded Context Engine

面向大型代码仓库的上下文工程工具库。解决 AI 编码助手在长任务中的核心问题：**上下文太多放不下，放进去的又不够相关。**

EGCE 不是一个 agent 框架，而是一个可嵌入的 Python 库，提供五个能力：

```
扫描仓库 → 检索证据 → 压缩内容 → 打包 prompt → 验证输出
```

## 解决什么问题

| 问题 | EGCE 怎么做 |
|---|---|
| 仓库太大，全塞进 prompt 放不下 | `RepoMap` 提取文件树 + 函数签名，用 5% 的 token 提供 100% 的导航视图 |
| 不知道哪些代码和当前任务相关 | `Retriever` 做 BM25 + symbol 混合检索，自动找出最相关的代码片段 |
| 检索结果太长，有很多无关内容 | `compress_chunks` 按 query 相关性保留签名/约束/错误处理，删掉注释和样板 |
| prompt 拼接混乱，重要信息被挤掉 | `ContextPacker` 按优先级分槽打包，关键信息不会被截断 |
| 模型输出的代码不知道对不对 | `Verifier` 自动跑 pytest/ruff/lint，返回结构化反馈 |

## 安装

```bash
pip install egce
```

或从源码安装：

```bash
git clone https://github.com/mycodemanager/repo-context-engine.git
cd repo-context-engine
pip install -e ".[dev]"
```

## 5 分钟 Quickstart

### 用法一：作为 Python 库（推荐）

```python
from egce import RepoMap, Retriever, ContextPacker, Verifier, compress_chunks

# 1. 扫描仓库 → 生成 symbol map
repo = RepoMap("/path/to/your/repo")
result = repo.scan()
print(result.to_text())  # 文件树 + 类/函数签名 + import 关系

# 2. 检索与任务相关的代码片段
retriever = Retriever("/path/to/your/repo")
retriever.index()
chunks = retriever.search("fix authentication token validation bug", top_k=10)

for chunk in chunks:
    print(f"{chunk.source_uri} L{chunk.start_line}-{chunk.end_line} score={chunk.score}")

# 3. 压缩检索结果（保留相关内容，删除无关注释和样板）
compressed = compress_chunks(chunks, "authentication token validation", target_ratio=0.5)

# 4. 按 token 预算打包成 prompt
packer = ContextPacker(token_budget=8000)
packer.set_slot("system", "You are a code assistant.")
packer.set_slot("task", "Fix the authentication bug described in issue #42.")
packer.set_slot("repo_map", result.to_text())
packer.set_slot("evidence", "\n\n".join(c.to_text() for c in compressed))

prompt = packer.build()  # 自动裁剪低优先级内容以适应 budget
# → 把 prompt 发给任意 LLM API

# 5. 验证 LLM 输出
verifier = Verifier("/path/to/your/repo")
verify_result = verifier.run()

if not verify_result.passed:
    # 把失败信息反馈给 packer，让模型重试
    packer.set_slot("verifier_feedback", verify_result.to_feedback())
    retry_prompt = packer.build()
```

### 用法二：命令行

```bash
# 扫描仓库，输出 symbol map
egce scan /path/to/repo

# 输出 JSON 格式
egce scan /path/to/repo --json

# 只看顶层 symbol（不展开方法）
egce scan /path/to/repo --depth 1

# 搜索与任务相关的代码
egce search "authentication token validation" /path/to/repo

# 一行跑完全流程：检索 → 压缩 → 打包
egce pipeline "fix the login bug" /path/to/repo --budget 8000

# 运行验证（自动检测 pytest/ruff/eslint 等）
egce verify /path/to/repo

# 组装 prompt（从文件读取 slot 内容）
egce pack --budget 8000 \
    --slot system=system_prompt.txt \
    --slot task=task.txt \
    --slot evidence=evidence.txt
```

### 用法三：在 Claude Code 中对话使用（MCP Server）

把 EGCE 注册为 Claude Code 的 MCP 工具，对话时直接调用：

**配置方法** — 在 `~/.claude/settings.json` 中添加：

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

配置后重启 Claude Code，即可在对话中直接使用这些工具：

- `egce_scan` — 扫描仓库结构
- `egce_search` — 搜索相关代码
- `egce_pipeline` — 全流程：检索 → 压缩 → 打包
- `egce_verify` — 运行测试和 lint

对话示例：
```
你: 帮我理解这个仓库的结构
Claude: (自动调用 egce_scan) 这个仓库有 48 个核心文件...

你: 找一下和用户认证相关的代码
Claude: (自动调用 egce_search) 找到 10 个相关代码片段...

你: 修好这个 bug 之后帮我跑一下测试
Claude: (自动调用 egce_verify) 所有测试通过 ✓
```

### 用法四：在 Codex / Cursor 等工具中使用（指令文件）

把 EGCE 的指令文件拷到你的项目根目录，AI 工具会自动读取并学会使用 `egce` 命令：

```bash
# 适用于 Claude Code
cp templates/CLAUDE.md /path/to/your/project/CLAUDE.md

# 适用于 OpenAI Codex
cp templates/AGENTS.md /path/to/your/project/AGENTS.md
```

放好之后，AI 在处理任务时会自动调用 `egce search`、`egce pipeline`、`egce verify` 等命令。无需额外配置。

## 核心 API

### RepoMap — 仓库扫描

```python
repo = RepoMap(
    "/path/to/repo",
    ignore_dirs={"node_modules", ".git", "__pycache__"},  # 默认已包含
    max_file_bytes=512_000,  # 跳过超大文件
)

result = repo.scan(
    include=["src/*"],       # 只扫描这些路径
    exclude=["tests/*"],     # 排除这些路径
)

# 完整输出
result.to_text(max_depth=2)

# 聚焦输出：只展开相关文件的 symbol，其他文件一行摘要
result.focused_text(
    focus_files={"src/auth.py", "src/router.py"},
    show_others=True,
)

# 导出为 dict/JSON
result.to_dict()
```

支持语言：Python, JavaScript, TypeScript, Go, Rust, Java

### Retriever — BM25 + Symbol 检索

```python
retriever = Retriever(
    "/path/to/repo",
    chunk_lines=40,   # 每个 chunk 的行数
    overlap=10,        # chunk 之间的重叠行数
)

retriever.index(
    exclude=["docs/*", "tests/*"],
)

chunks = retriever.search(
    "dependency injection model validation",
    top_k=10,
    bm25_weight=0.6,     # BM25 分数权重
    symbol_weight=0.4,    # symbol 命中权重
)

# 每个 chunk 包含完整来源信息
for c in chunks:
    print(c.source_uri)    # "src/router.py"
    print(c.start_line)    # 42
    print(c.end_line)      # 80
    print(c.symbols)       # ["Router", "Router.dispatch"]
    print(c.score)         # 0.85
    print(c.content)       # 原始代码
```

### compress_chunks — 代码压缩

```python
compressed = compress_chunks(
    chunks,
    query="authentication token validation",
    target_ratio=0.5,    # 目标保留 50% 的行
    min_score=0.1,       # 低于此分数的行候选删除
    context_lines=1,     # 保留的行上下各保留 1 行上下文
)

# 压缩后保留：函数签名、import、raise/return、装饰器、TODO/FIXME
# 压缩删除：无关注释、空行、日志调用、print、pass
# 被删除的连续行会合并为 "[...N lines omitted...]"
```

### ContextPacker — Prompt 打包

```python
from egce import ContextPacker
from egce.packer import Priority

packer = ContextPacker(token_budget=8000)

# 内置 8 个默认 slot（可自定义）：
# system(10%) > task(10%) > pinned_facts(10%) > repo_map(10%)
# > evidence(40%) > memory(10%) > verifier_feedback(5%) > output_contract(5%)

packer.set_slot("system", "...", priority=Priority.CRITICAL)
packer.set_slot("task", "...", priority=Priority.HIGH)
packer.set_slot("evidence", "...", priority=Priority.NORMAL)
packer.set_slot("custom_slot", "...", priority=Priority.LOW)  # 可加自定义 slot

prompt = packer.build()
# 超预算时自动按优先级裁剪：CRITICAL > HIGH > NORMAL > LOW

# 查看 token 使用统计
packer.stats()
# → {"budget": 8000, "total_before_trim": 12000, "over_budget": 4000,
#    "slots": {"system": {"tokens": 30, "priority": "CRITICAL"}, ...}}
```

### Verifier — 测试/Lint 验证

```python
verifier = Verifier("/path/to/repo", timeout=120)

# 自动检测并运行（支持 pytest / ruff / npm test / go test / cargo test）
result = verifier.run()
result.passed           # True/False
result.failed_checks    # 失败的检查列表

# 只跑特定类型
from egce.verify import CheckKind
result = verifier.run(kinds={CheckKind.TEST})

# 跑自定义命令
result = verifier.run_command(CheckKind.CUSTOM, ["mypy", "src/"])

# 生成反馈文本（可直接塞进 packer 的 verifier_feedback slot）
result.to_feedback(max_chars=3000)
```

## 完整 Pipeline 示例

把上面的能力串成一条完整链路：

```python
from egce import RepoMap, Retriever, ContextPacker, Verifier, compress_chunks
from egce.packer import Priority

REPO = "/path/to/your/repo"
TASK = "Fix: POST requests with nested Pydantic models lose field validators"

# ── 1. Index ──
retriever = Retriever(REPO)
retriever.index(exclude=["docs/*", "tests/*"])

# ── 2. Search ──
chunks = retriever.search(TASK, top_k=10)

# ── 3. Compress ──
compressed = compress_chunks(chunks, TASK, target_ratio=0.5)

# ── 4. Focused repo map ──
repo_result = retriever.repo_map_result
focus_files = {c.source_uri for c in chunks}
focused_map = repo_result.focused_text(focus_files)

# ── 5. Pack ──
packer = ContextPacker(token_budget=8000)
packer.set_slot("system", "You are a senior developer. Write minimal, correct patches.")
packer.set_slot("task", TASK)
packer.set_slot("repo_map", focused_map)
packer.set_slot("evidence", "\n\n".join(c.to_text() for c in compressed))
packer.set_slot("output_contract", "Reply with: 1) root cause  2) diff patch  3) test command")

prompt = packer.build()
# → send prompt to your LLM

# ── 6. Verify (after applying LLM's patch) ──
result = Verifier(REPO).run()
if not result.passed:
    packer.set_slot("verifier_feedback", result.to_feedback())
    retry_prompt = packer.build()
    # → send retry_prompt to LLM
```

## 在你自己的 Agent 中集成

EGCE 是一个库，不是框架。你可以把它嵌入到任何 agent 实现中：

```python
# 在你的 agent loop 中
def agent_step(task: str, repo_path: str):
    # 用 EGCE 构建高质量上下文
    retriever = Retriever(repo_path)
    retriever.index()
    chunks = retriever.search(task, top_k=10)
    compressed = compress_chunks(chunks, task)

    packer = ContextPacker(token_budget=8000)
    packer.set_slot("task", task)
    packer.set_slot("evidence", "\n\n".join(c.to_text() for c in compressed))

    prompt = packer.build()

    # 调用你自己的 LLM
    response = your_llm_call(prompt)

    # 验证输出
    result = Verifier(repo_path).run()
    return response, result
```

## 项目结构

```
src/egce/
  __init__.py        # 公开 API
  repo_map.py        # tree-sitter 仓库扫描，提取 symbol map
  retrieve.py        # BM25 + symbol 混合检索
  compress.py        # query-aware 代码片段压缩
  packer.py          # 槽位制 token 预算打包器
  verify.py          # 自动检测并运行 test/lint
  cli.py             # 命令行工具
  mcp_server.py      # MCP Server（Claude Code 原生集成）
templates/
  CLAUDE.md          # Claude Code 指令模板
  AGENTS.md          # Codex / 其他 AI 工具指令模板
```

## 实测数据（FastAPI, 109K 行代码）

```
原始源码          ~436,000 tokens  (100%)
→ 全量 repo map    210,835 tokens  (48.3%)   tree-sitter 提取签名
→ 聚焦 repo map     44,121 tokens  (10.1%)   只展开检索命中的 8 个文件
→ 检索 + 压缩        611 tokens   (0.14%)   10 个代码片段，保留结构
→ 最终 prompt        8,042 tokens  (1.84%)   54x 压缩，包含完整上下文
```

## 设计原则

1. **摘要不是事实源** — 所有进入 prompt 的内容都带文件路径和行号
2. **证据优先** — 检索结果带 provenance，压缩保留来源回指
3. **验证先于反思** — 编译/测试/lint 是最终裁决者，不靠模型"自我检查"
4. **结构优先于语义** — 先压缩文件树/签名/依赖关系，再考虑全文语义

## License

Apache-2.0
