# Architecture

EGCE 是一个纯本地的 Python 工具库，全局安装后为 AI 编码工具提供代码上下文支持。

## 核心理念

- AI 幻觉的根源是上下文不足，不是模型问题
- 从需求分析到开发到测试，每个阶段都需要高质量的代码上下文
- 需求规格（spec）是给 AI 执行的精确规格，不是给人看的模糊 PRD
- 不可测试的变更是违规操作

## 设计约束

- **不调 LLM** — 纯本地工具，context 文件由 AI 在对话中生成
- **不做 Git 操作** — clone/commit/push 交给 AI 工具
- **不做 Web UI** — AI 工具（Claude Code/Cursor/Codex）就是 UI
- **不做权限管理** — 用 Git 仓库权限

## 数据流

```
egce init → 扫描代码 → 生成 analysis/（自动，不提交 Git）
AI 读 analysis/ → 生成 context/（人审核后提交 Git）
PM 提需求 → AI 读 context/ + egce search → 输出 spec
egce spec validate → 检查 spec 自包含性
egce spec test → 生成测试骨架
AI 按 spec 开发 → egce verify → 更新 context → 提交
```

## 三层信息架构

1. **analysis/**（自动生成，不提交）— repo-map、API 路由、数据模型、组件清单等
2. **context/**（人审核后提交）— 架构、模块、约定、接口契约等
3. **specs/**（工作区级别）— 需求规格，开发完成后归档
