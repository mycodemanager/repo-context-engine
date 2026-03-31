"""Vue.js framework extractor — pages, components, API calls, state stores."""

from __future__ import annotations

import re
from pathlib import Path

from egce.extractors.base import (
    ApiCallInfo,
    ComponentInfo,
    FrameworkExtractor,
    PageRouteInfo,
    StoreInfo,
    register_extractor,
)

# Vue Router: { path: "/foo", component: Foo }
_VUE_ROUTE_RE = re.compile(
    r"path\s*:\s*[\"']([^\"']+)[\"']\s*,\s*(?:component|name)\s*:\s*[\"']?(\w+)"
)

# Nuxt file-based routing
# (same concept as Next.js — pages/ directory)

# defineComponent({ name: "Foo", props: {...} })
_DEFINE_COMP_RE = re.compile(r"defineComponent\s*\(\s*\{[^}]*name\s*:\s*[\"'](\w+)[\"']")

# <script setup> components are named by filename
# SFC component: export default { name: "..." }
_SFC_NAME_RE = re.compile(r"name\s*:\s*[\"'](\w+)[\"']")

# defineProps<{...}>() or defineProps({...})
_DEFINE_PROPS_RE = re.compile(r"defineProps\s*[<(]")

# Pinia store: defineStore("name", ...)
_PINIA_RE = re.compile(r"defineStore\s*\(\s*[\"'](\w+)[\"']")

# Vuex module: new Vuex.Store({...}) or store/index.js
_VUEX_RE = re.compile(r"(?:new\s+Vuex\.Store|createStore)\s*\(")

# API calls (same patterns as React)
_API_CALL_RE = re.compile(
    r"(?:axios|api|http|client|\$fetch|useFetch)\s*[\.(]\s*[\"'`]?(get|post|put|delete|patch)?[\"'`]?\s*[\(,]\s*[\"'`]([^\"'`]+)[\"'`]",
    re.IGNORECASE,
)


@register_extractor
class VueExtractor(FrameworkExtractor):
    name = "vue"
    language = "javascript"
    project_type = "frontend"
    detect_markers = [
        ("package.json", "vue"),
    ]

    def extract_pages(self, root: Path, files: dict[str, str]) -> list[PageRouteInfo]:
        pages: list[PageRouteInfo] = []

        # Method 1: Vue Router config
        for rel, content in files.items():
            if not rel.endswith((".js", ".ts")):
                continue
            if "router" not in rel.lower() and "routes" not in content.lower():
                continue
            for i, line in enumerate(content.splitlines()):
                m = _VUE_ROUTE_RE.search(line)
                if m:
                    pages.append(PageRouteInfo(
                        path=m.group(1),
                        component_file=rel,
                        component_name=m.group(2),
                        line=i + 1,
                    ))

        # Method 2: Nuxt file-based routing (pages/ directory)
        for rel in files:
            if rel.endswith(".vue") and ("pages/" in rel):
                route = _vue_file_to_route(rel)
                if route:
                    pages.append(PageRouteInfo(path=route, component_file=rel))

        return pages

    def extract_components(self, root: Path, files: dict[str, str]) -> list[ComponentInfo]:
        components: list[ComponentInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".vue", ".js", ".ts", ".jsx", ".tsx")):
                continue

            # SFC .vue files: component name = filename
            if rel.endswith(".vue"):
                name = Path(rel).stem
                # Check for PascalCase (likely a component)
                if name[0].isupper():
                    props = _extract_vue_props(content)
                    components.append(ComponentInfo(
                        name=name, file=rel, line=1, props=props,
                    ))
                continue

            # defineComponent
            m = _DEFINE_COMP_RE.search(content)
            if m:
                components.append(ComponentInfo(
                    name=m.group(1), file=rel, line=content[:m.start()].count("\n") + 1,
                ))

        return components

    def extract_api_calls(self, root: Path, files: dict[str, str]) -> list[ApiCallInfo]:
        calls: list[ApiCallInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".vue", ".js", ".ts", ".jsx", ".tsx")):
                continue
            for i, line in enumerate(content.splitlines()):
                m = _API_CALL_RE.search(line)
                if m:
                    method = (m.group(1) or "GET").upper()
                    path = m.group(2)
                    if path.startswith("/") or path.startswith("http"):
                        calls.append(ApiCallInfo(method=method, path=path, file=rel, line=i + 1))
        return calls

    def extract_stores(self, root: Path, files: dict[str, str]) -> list[StoreInfo]:
        stores: list[StoreInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".js", ".ts")):
                continue
            for i, line in enumerate(content.splitlines()):
                # Pinia
                m = _PINIA_RE.search(line)
                if m:
                    stores.append(StoreInfo(
                        name=m.group(1), file=rel, line=i + 1, kind="pinia",
                    ))
                    continue
                # Vuex
                m = _VUEX_RE.search(line)
                if m:
                    stores.append(StoreInfo(
                        name="root", file=rel, line=i + 1, kind="vuex",
                    ))
        return stores


def _vue_file_to_route(rel: str) -> str | None:
    """Convert Nuxt pages/ file path to route."""
    path = rel
    if path.startswith("src/"):
        path = path[4:]
    idx = path.find("pages/")
    if idx < 0:
        return None
    path = path[idx + 6:]
    if path.endswith(".vue"):
        path = path[:-4]
    if path.endswith("/index"):
        path = path[:-6]
    # Convert [param] or _param to :param
    path = re.sub(r"\[(\w+)\]", r":\1", path)
    path = re.sub(r"_(\w+)", r":\1", path)
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def _extract_vue_props(content: str) -> list[str]:
    """Extract props from a Vue SFC."""
    props: list[str] = []
    m = _DEFINE_PROPS_RE.search(content)
    if not m:
        return props
    # Simple extraction: find prop names in the next few lines
    start = content[:m.start()].count("\n")
    lines = content.splitlines()
    brace_depth = 0
    for i in range(start, min(start + 30, len(lines))):
        line = lines[i]
        brace_depth += line.count("{") + line.count("<") - line.count("}") - line.count(">")
        pm = re.match(r"\s+(\w+)(\??)\s*:\s*(.+?)\s*[;,]?\s*$", line)
        if pm:
            name = pm.group(1)
            optional = pm.group(2) == "?"
            ptype = pm.group(3).rstrip(";,").strip()
            mark = " (optional)" if optional else ""
            props.append(f"{name}: {ptype}{mark}")
        if brace_depth <= 0 and i > start + 1:
            break
    return props
