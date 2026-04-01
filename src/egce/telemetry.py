"""Telemetry — track token usage, compression stats, and pipeline performance.

Records each pipeline invocation to .egce/telemetry/ as JSONL files.
Provides summary reports for cost analysis and optimization.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PipelineTrace:
    """A single pipeline invocation record."""

    timestamp: str = ""
    task: str = ""
    repo: str = ""

    # Retrieval stats
    chunks_retrieved: int = 0
    chunks_total_tokens: int = 0

    # Compression stats
    chunks_after_compression: int = 0
    compressed_tokens: int = 0
    compression_ratio: float = 0.0

    # Context loading
    project_context_tokens: int = 0
    spec_tokens: int = 0
    repo_map_tokens: int = 0

    # Packing
    total_input_tokens: int = 0
    packed_tokens: int = 0
    token_budget: int = 0
    over_budget: int = 0

    # Timing
    index_time_s: float = 0.0
    search_time_s: float = 0.0
    compress_time_s: float = 0.0
    pack_time_s: float = 0.0
    total_time_s: float = 0.0


class Telemetry:
    """Track and store pipeline execution metrics.

    Usage::

        tel = Telemetry("/path/to/project")
        trace = tel.start_trace("fix the login bug", "/path/to/project")
        trace.chunks_retrieved = 10
        trace.chunks_total_tokens = 2500
        # ... fill in metrics during pipeline execution
        tel.save_trace(trace)
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._telemetry_dir = self._find_telemetry_dir()

    def _find_telemetry_dir(self) -> Path:
        """Find or create the telemetry directory."""
        # Check workspace level first
        ws_dir = self.root / ".egce" / "telemetry"
        if (self.root / ".egce").exists():
            ws_dir.mkdir(parents=True, exist_ok=True)
            return ws_dir
        # Check parent (workspace root)
        parent_dir = self.root.parent / ".egce" / "telemetry"
        if (self.root.parent / ".egce").exists():
            parent_dir.mkdir(parents=True, exist_ok=True)
            return parent_dir
        # Fallback: create in project
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir

    def start_trace(self, task: str, repo: str) -> PipelineTrace:
        """Create a new trace with timestamp."""
        return PipelineTrace(
            timestamp=datetime.now().isoformat(),
            task=task,
            repo=repo,
        )

    def save_trace(self, trace: PipelineTrace) -> Path:
        """Append a trace to the JSONL log file."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self._telemetry_dir / f"pipeline-{today}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(trace), ensure_ascii=False) + "\n")
        return log_file

    def load_traces(self, days: int = 7) -> list[PipelineTrace]:
        """Load recent traces."""
        traces: list[PipelineTrace] = []
        if not self._telemetry_dir.exists():
            return traces

        for f in sorted(self._telemetry_dir.glob("pipeline-*.jsonl"), reverse=True):
            try:
                for line in f.read_text().splitlines():
                    if line.strip():
                        data = json.loads(line)
                        traces.append(PipelineTrace(**data))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if len(traces) >= days * 50:  # rough limit
                break

        return traces

    def summary(self, days: int = 7) -> dict:
        """Generate a summary report of recent pipeline usage."""
        traces = self.load_traces(days)
        if not traces:
            return {"total_runs": 0}

        total_input = sum(t.total_input_tokens for t in traces)
        total_packed = sum(t.packed_tokens for t in traces)
        total_retrieved = sum(t.chunks_total_tokens for t in traces)
        total_compressed = sum(t.compressed_tokens for t in traces)
        total_time = sum(t.total_time_s for t in traces)

        avg_compression = (
            total_compressed / total_retrieved if total_retrieved else 0
        )

        return {
            "total_runs": len(traces),
            "total_input_tokens": total_input,
            "total_packed_tokens": total_packed,
            "total_tokens_saved": total_input - total_packed,
            "avg_compression_ratio": round(avg_compression, 3),
            "avg_packed_tokens": round(total_packed / len(traces)),
            "avg_time_s": round(total_time / len(traces), 2),
            "total_time_s": round(total_time, 2),
        }
