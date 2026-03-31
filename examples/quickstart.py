#!/usr/bin/env python3
"""Quickstart: 用 3 行代码扫描一个仓库。

Usage:
    pip install egce
    python examples/quickstart.py /path/to/any/repo
"""

import sys
from egce import RepoMap, Retriever, ContextPacker, compress_chunks
from egce.packer import count_tokens

repo_path = sys.argv[1] if len(sys.argv) > 1 else "."

# ── 扫描 ──
print("Scanning...")
result = RepoMap(repo_path).scan()
n_files = len(result.files)
n_symbols = sum(len(f.symbols) + sum(len(s.children) for s in f.symbols) for f in result.files)
print(f"Found {n_files} files, {n_symbols} symbols\n")

# ── 检索 ──
query = "main entry point and configuration"
print(f"Searching: \"{query}\"")
retriever = Retriever(repo_path)
retriever.index()
chunks = retriever.search(query, top_k=5)
print(f"Found {len(chunks)} relevant chunks:\n")
for c in chunks:
    print(f"  {c.source_uri} L{c.start_line}-{c.end_line}  score={c.score:.3f}")

# ── 压缩 ──
compressed = compress_chunks(chunks, query, target_ratio=0.5)
raw_tokens = sum(count_tokens(c.content) for c in chunks)
comp_tokens = sum(count_tokens(c.content) for c in compressed)
print(f"\nCompressed: {raw_tokens} → {comp_tokens} tokens ({comp_tokens/raw_tokens:.0%})\n")

# ── 打包 ──
focus_files = {c.source_uri for c in chunks}
repo_map = retriever.repo_map_result
focused = repo_map.focused_text(focus_files) if repo_map else result.to_text()

packer = ContextPacker(token_budget=4000)
packer.set_slot("system", "You are a helpful code assistant.")
packer.set_slot("task", f"Explain: {query}")
packer.set_slot("repo_map", focused)
packer.set_slot("evidence", "\n\n".join(c.to_text() for c in compressed))

prompt = packer.build()
print(f"Final prompt: {count_tokens(prompt)} tokens (budget: 4000)")
print(f"\nDone. Send this prompt to any LLM API.")
