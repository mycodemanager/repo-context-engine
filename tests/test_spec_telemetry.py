"""Tests for spec validation, test generation, and telemetry."""

from __future__ import annotations

import textwrap
from pathlib import Path


class TestSpecValidation:
    """Test spec self-containment validation."""

    def _make_spec(self, tmp_path: Path, content: str) -> None:
        specs_dir = tmp_path / ".egce" / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "test-feature.yaml").write_text(content)

    def test_valid_spec_passes(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Test Feature
            status: draft

            backend:
              tasks:
                - id: be-1
                  title: Add endpoint
                  api:
                    method: POST
                    path: /api/v1/items
                    request:
                      body:
                        name: string

              testing:
                - POST /api/v1/items returns 201
                - Empty name returns 400

            frontend:
              api_calls:
                - POST /api/v1/items
              testing:
                - Form submits correctly
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert result.passed, result.to_text()

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            description: no id or title
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert not result.passed
        assert any("id" in i.message for i in result.errors)
        assert any("title" in i.message for i in result.errors)

    def test_frontend_backend_mismatch(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Test
            status: draft

            backend:
              tasks:
                - api:
                    method: GET
                    path: /api/v1/users

            frontend:
              api_calls:
                - POST /api/v1/orders
              testing:
                - Test something
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        # Should flag that frontend calls /api/v1/orders but backend doesn't have it
        assert any("orders" in i.message for i in result.issues)

    def test_no_testing_section_warns(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Test
            status: draft

            backend:
              tasks:
                - api:
                    method: GET
                    path: /api/v1/data
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert any("testing" in i.message.lower() for i in result.warnings)

    def test_validation_output_text(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Test
            status: draft
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        text = result.to_text()
        assert "test-feature" in text

    def test_multi_frontend_validation_passes(self, tmp_path: Path) -> None:
        """Spec with multiple frontend sections passes when APIs align."""
        # Create workspace.yaml so projects are recognized
        egce_dir = tmp_path / ".egce"
        egce_dir.mkdir()
        (egce_dir / "workspace.yaml").write_text(textwrap.dedent("""\
            workspace: test
            projects:
              - name: tarspay
                path: ./tarspay
                language: python
                framework: fastapi
              - name: manager
                path: ./manager
                language: javascript
                framework: react
              - name: merchant
                path: ./merchant
                language: javascript
                framework: vue
        """))

        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Multi Frontend Test
            status: draft

            tarspay:
              tasks:
                - id: be-1
                  api:
                    method: POST
                    path: /api/v1/refunds
                    request:
                      body:
                        order_id: string

              testing:
                - POST /api/v1/refunds creates a refund

            merchant:
              api_calls:
                - POST /api/v1/refunds
              testing:
                - Refund form submits correctly

            manager:
              api_calls:
                - POST /api/v1/refunds
              testing:
                - Refund list shows new entries
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert result.passed, result.to_text()

    def test_multi_frontend_alignment_error(self, tmp_path: Path) -> None:
        """Frontend section calling API that no backend defines should fail."""
        egce_dir = tmp_path / ".egce"
        egce_dir.mkdir()
        (egce_dir / "workspace.yaml").write_text(textwrap.dedent("""\
            workspace: test
            projects:
              - name: tarspay
                path: ./tarspay
                language: python
              - name: merchant
                path: ./merchant
                language: javascript
                framework: react
        """))

        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Alignment Error Test
            status: draft

            tarspay:
              tasks:
                - id: be-1
                  api:
                    method: GET
                    path: /api/v1/users

            merchant:
              api_calls:
                - POST /api/v1/payments
              testing:
                - Payment form works
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert any("payments" in i.message and "merchant" in i.message for i in result.issues)

    def test_backward_compatible_spec(self, tmp_path: Path) -> None:
        """Old-style backend/frontend spec still works without workspace.yaml."""
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: test-feature
            title: Legacy Format
            status: draft

            backend:
              tasks:
                - api:
                    method: GET
                    path: /api/v1/items

              testing:
                - GET /api/v1/items returns list

            frontend:
              api_calls:
                - GET /api/v1/items
              testing:
                - Items list renders
        """))

        from egce.spec import validate_spec

        result = validate_spec(tmp_path, "test-feature")
        assert result.passed, result.to_text()


class TestTestGeneration:
    """Test skeleton generation from specs."""

    def _make_spec(self, tmp_path: Path, content: str) -> None:
        specs_dir = tmp_path / ".egce" / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "batch-export.yaml").write_text(content)

    def test_generates_pytest_skeleton(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: batch-export
            title: Batch Export Feature

            backend:
              tasks:
                - id: be-1
                  api:
                    method: POST
                    path: /api/v1/exports/batch
              testing:
                - POST /api/v1/exports/batch with 10 IDs returns task_id
                - Empty ID list returns 400
                - Exceeding 1000 IDs returns 400
        """))

        from egce.spec import generate_test_skeleton

        files = generate_test_skeleton(tmp_path, "batch-export")
        assert len(files) >= 1

        # Should have a Python test file
        py_files = {k: v for k, v in files.items() if k.endswith(".py")}
        assert len(py_files) >= 1

        py_content = list(py_files.values())[0]
        assert "def test_" in py_content
        assert "Batch Export" in py_content
        assert "raise NotImplementedError" in py_content
        # Should have 3 test functions
        assert py_content.count("def test_") == 3

    def test_generates_jest_skeleton(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: batch-export
            title: Batch Export Feature

            frontend:
              testing:
                - Export button disabled when nothing selected
                - Export button enabled when items selected
                - Download starts after export completes
        """))

        from egce.spec import generate_test_skeleton

        files = generate_test_skeleton(tmp_path, "batch-export")
        ts_files = {k: v for k, v in files.items() if k.endswith(".ts")}
        assert len(ts_files) >= 1

        ts_content = list(ts_files.values())[0]
        assert "describe(" in ts_content
        assert 'it("' in ts_content
        assert ts_content.count('it("') == 3

    def test_no_tests_returns_empty(self, tmp_path: Path) -> None:
        self._make_spec(tmp_path, textwrap.dedent("""\
            id: batch-export
            title: No Tests Here

            backend:
              tasks:
                - id: be-1
                  title: Something
        """))

        from egce.spec import generate_test_skeleton

        files = generate_test_skeleton(tmp_path, "batch-export")
        assert len(files) == 0

    def test_multi_project_skeleton(self, tmp_path: Path) -> None:
        """Test skeleton generation for multi-project spec with workspace.yaml."""
        egce_dir = tmp_path / ".egce"
        egce_dir.mkdir()
        (egce_dir / "workspace.yaml").write_text(textwrap.dedent("""\
            workspace: test
            projects:
              - name: tarspay
                path: ./tarspay
                language: python
                framework: fastapi
              - name: merchant
                path: ./merchant
                language: javascript
                framework: vue
        """))
        specs_dir = egce_dir / "specs"
        specs_dir.mkdir()
        (specs_dir / "batch-export.yaml").write_text(textwrap.dedent("""\
            id: batch-export
            title: Batch Export Feature

            tarspay:
              tasks:
                - id: be-1
                  api:
                    method: POST
                    path: /api/v1/exports/batch
              testing:
                - POST returns task_id
                - Empty list returns 400

            merchant:
              testing:
                - Export button shows progress
                - Download completes
        """))

        from egce.spec import generate_test_skeleton

        files = generate_test_skeleton(tmp_path, "batch-export")

        # Should generate tarspay (pytest) and merchant (jest) files
        py_files = {k: v for k, v in files.items() if k.endswith(".py")}
        ts_files = {k: v for k, v in files.items() if k.endswith(".ts")}

        assert len(py_files) == 1
        assert len(ts_files) == 1
        assert "tarspay" in list(py_files.keys())[0]
        assert "merchant" in list(ts_files.keys())[0]

        # pytest file should have 2 test functions
        py_content = list(py_files.values())[0]
        assert py_content.count("def test_") == 2

        # jest file should have 2 it() blocks
        ts_content = list(ts_files.values())[0]
        assert ts_content.count('it("') == 2


class TestTelemetry:
    """Test pipeline telemetry tracking."""

    def test_save_and_load_trace(self, tmp_path: Path) -> None:
        (tmp_path / ".egce").mkdir()

        from egce.telemetry import Telemetry

        tel = Telemetry(tmp_path)
        trace = tel.start_trace("test task", str(tmp_path))
        trace.chunks_retrieved = 10
        trace.chunks_total_tokens = 2500
        trace.compressed_tokens = 1200
        trace.packed_tokens = 800
        trace.total_time_s = 1.5

        tel.save_trace(trace)

        # Load back
        traces = tel.load_traces()
        assert len(traces) == 1
        assert traces[0].chunks_retrieved == 10
        assert traces[0].packed_tokens == 800

    def test_summary(self, tmp_path: Path) -> None:
        (tmp_path / ".egce").mkdir()

        from egce.telemetry import Telemetry

        tel = Telemetry(tmp_path)

        # Save multiple traces
        for i in range(3):
            trace = tel.start_trace(f"task {i}", str(tmp_path))
            trace.total_input_tokens = 5000
            trace.packed_tokens = 2000
            trace.chunks_total_tokens = 3000
            trace.compressed_tokens = 1500
            trace.total_time_s = 1.0
            tel.save_trace(trace)

        summary = tel.summary()
        assert summary["total_runs"] == 3
        assert summary["total_packed_tokens"] == 6000
        assert summary["total_tokens_saved"] == 9000
        assert summary["avg_compression_ratio"] == 0.5

    def test_empty_summary(self, tmp_path: Path) -> None:
        (tmp_path / ".egce").mkdir()

        from egce.telemetry import Telemetry

        tel = Telemetry(tmp_path)
        summary = tel.summary()
        assert summary["total_runs"] == 0
