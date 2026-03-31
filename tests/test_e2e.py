"""End-to-end integration test: workspace with frontend + backend."""

from __future__ import annotations

import textwrap
from pathlib import Path


class TestE2EWorkspace:
    """Full pipeline test on a minimal frontend + backend workspace."""

    def _setup_workspace(self, tmp_path: Path) -> Path:
        """Create a minimal FastAPI + React workspace."""
        # Backend
        be = tmp_path / "backend"
        be.mkdir()
        (be / ".git").mkdir()
        (be / "pyproject.toml").write_text('[project]\ndependencies=["fastapi","sqlmodel"]\n')
        (be / "main.py").write_text(textwrap.dedent("""\
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/api/v1/users")
            async def list_users(skip: int = 0, limit: int = 20):
                return []

            @app.post("/api/v1/users")
            async def create_user(name: str, email: str):
                return {"id": 1, "name": name, "email": email}
        """))
        (be / "models.py").write_text(textwrap.dedent("""\
            from pydantic import BaseModel

            class User(BaseModel):
                id: int
                name: str
                email: str
        """))
        (be / ".env.example").write_text("DATABASE_URL=sqlite:///./app.db\nSECRET_KEY=xxx\n")

        # Frontend
        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / ".git").mkdir()
        (fe / "package.json").write_text('{"dependencies":{"react":"^18","axios":"^1","zustand":"^4"}}')

        src = fe / "src"
        src.mkdir()
        (src / "App.tsx").write_text(textwrap.dedent("""\
            import React from "react";
            export default function App() { return <div>Hello</div>; }
        """))
        services = src / "services"
        services.mkdir()
        (services / "userApi.ts").write_text(textwrap.dedent("""\
            import axios from "axios";
            export const getUsers = () => axios.get("/api/v1/users");
            export const createUser = (data: any) => axios.post("/api/v1/users", data);
        """))
        stores = src / "stores"
        stores.mkdir()
        (stores / "userStore.ts").write_text(textwrap.dedent("""\
            import { create } from "zustand";
            export const useUserStore = create((set) => ({
                users: [],
                fetchUsers: async () => {},
            }));
        """))

        return tmp_path

    def test_workspace_init_and_structure(self, tmp_path: Path) -> None:
        """egce init on workspace creates .egce/ in both projects."""
        ws = self._setup_workspace(tmp_path)

        import egce.extractors.fastapi_ext  # noqa: F401
        import egce.extractors.react_ext  # noqa: F401
        from egce.workspace import init_workspace

        result = init_workspace(ws)
        assert len(result["projects"]) == 2

        be_stats = next(p for p in result["projects"] if p["project"] == "backend")
        fe_stats = next(p for p in result["projects"] if p["project"] == "frontend")

        assert be_stats["framework"] == "fastapi"
        assert be_stats["routes"] >= 2
        assert be_stats["models"] >= 1

        assert fe_stats["project_type"] == "frontend"
        assert fe_stats["components"] >= 1

        # Check files exist
        assert (ws / "backend" / ".egce" / "analysis" / "api-routes.txt").exists()
        assert (ws / "frontend" / ".egce" / "analysis" / "components.txt").exists()
        assert (ws / ".egce" / "workspace.yaml").exists()

    def test_workspace_retriever(self, tmp_path: Path) -> None:
        """WorkspaceRetriever searches across both projects."""
        ws = self._setup_workspace(tmp_path)

        import egce.extractors.fastapi_ext  # noqa: F401
        import egce.extractors.react_ext  # noqa: F401
        from egce.workspace import init_workspace
        from egce.retrieve import WorkspaceRetriever

        init_workspace(ws)

        wr = WorkspaceRetriever.from_workspace(ws)
        wr.index()
        chunks = wr.search("users api create", top_k=10)

        assert len(chunks) > 0
        # Results should have project prefix
        all_uris = [c.source_uri for c in chunks]
        has_backend = any(u.startswith("backend:") for u in all_uris)
        has_frontend = any(u.startswith("frontend:") for u in all_uris)
        assert has_backend, f"Expected backend results, got: {all_uris}"
        assert has_frontend, f"Expected frontend results, got: {all_uris}"

    def test_context_auto_load(self, tmp_path: Path) -> None:
        """Pipeline auto-loads .egce/context/ into packer."""
        ws = self._setup_workspace(tmp_path)

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        be = ws / "backend"
        init_project(be)

        # Write context
        ctx = be / ".egce" / "context" / "architecture.md"
        ctx.write_text("# Architecture\n\nFastAPI backend with SQLModel ORM.\n")

        from egce.packer import ContextPacker, load_project_context

        packer = ContextPacker(token_budget=8000)
        load_project_context(packer, str(be))

        slot = packer.get_slot("project_context")
        assert slot is not None
        assert slot.content  # not empty
        assert "FastAPI backend" in slot.content

    def test_spec_in_workspace(self, tmp_path: Path) -> None:
        """Specs at workspace level are loaded into packer."""
        ws = self._setup_workspace(tmp_path)

        import egce.extractors.fastapi_ext  # noqa: F401
        import egce.extractors.react_ext  # noqa: F401
        from egce.workspace import init_workspace

        init_workspace(ws)

        # Create a spec at workspace level
        spec = ws / ".egce" / "specs" / "feature-export.yaml"
        spec.write_text(textwrap.dedent("""\
            id: feature-export
            title: Batch Export
            status: approved
            backend:
              tasks:
                - id: be-1
                  title: Add export endpoint
        """))

        from egce.packer import ContextPacker, load_project_context

        packer = ContextPacker(token_budget=8000)
        load_project_context(packer, str(ws))

        slot = packer.get_slot("spec")
        assert slot is not None
        assert "Batch Export" in slot.content

    def test_full_pipeline_with_context(self, tmp_path: Path) -> None:
        """End-to-end: init → write context → pipeline → verify context loaded."""
        ws = self._setup_workspace(tmp_path)

        import egce.extractors.fastapi_ext  # noqa: F401
        from egce.workspace import init_project

        be = ws / "backend"
        init_project(be)

        # Simulate AI writing context
        (be / ".egce" / "context" / "api-contracts.md").write_text(
            "# API Contracts\n\n- GET /api/v1/users — list users\n- POST /api/v1/users — create user\n"
        )

        # Run pipeline
        from egce.compress import compress_chunks
        from egce.packer import ContextPacker, Priority, count_tokens, load_project_context
        from egce.retrieve import Retriever

        retriever = Retriever(str(be))
        retriever.index()
        chunks = retriever.search("create user endpoint", top_k=5)
        assert len(chunks) > 0

        compressed = compress_chunks(chunks, "create user endpoint")

        packer = ContextPacker(token_budget=8000)
        load_project_context(packer, str(be))
        packer.set_slot("task", "Add email validation to create user endpoint", priority=Priority.HIGH)
        packer.set_slot("evidence", "\n\n".join(c.to_text() for c in compressed))

        prompt = packer.build()

        # Verify the prompt contains both context and evidence
        assert "API Contracts" in prompt
        assert "create user" in prompt.lower()
        assert count_tokens(prompt) <= 8000
