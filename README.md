# EGCE — 让 AI 真正理解你的代码项目

EGCE 是一个研发上下文引擎。安装后，你可以在 Claude Code / Cursor / Codex 中通过对话完成需求分析、代码开发和测试验证，不需要手动操作任何命令。

**一句话说明**：让 AI 在开发前先读懂你的项目——API 接口、数据模型、模块结构、开发约定——然后基于真实代码做需求分析和开发，而不是瞎猜。

---

## 适合谁用

| 角色 | 你可以做什么 |
|---|---|
| 产品经理 | 对话描述需求，AI 基于现有代码自动分析并输出需求规格 |
| 后端开发 | AI 理解你的 API、数据模型和模块结构后，按规格精确开发 |
| 前端开发 | AI 理解你的组件、页面路由和状态管理后，按规格精确开发 |
| 测试 | AI 告诉你这次改动影响了哪些功能，该测什么 |
| 新人 | 对话问 AI 项目架构、业务逻辑，基于真实文档回答而不是猜测 |

**不需要懂代码也能使用。** 所有操作都是对话完成。

---

## 快速开始（3 步）

### 第 1 步：安装

确保你的电脑安装了 Python 3.9 或更高版本，然后打开终端执行：

```bash
pip install git+https://github.com/mycodemanager/repo-context-engine.git
```

安装完成后，执行配置命令（只需要做一次）：

```bash
egce setup
```

这个命令会自动把 EGCE 的工作指令写入 AI 工具的全局配置。执行后 AI 就知道：
- 用户说"创建工作区"时该怎么做
- 怎么调用 EGCE 命令扫描代码
- 怎么按规范生成需求规格
- 怎么按流程开发和验证

### 第 2 步：打开 AI 工具

打开你常用的 AI 编码工具：

- **Claude Code**（推荐，egce setup 已自动配置）
- **Cursor**（需要手动把 `templates/CLAUDE.md` 放到项目根目录）
- **OpenAI Codex**（需要手动把 `templates/AGENTS.md` 放到项目根目录）

### 第 3 步：对话开始工作

直接告诉 AI 你的项目信息：

```
你：我要开发一个项目，后端仓库是 git@github.com:xxx/backend.git，
    前端仓库是 git@github.com:xxx/frontend.git
```

AI 会自动执行：
1. 询问你工作区放在哪个位置
2. 创建目录，拉取代码
3. 运行 `egce init` 扫描代码，提取 API 接口、数据模型、组件结构
4. 基于扫描结果生成项目上下文文档
5. 让你审核后，告诉你可以开始工作了

> **提示**：如果扫描过程中检测到了框架（如 FastAPI）但提取结果为空（0 个路由），终端会输出 `WARNING` 提醒你检查代码格式是否符合预期。这是正常的防护机制，避免 AI 基于不完整的分析结果工作。

**之后你就可以直接对话做事了。**

---

## 你能做什么（对话示例）

### 需求分析

```
你：我想给用户列表加一个批量导出功能，帮我分析一下
AI：（读取现有代码和项目上下文）
    现在系统已有单用户查询接口 GET /api/v1/users/{id}，
    但没有批量导出功能。建议：
    - 后端新增 POST /api/v1/exports/batch 接口
    - 前端在用户列表页增加导出按钮
    以下是详细的需求规格...
```

### 开发

```
你：按照刚才的规格，开始开发后端接口
AI：（基于现有代码结构和开发约定）
    正在开发 POST /api/v1/exports/batch 接口...
    已完成，运行测试验证...
    所有测试通过。
```

### 测试

```
你：这次改动影响了哪些功能？
AI：（搜索代码变更范围）
    影响范围：
    1. 新增了 /exports/batch 接口
    2. 修改了 ExportService
    3. 前端 UserList 页面新增了导出按钮
    建议测试：...
```

### 项目理解

```
你：帮我介绍一下这个项目的架构
AI：（读取 .egce/context/ 里的项目文档）
    这是一个前后端分离项目：
    - 后端：FastAPI + SQLModel，API 在 /api/v1/ 下
    - 前端：React + Zustand，使用 axios 调用后端
    ...
```

---

## 工作流程

