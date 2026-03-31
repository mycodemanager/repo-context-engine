"""EGCE - Evidence-Grounded Context Engine for large code repositories."""

from egce.compress import compress_chunks
from egce.packer import ContextPacker, Slot, load_project_context
from egce.repo_map import RepoMap
from egce.retrieve import EvidenceChunk, Retriever, WorkspaceRetriever
from egce.verify import Verifier, VerifyResult

__all__ = [
    "RepoMap",
    "Retriever",
    "WorkspaceRetriever",
    "EvidenceChunk",
    "compress_chunks",
    "ContextPacker",
    "Slot",
    "load_project_context",
    "Verifier",
    "VerifyResult",
]
__version__ = "0.2.0"
