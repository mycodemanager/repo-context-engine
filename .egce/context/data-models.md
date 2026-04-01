# Data Models

EGCE 的核心数据结构定义在各模块中，没有集中的 ORM 层。

## repo_map.py

- **Symbol** — 单个符号（类/函数/方法），含 name、kind、line、signature、children
- **ImportEntry** — import 语句，含 module、names、line
- **FileInfo** — 文件解析结果，含 path、language、symbols、imports、lines
- **RepoMapResult** — 完整扫描结果，提供 to_text() 和 focused_text()

## retrieve.py

- **EvidenceChunk** — 检索到的代码片段，含 source_uri、start_line、end_line、content、symbols、score

## extractors/base.py

- **RouteInfo** — API 路由定义
- **ModelInfo** / **ModelFieldInfo** — 数据模型和字段
- **PageRouteInfo** — 前端页面路由
- **ComponentInfo** — 前端组件（含 props）
- **StoreInfo** — 状态管理 store
- **InfraInfo** — 基础设施依赖
- **EnvVarInfo** — 环境变量
- **AnalysisResult** — 完整分析结果，聚合所有提取信息

## spec.py

- **ValidationIssue** — 验证问题（error/warning）
- **ValidationResult** — 验证结果，含 passed/errors/warnings

## telemetry.py

- **PipelineTrace** — pipeline 调用记录（token 数、耗时）

## packer.py

- **Slot** — prompt 槽位（name、content、priority、budget_pct）
- **Priority** — LOW(10) / NORMAL(50) / HIGH(80) / CRITICAL(100)
