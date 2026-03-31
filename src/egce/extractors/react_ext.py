"""React framework extractor — pages, components, API calls, state stores."""

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

# React Router: <Route path="/foo" component={Foo} /> or element={<Foo/>}
_ROUTE_JSX_RE = re.compile(
    r"<Route\s+[^>]*path\s*=\s*[\"']([^\"']+)[\"'][^>]*(?:component\s*=\s*\{(\w+)\}|element\s*=\s*\{?\s*<(\w+))",
)

# Next.js style: files in pages/ or app/ directory = routes
# (detected by file path convention)

# Component definition: function Foo(...) or const Foo = (...) => or class Foo extends Component
_FUNC_COMP_RE = re.compile(r"(?:export\s+(?:default\s+)?)?function\s+([A-Z]\w+)\s*\(([^)]*)\)")
_ARROW_COMP_RE = re.compile(r"(?:export\s+(?:default\s+)?)?const\s+([A-Z]\w+)\s*(?::\s*\w+\s*)?=\s*(?:\([^)]*\)|[^=])\s*=>")
_CLASS_COMP_RE = re.compile(r"class\s+([A-Z]\w+)\s+extends\s+(?:React\.)?(?:Component|PureComponent)")

# Props interface: interface FooProps { ... } or type FooProps = { ... }
_PROPS_RE = re.compile(r"(?:interface|type)\s+(\w+Props)\s*[={]")

# API calls: axios.get("/foo"), fetch("/foo"), api.post("/foo")
_API_CALL_RE = re.compile(
    r"(?:axios|api|http|client|fetch)\s*[\.(]\s*[\"'`]?(get|post|put|delete|patch)?[\"'`]?\s*[\(,]\s*[\"'`]([^\"'`]+)[\"'`]",
    re.IGNORECASE,
)
_FETCH_RE = re.compile(r"fetch\s*\(\s*[\"'`]([^\"'`]+)[\"'`]")

# Zustand: create((set) => ({ ... }))
_ZUSTAND_RE = re.compile(r"(?:export\s+)?const\s+(\w+)\s*=\s*create\s*[(<]")

# Redux toolkit: createSlice({ name: "foo" })
_REDUX_SLICE_RE = re.compile(r"createSlice\s*\(\s*\{[^}]*name\s*:\s*[\"'](\w+)[\"']")


