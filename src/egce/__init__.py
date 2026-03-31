"""EGCE - Evidence-Grounded Context Engine for large code repositories."""

from egce.compress import compress_chunks
from egce.packer import ContextPacker, Slot
from egce.repo_map import RepoMap
from egce.retrieve import EvidenceChunk, Retriever
from egce.verify import Verifier, VerifyResult

__all__ = [
    "RepoMap",
    "Retriever",
    "EvidenceChunk",
    "compress_chunks",
    "ContextPacker",
    "Slot",
    "Verifier",
    "VerifyResult",
]
__version__ = "0.1.0"
