"""Compress — query-aware compression of retrieved code chunks.

Takes a list of EvidenceChunks and compresses them by:
1. Removing lines unlikely to be relevant to the query
2. Keeping structural elements (signatures, imports, error handling)
3. Collapsing contiguous removed lines into "[... N lines omitted]"
4. Preserving provenance (file path, line numbers)
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Sequence

from egce.retrieve import EvidenceChunk


# ---------------------------------------------------------------------------
# Line-level relevance signals
# ---------------------------------------------------------------------------

# Patterns for lines that are almost always worth keeping
_KEEP_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(def |class |async def )", re.IGNORECASE),  # signatures
    re.compile(r"^\s*(import |from .+ import )"),                # imports
    re.compile(r"^\s*(raise |except |finally:)"),                # error handling
    re.compile(r"^\s*(return |yield )"),                         # returns
    re.compile(r"^\s*@"),                                        # decorators
    re.compile(r"^\s*(if __name__|assert )"),                    # entry / assertions
    re.compile(r"#\s*(TODO|FIXME|HACK|BUG|XXX|NOTE)", re.IGNORECASE),  # important comments
    re.compile(r"^\s*(interface |struct |enum |type |func |fn |pub fn )"),  # multi-lang
]

# Patterns for lines that are safe to drop when under pressure
_DROP_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*#(?!\s*(TODO|FIXME|HACK|BUG|XXX|NOTE))"),  # generic comments
    re.compile(r"^\s*//(?!\s*(TODO|FIXME|HACK|BUG|XXX|NOTE))"), # C-style comments
    re.compile(r'^\s*"""'),                                      # docstring delimiters
    re.compile(r"^\s*'''"),
    re.compile(r"^\s*(pass|\.\.\.)\s*$"),                        # pass / ellipsis
    re.compile(r"^\s*$"),                                        # blank lines
    re.compile(r"^\s*(logger\.|logging\.|log\.)"),               # logging calls
    re.compile(r"^\s*print\("),                                  # debug prints
]


def _tokenize_simple(text: str) -> set[str]:
    """Extract lowercase word tokens from text."""
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()))


def _line_relevance(
    line: str,
    query_tokens: set[str],
    *,
    structural_bonus: float = 0.3,
    query_match_bonus: float = 0.4,
) -> float:
    """Score a single line's relevance (0.0 to 1.0)."""
    score = 0.0

    # Structural patterns always boost
    for pat in _KEEP_PATTERNS:
        if pat.search(line):
            score += structural_bonus
            break

    # Query term matches
    line_tokens = _tokenize_simple(line)
    overlap = line_tokens & query_tokens
    if overlap:
        score += query_match_bonus * (len(overlap) / max(len(query_tokens), 1))

    # Drop patterns penalize
    for pat in _DROP_PATTERNS:
        if pat.search(line):
            score -= 0.2
            break

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Compressor
# ---------------------------------------------------------------------------


def compress_chunks(
    chunks: Sequence[EvidenceChunk],
    query: str,
    *,
    target_ratio: float = 0.5,
    min_score: float = 0.1,
    context_lines: int = 1,
) -> list[EvidenceChunk]:
    """Compress a list of evidence chunks with query awareness.

    Parameters
    ----------
    chunks : evidence chunks to compress
    query : the user's query / task description
    target_ratio : target compression ratio (0.5 = keep ~50% of lines)
    min_score : lines below this relevance score are candidates for removal
    context_lines : keep N lines around every kept line for readability

    Returns
    -------
    New list of EvidenceChunks with compressed content.
    """
    query_tokens = _tokenize_simple(query)
    results: list[EvidenceChunk] = []

    for chunk in chunks:
        compressed = _compress_one(chunk, query_tokens, target_ratio, min_score, context_lines)
        results.append(compressed)

    return results


def _compress_one(
    chunk: EvidenceChunk,
    query_tokens: set[str],
    target_ratio: float,
    min_score: float,
    context_lines: int,
) -> EvidenceChunk:
    """Compress a single evidence chunk."""
    lines = chunk.content.splitlines()
    if len(lines) <= 5:
        # Too short to compress meaningfully
        return chunk

    # Score each line
    scores = [_line_relevance(line, query_tokens) for line in lines]

    # Determine how many lines to keep
    target_keep = max(3, int(len(lines) * target_ratio))

    # Mark which lines to keep
    keep = [False] * len(lines)

    # 1) Always keep lines above min_score
    for i, score in enumerate(scores):
        if score >= min_score:
            keep[i] = True

    # 2) Add context around kept lines
    if context_lines > 0:
        expanded = list(keep)
        for i, k in enumerate(keep):
            if k:
                for j in range(max(0, i - context_lines), min(len(lines), i + context_lines + 1)):
                    expanded[j] = True
        keep = expanded

    # 3) If we're keeping too many, raise the threshold
    kept_count = sum(keep)
    if kept_count > target_keep:
        # Sort by score, remove lowest until we hit target
        scored_indices = sorted(
            [(i, scores[i]) for i in range(len(lines)) if keep[i]],
            key=lambda x: x[1],
        )
        to_remove = kept_count - target_keep
        for idx, _ in scored_indices[:to_remove]:
            keep[idx] = False

    # 4) Build compressed output with omission markers
    output_lines: list[str] = []
    omitted_run = 0

    for i, line in enumerate(lines):
        if keep[i]:
            if omitted_run > 0:
                output_lines.append(f"    [...{omitted_run} lines omitted...]")
                omitted_run = 0
            output_lines.append(line)
        else:
            omitted_run += 1

    if omitted_run > 0:
        output_lines.append(f"    [...{omitted_run} lines omitted...]")

    compressed_content = "\n".join(output_lines)

    return replace(
        chunk,
        content=compressed_content,
    )
