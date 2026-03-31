"""Extractor framework — pluggable analysis for different tech stacks.

This package provides a registry of framework-specific extractors that can
pull structured information (API routes, data models, page routes, components,
state stores, infrastructure) from source code.

Architecture:
    Layer 1: tree-sitter AST          (already in repo_map.py)
    Layer 2: language-level extraction (classes, functions, imports)
    Layer 3: framework extractors      (this package — routes, models, etc.)
"""

from egce.extractors.base import (
    AnalysisResult,
    ComponentInfo,
    EnvVarInfo,
    FrameworkExtractor,
    InfraInfo,
    ModelFieldInfo,
    ModelInfo,
    PageRouteInfo,
    RouteInfo,
    StoreInfo,
    detect_frameworks,
    get_extractor,
    list_extractors,
    register_extractor,
    run_analysis,
)

__all__ = [
    "FrameworkExtractor",
    "RouteInfo",
    "ModelInfo",
    "ModelFieldInfo",
    "PageRouteInfo",
    "ComponentInfo",
    "StoreInfo",
    "InfraInfo",
    "EnvVarInfo",
    "AnalysisResult",
    "register_extractor",
    "detect_frameworks",
    "get_extractor",
    "list_extractors",
    "run_analysis",
]
