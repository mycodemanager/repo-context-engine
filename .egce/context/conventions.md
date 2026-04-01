# Development Conventions

## 语言和工具

- Python 3.9+（兼容用户环境，不用 3.10+ 特性）
- Ruff 做 lint（line-length=100）
- pytest 做测试
- tree-sitter 做代码解析
- tiktoken 做 token 计数

## 代码风格

- 使用 `from __future__ import annotations` 支持 3.9 的类型注解
- 模块内的辅助函数用 `_` 前缀标记为私有
- 每个模块顶部有 docstring 说明职责

## 新增模块的规范

- 框架提取器放 `src/egce/extractors/`，用 `@register_extractor` 注册
- 新提取器必须有 `name`、`language`、`project_type`、`detect_markers` 属性
- 新的 CLI 子命令在 `cli.py` 的 `main()` 中添加 argparse 定义和 dispatch

## 测试规范

- 测试文件按功能分组
- 使用 pytest 的 tmp_path fixture 创建临时项目
- 端到端测试创建带 `.git` 目录的模拟仓库

## 提交规范

- 每次提交前跑 `python3 -m ruff check src/ tests/` 和 `python3 -m pytest tests/ -q`
- 新功能必须有对应测试
- commit message 说明改了什么和为什么