@register_extractor
class ReactExtractor(FrameworkExtractor):
    name = "react"
    language = "javascript"
    project_type = "frontend"
    detect_markers = [
        ("package.json", "react"),
    ]

    def extract_pages(self, root: Path, files: dict[str, str]) -> list[PageRouteInfo]:
        pages: list[PageRouteInfo] = []

        # Method 1: React Router JSX routes
        for rel, content in files.items():
            if not rel.endswith((".jsx", ".tsx", ".js", ".ts")):
                continue
            for i, line in enumerate(content.splitlines()):
                m = _ROUTE_JSX_RE.search(line)
                if m:
                    path = m.group(1)
                    comp = m.group(2) or m.group(3) or ""
                    pages.append(PageRouteInfo(
                        path=path, component_file=rel,
                        component_name=comp, line=i + 1,
                    ))

        # Method 2: Next.js file-based routing (pages/ or app/ directory)
        for rel in files:
            if not rel.endswith((".jsx", ".tsx", ".js", ".ts")):
                continue
            if rel.startswith("pages/") or rel.startswith("src/pages/"):
                route = _file_to_route(rel, "pages/")
                if route:
                    pages.append(PageRouteInfo(path=route, component_file=rel))
            elif rel.startswith("app/") or rel.startswith("src/app/"):
                if "/page." in rel:
                    route = _file_to_route(rel, "app/")
                    if route:
                        pages.append(PageRouteInfo(path=route, component_file=rel))

        return pages

    def extract_components(self, root: Path, files: dict[str, str]) -> list[ComponentInfo]:
        components: list[ComponentInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".jsx", ".tsx", ".js", ".ts")):
                continue
            lines = content.splitlines()
            full = content

            # Find component definitions
            for pattern in [_FUNC_COMP_RE, _ARROW_COMP_RE, _CLASS_COMP_RE]:
                for m in pattern.finditer(full):
                    name = m.group(1)
                    # Find line number
                    pos = m.start()
                    line_num = full[:pos].count("\n") + 1

                    props: list[str] = []
                    # Try to find Props interface
                    props_name = f"{name}Props"
                    pm = re.search(rf"(?:interface|type)\s+{props_name}\s*[={{]", full)
                    if pm:
                        props = _extract_props(lines, full[:pm.start()].count("\n") + 1)

                    components.append(ComponentInfo(
                        name=name, file=rel, line=line_num, props=props,
                    ))

        return components

    def extract_api_calls(self, root: Path, files: dict[str, str]) -> list[ApiCallInfo]:
        calls: list[ApiCallInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".jsx", ".tsx", ".js", ".ts")):
                continue
            for i, line in enumerate(content.splitlines()):
                # axios/api style
                m = _API_CALL_RE.search(line)
                if m:
                    method = (m.group(1) or "GET").upper()
                    path = m.group(2)
                    if path.startswith("/") or path.startswith("http"):
                        calls.append(ApiCallInfo(method=method, path=path, file=rel, line=i + 1))
                    continue
                # fetch() style
                m = _FETCH_RE.search(line)
                if m:
                    path = m.group(1)
                    if path.startswith("/") or path.startswith("http"):
                        method = "POST" if "method" in line and ("POST" in line or "post" in line) else "GET"
                        calls.append(ApiCallInfo(method=method, path=path, file=rel, line=i + 1))

        return calls

    def extract_stores(self, root: Path, files: dict[str, str]) -> list[StoreInfo]:
        stores: list[StoreInfo] = []
        for rel, content in files.items():
            if not rel.endswith((".js", ".ts", ".jsx", ".tsx")):
                continue
            for i, line in enumerate(content.splitlines()):
                # Zustand
                m = _ZUSTAND_RE.search(line)
                if m:
                    stores.append(StoreInfo(
                        name=m.group(1), file=rel, line=i + 1, kind="zustand",
                    ))
                    continue
                # Redux toolkit
                m = _REDUX_SLICE_RE.search(line)
                if m:
                    stores.append(StoreInfo(
                        name=m.group(1), file=rel, line=i + 1, kind="redux",
                    ))

        return stores


def _file_to_route(rel: str, prefix: str) -> str | None:
    """Convert a file-based route path to a URL path."""
    # Remove prefix (pages/ or app/) and src/ prefix
    path = rel
    if path.startswith("src/"):
        path = path[4:]
    idx = path.find(prefix)
    if idx < 0:
        return None
    path = path[idx + len(prefix):]
    # Remove file extension
    for ext in (".tsx", ".jsx", ".ts", ".js"):
        if path.endswith(ext):
            path = path[: -len(ext)]
    # Remove /index and /page suffixes
    if path.endswith("/index"):
        path = path[:-6]
    if path.endswith("/page"):
        path = path[:-5]
    # Convert [param] to :param
    path = re.sub(r"\[(\w+)\]", r":\1", path)
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def _extract_props(lines: list[str], start: int) -> list[str]:
    """Extract props from interface/type definition."""
    props: list[str] = []
    brace_depth = 0
    for i in range(start, min(start + 30, len(lines))):
        line = lines[i]
        brace_depth += line.count("{") - line.count("}")
        m = re.match(r"\s+(\w+)(\??)\s*:\s*(.+?)\s*;?\s*$", line)
        if m:
            name = m.group(1)
            optional = m.group(2) == "?"
            ptype = m.group(3).rstrip(";").strip()
            mark = " (optional)" if optional else ""
            props.append(f"{name}: {ptype}{mark}")
        if brace_depth <= 0 and i > start:
            break
    return props