```
产品经理描述需求（一句话就行）
    ↓
AI 分析现有代码 → 输出需求规格（精确到接口字段和页面交互）
    ↓
自动检查规格自包含性（前后端接口对齐、字段完整、测试用例齐全）
    ↓
人工审核规格（确认接口设计、业务逻辑是否正确）
    ↓
从规格自动生成测试骨架 → AI 先跑测试（全部失败）
    ↓
AI 按规格开发 → 后端前端自动对齐（因为接口已在规格中定义好）
    ↓
AI 运行测试验证 → 全部通过后更新项目文档
    ↓
提交代码（项目文档一起提交，新人可用）
```

---

## 前后端分离项目怎么用

前后端各自有自己的代码仓库，各自有自己的上下文：

```
工作区/
  backend/                  ← 后端仓库
    .egce/
      analysis/             ← 自动生成：API 路由、数据模型、模块结构
      context/              ← 人工维护：架构说明、接口契约、开发约定
  frontend/                 ← 前端仓库
    .egce/
      analysis/             ← 自动生成：页面路由、组件清单、API 调用、状态管理
      context/              ← 人工维护：架构说明、组件规范、开发约定
  .egce/
    workspace.yaml          ← 工作区配置
    specs/                  ← 需求规格（前后端共享）
```

**关键设计**：需求规格里同时定义了后端接口和前端交互，AI 开发时严格按规格执行，前后端天然对齐，不需要联调扯皮。

### 多前端仓库

如果你的项目有多个前端（管理端、商户端、支付端等），spec 按实际项目名分段：

```yaml
id: feature-refund
title: 商户退款功能
status: draft

tarspay:                    # 后端项目名（来自 workspace.yaml）
  tasks:
    - id: be-1
      title: 退款接口
      api:
        method: POST
        path: /api/v1/refunds

merchant:                   # 前端-商户端
  api_calls:
    - POST /api/v1/refunds
  testing:
    - 退款表单提交

manager:                    # 前端-管理端（不涉及则不写）
  api_calls:
    - POST /api/v1/refunds
  testing:
    - 退款列表展示
```

`egce spec validate` 会自动识别哪些是后端、哪些是前端（根据 workspace.yaml），分别做 API 完整性检查和前后端对齐检查。旧的 `backend`/`frontend` 格式仍然支持。

---

## 项目上下文（核心价值）

`.egce/context/` 目录下的文件是项目的核心知识资产，随代码一起提交到 Git：

| 文件 | 内容 | 谁维护 |
|---|---|---|
| architecture.md | 系统架构、技术选型、分层设计 | AI 初次生成，人审核修改 |
| modules.md | 各模块职责、边界、依赖关系 | 同上 |
| api-contracts.md | API 接口文档 | 同上 |
| data-models.md | 核心数据模型、字段、关系 | 同上 |
| conventions.md | 开发约定、命名规范、代码风格 | 同上 |
| components.md | 前端组件结构（仅前端项目） | 同上 |

**新人入职**：clone 代码 → 安装 EGCE → 打开 AI 工具 → 直接对话了解项目。所有知识都在仓库里，不在老员工脑子里。

---

## 支持的技术栈

### 代码扫描（通用）

Python, JavaScript, TypeScript, Go, Rust, Java

### 框架深度分析

| 框架 | 提取内容 |
|---|---|
| FastAPI | API 路由、参数、Pydantic/SQLModel 数据模型 |
| Django | URL 路由、ORM 模型 |
| Express | HTTP 路由、TypeScript 接口、Mongoose schema |
| React | 页面路由、组件、Props、API 调用、Redux/Zustand 状态管理 |
| Vue | 页面路由(含 Nuxt)、组件、API 调用、Pinia/Vuex 状态管理 |

**不在列表里的框架也能用**，只是没有深度提取（API 路由、数据模型）。基础的代码结构扫描对所有语言都有效。

---

## 可选配置：Claude Code MCP 集成

如果你使用 Claude Code，可以把 EGCE 注册为原生工具，获得更好的体验：

编辑 `~/.claude/settings.json`，添加：

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

重启 Claude Code 后，AI 可以直接调用 EGCE 工具，无需通过命令行。

---

## 所有命令速查

