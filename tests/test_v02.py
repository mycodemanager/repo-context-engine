"""Tests for extractors, workspace init, spec management."""

from __future__ import annotations

import textwrap
from pathlib import Path


class TestExtractors:
    """Test framework extractors."""

    def test_fastapi_routes(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')
        (tmp_path / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/users")
            async def list_users():
                return []

            @app.post("/users")
            async def create_user(name: str, email: str):
                return {"id": 1}

            @app.get("/users/{user_id}")
            async def get_user(user_id: int):
                return {"id": user_id}
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert result.framework == "fastapi"
        assert len(result.routes) == 3

        methods = {r.method for r in result.routes}
        assert "GET" in methods
        assert "POST" in methods

        paths = {r.path for r in result.routes}
        assert "/users" in paths
        assert "/users/{user_id}" in paths

    def test_fastapi_models(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')
        (tmp_path / "models.py").write_text(textwrap.dedent("""\
            from pydantic import BaseModel
            from typing import Optional

            class User(BaseModel):
                name: str
                email: str
                age: Optional[int] = None

            class UserResponse(BaseModel):
                id: int
                name: str
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert len(result.models) == 2

        user = next(m for m in result.models if m.name == "User")
        assert len(user.fields) == 3
        assert user.fields[0].name == "name"
        assert user.fields[0].type == "str"
        assert user.fields[2].required is False  # Optional

    def test_express_routes(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"dependencies": {"express": "^4.0"}}')
        (tmp_path / "app.js").write_text(textwrap.dedent("""\
            const express = require("express");
            const app = express();

            app.get("/api/items", (req, res) => {
                res.json([]);
            });

            app.post("/api/items", (req, res) => {
                res.json({id: 1});
            });
        """))

        import egce.extractors.express_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert "express" in result.framework
        assert len(result.routes) == 2

    def test_react_components(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0"}}')
        (tmp_path / "App.tsx").write_text(textwrap.dedent("""\
            import React from "react";

            interface ButtonProps {
                label: string;
                onClick?: () => void;
            }

            function Button({ label, onClick }: ButtonProps) {
                return <button onClick={onClick}>{label}</button>;
            }

            export default function App() {
                return <div><Button label="Hello" /></div>;
            }
        """))

        import egce.extractors.react_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert result.project_type == "frontend"
        assert len(result.components) >= 2

        names = {c.name for c in result.components}
        assert "Button" in names
        assert "App" in names

    def test_react_api_calls(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0"}}')
        (tmp_path / "api.ts").write_text(textwrap.dedent("""\
            import axios from "axios";

            export const getUsers = () => axios.get("/api/users");
            export const createUser = (data) => axios.post("/api/users", data);
        """))

        import egce.extractors.react_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert len(result.api_calls) == 2
        methods = {c.method for c in result.api_calls}
        assert "GET" in methods
        assert "POST" in methods

    def test_vue_pages(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"dependencies": {"vue": "^3.0"}}')
        pages = tmp_path / "pages"
        pages.mkdir()
        (pages / "index.vue").write_text("<template><div>Home</div></template>")
        (pages / "about.vue").write_text("<template><div>About</div></template>")

        import egce.extractors.vue_ext  # noqa: F401
        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert result.project_type == "frontend"
        assert len(result.pages) >= 2

    def test_infra_detection(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yaml").write_text(textwrap.dedent("""\
            services:
              db:
                image: postgres:15
              cache:
                image: redis:7
              queue:
                image: rabbitmq:3
        """))

        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        infra_names = {i.name for i in result.infra}
        assert "PostgreSQL" in infra_names
        assert "Redis" in infra_names
        assert "RabbitMQ" in infra_names

    def test_env_vars(self, tmp_path: Path) -> None:
        (tmp_path / ".env.example").write_text(textwrap.dedent("""\
            DATABASE_URL=postgres://localhost/mydb
            REDIS_URL=redis://localhost:6379
            SECRET_KEY=change-me
        """))

        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert len(result.env_vars) == 3
        names = {e.name for e in result.env_vars}
        assert "DATABASE_URL" in names
        assert "SECRET_KEY" in names

    def test_unknown_framework_fallback(self, tmp_path: Path) -> None:
        """Unknown framework should still return a result with language detection."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname="foo"\n')
        (tmp_path / "main.py").write_text("def main(): pass\n")

        from egce.extractors.base import run_analysis

        result = run_analysis(tmp_path)
        assert result.language == "python"
        assert result.framework == ""  # no framework detected
        assert result.routes == []


class TestInit:
    """Test egce init."""

    def test_init_creates_structure(self, tmp_path: Path) -> None:
        """egce init should create .egce/ with analysis and context."""
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["fastapi"]\n')
        (tmp_path / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/health")
            def health():
                return {"ok": True}
        """))

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        stats = init_project(tmp_path)
        assert stats["files"] > 0
        assert stats["framework"] == "fastapi"

        # Check directory structure
        assert (tmp_path / ".egce").exists()
        assert (tmp_path / ".egce" / "config.yaml").exists()
        assert (tmp_path / ".egce" / "analysis" / "repo-map.txt").exists()
        assert (tmp_path / ".egce" / "analysis" / "api-routes.txt").exists()
        assert (tmp_path / ".egce" / "context" / "architecture.md").exists()
        assert (tmp_path / ".egce" / "context" / "conventions.md").exists()
        assert (tmp_path / ".egce" / "specs").exists()
        assert (tmp_path / "CLAUDE.md").exists()

        # Check api-routes.txt content
        routes = (tmp_path / ".egce" / "analysis" / "api-routes.txt").read_text()
        assert "GET /health" in routes

    def test_init_workspace(self, tmp_path: Path) -> None:
        """egce init on a workspace with multiple repos."""
        # Create two "repos"
        be = tmp_path / "backend"
        be.mkdir()
        (be / ".git").mkdir()
        (be / "pyproject.toml").write_text('[project]\ndependencies=["fastapi"]\n')
        (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / ".git").mkdir()
        (fe / "package.json").write_text('{"dependencies":{"react":"^18"}}')
        (fe / "App.tsx").write_text("export default function App() { return <div/>; }\n")

        import egce.extractors.fastapi_ext  # noqa: F401
        import egce.extractors.react_ext  # noqa: F401
        from egce.workspace import init_workspace

        result = init_workspace(tmp_path)
        assert result["workspace"] == tmp_path.name
        assert len(result["projects"]) == 2

        # workspace.yaml should exist
        assert (tmp_path / ".egce" / "workspace.yaml").exists()
        # Each project should have its own .egce/
        assert (be / ".egce" / "analysis" / "repo-map.txt").exists()
        assert (fe / ".egce" / "analysis" / "repo-map.txt").exists()


class TestSync:
    """Test egce sync."""

    def test_sync_updates_analysis(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
        (tmp_path / "main.py").write_text("def foo(): pass\n")

        from egce.workspace import init_project, sync_project

        init_project(tmp_path)

        # Add a new file
        (tmp_path / "new_module.py").write_text("def bar(): pass\n")

        result = sync_project(tmp_path)
        assert result["updated"]
        assert result["files"] >= 2

    def test_sync_check_only(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
        (tmp_path / "main.py").write_text("def foo(): pass\n")

        from egce.workspace import init_project, sync_project

        init_project(tmp_path)
        result = sync_project(tmp_path, check_only=True)
        assert not result["updated"]


class TestSpec:
    """Test spec management."""

    def test_spec_lifecycle(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / ".egce" / "specs"
        specs_dir.mkdir(parents=True)

        spec_content = textwrap.dedent("""\
            id: feature-export
            title: Batch Export
            status: draft
            description: Add batch export functionality

            backend:
              tasks:
                - id: be-1
                  title: Add export API
                  status: pending
        """)
        (specs_dir / "feature-export.yaml").write_text(spec_content)

        from egce.spec import list_specs, show_spec, update_spec_status

        # List
        specs = list_specs(tmp_path)
        assert len(specs) == 1
        assert specs[0]["id"] == "feature-export"
        assert specs[0]["status"] == "draft"

        # Show
        content = show_spec(tmp_path, "feature-export")
        assert content is not None
        assert "Batch Export" in content

        # Update status
        ok = update_spec_status(tmp_path, "feature-export", "approved")
        assert ok

        # Verify update
        specs = list_specs(tmp_path)
        assert specs[0]["status"] == "approved"

    def test_spec_not_found(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / ".egce" / "specs"
        specs_dir.mkdir(parents=True)

        from egce.spec import show_spec

        assert show_spec(tmp_path, "nonexistent") is None


class TestAnalysisRendering:
    """Test AnalysisResult rendering methods."""

    def test_render_routes(self) -> None:
        from egce.extractors.base import AnalysisResult, RouteInfo

        result = AnalysisResult(
            project_name="test", language="python",
            routes=[
                RouteInfo(method="GET", path="/users", file="api.py", line=10,
                          function_name="list_users", params=["limit: int"]),
                RouteInfo(method="POST", path="/users", file="api.py", line=20),
            ],
        )
        text = result.render_routes()
        assert "GET /users" in text
        assert "POST /users" in text
        assert "list_users" in text
        assert "limit: int" in text

    def test_render_models(self) -> None:
        from egce.extractors.base import AnalysisResult, ModelFieldInfo, ModelInfo

        result = AnalysisResult(
            project_name="test", language="python",
            models=[
                ModelInfo(name="User", file="models.py", line=5, kind="model",
                          base_class="BaseModel",
                          fields=[
                              ModelFieldInfo(name="name", type="str"),
                              ModelFieldInfo(name="email", type="str", required=False),
                          ]),
            ],
        )
        text = result.render_models()
        assert "User" in text
        assert "name: str" in text
        assert "(optional)" in text