| 命令 | 作用 |
|---|---|
| `egce setup` | 首次安装后执行，配置 AI 工具的全局指令 |
| `egce init .` | 初始化项目，扫描代码，生成 .egce/ 目录 |
| `egce sync .` | 重新扫描，更新分析结果 |
| `egce sync . --check` | 检查项目文档是否过期 |
| `egce scan .` | 查看代码结构（文件树 + 函数签名） |
| `egce search "关键词" .` | 搜索相关代码 |
| `egce pipeline "任务描述" .` | 完整流程：搜索 → 压缩 → 打包上下文 |
| `egce verify .` | 运行测试和代码检查 |
| `egce spec list` | 查看所有需求规格 |
| `egce spec show <id>` | 查看某个规格详情 |
| `egce spec status <id> <状态>` | 更新规格状态 |
| `egce spec validate <id>` | 检查规格是否自包含（开发前必做） |
| `egce spec test <id>` | 从规格生成测试骨架代码 |
| `egce context list` | 查看项目上下文文件 |
| `egce context show <name>` | 查看某个上下文文件 |

所有命令支持 `--verbose / -v` 全局参数，开启后会输出详细的调试日志，方便排查问题。

注意：**一般情况下你不需要手动执行这些命令**，AI 会自动调用。列在这里是为了调试和了解。

---

## 质量保障机制

### Spec 自包含性检查

开发前 AI 会自动检查需求规格是否完整：

```
egce spec validate feature-export
```

检查内容：
- 必填字段是否齐全（id、title、status）
- 后端接口是否定义了请求方法、路径、请求体字段
- **前后端接口是否对齐**（前端调用的接口，后端是否有对应定义）
- 是否写了测试用例

如果检查不通过，AI 会先补全规格再开始开发。**不完整的规格 = 不完整的上下文 = AI 幻觉的来源。**

### 测试驱动开发（TDD）

从需求规格自动生成测试骨架：

```
egce spec test feature-export --output-dir tests/
```

- 后端：生成 pytest 测试文件，每个测试用例一个函数
- 前端：生成 Jest 测试文件，每个测试用例一个 it()

AI 开发时先跑测试（全部失败），再写代码让测试通过。**测试是验收标准，不是事后补的。**

### Context 过期检查

`egce verify` 会自动检查 `.egce/context/` 是否和实际代码一致：

```
egce verify .
# [PASS] pytest  (1.2s)
# [PASS] ruff check  (0.3s)
# [FAIL] egce sync --check  (0.8s)
#        2 stale context item(s)
```

检查内容：
- 新增的 API 路由是否出现在 `context/api-contracts.md`
- 新增的数据模型是否出现在 `context/data-models.md`
- 新增的代码目录是否出现在 `context/modules.md`

如果 context 文件还是模板占位符（未编辑），跳过检查。

**AI 改完代码跑 verify，context 过期就会被卡住，必须更新后才能通过。** 这确保了项目文档不会滞后于代码。

### 效果追踪

每次使用 pipeline 命令，自动记录：
- 检索了多少代码片段，用了多少 token
- 压缩效果（压缩前后的 token 数）
- 最终打包的 prompt 大小
- 各阶段耗时

数据存储在 `.egce/telemetry/`，可用于分析和优化。

---

## 实测数据

在 FastAPI 项目上测试（109,029 行代码）：

```
代码扫描：1,122 文件 → 提取 4,905 个函数/类签名、3,415 个 import 关系
框架分析：检测到 737 个 API 路由、230 个数据模型
上下文压缩：436,000 tokens 原始代码 → 8,042 tokens 打包后的 prompt（54 倍压缩）
耗时：初始化 ~3 秒
```

---

## 设计原则

1. **AI 不猜，基于证据** — 所有分析和开发都基于真实代码，不是凭空想象
2. **测试是裁判** — 代码写完跑测试，不是让 AI 自己说"我觉得对了"
3. **文档跟着代码走** — 项目知识存在仓库里，不丢失
4. **不碰你的代码** — EGCE 只读取和分析代码，所有修改由 AI 工具完成

---

## 问题反馈

GitHub Issues: https://github.com/mycodemanager/repo-context-engine/issues

## License

Apache-2.0
