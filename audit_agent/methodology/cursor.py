"""Deterministic discovery chunks (FR-013 / R5)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sr_agent.memory.canonical import canonical_bytes

CHUNK_SIZE = 32


def chunk_id_for(roadmap_revision: int, relpaths: Sequence[str]) -> str:
    """SHA-256 hex of the canonical {roadmap_revision, sorted relative paths}."""
    payload = {
        "roadmap_revision": int(roadmap_revision),
        "paths": sorted(str(p).replace("\\", "/") for p in relpaths),
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def partition_chunks(
    relpaths: Sequence[str],
    roadmap_revision: int = 0,
    *,
    size: int = CHUNK_SIZE,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return (chunk_id, paths) pairs. Same listing + revision => same sequence."""
    ordered = tuple(sorted(str(p).replace("\\", "/") for p in relpaths))
    out: list[tuple[str, tuple[str, ...]]] = []
    for i in range(0, len(ordered), size):
        group = ordered[i : i + size]
        out.append((chunk_id_for(roadmap_revision, group), group))
    return tuple(out)


def first_uncommitted_chunk(
    relpaths: Sequence[str],
    committed_chunk_ids: Sequence[str],
    roadmap_revision: int = 0,
) -> tuple[str, tuple[str, ...]] | None:
    committed = set(committed_chunk_ids)
    for cid, group in partition_chunks(relpaths, roadmap_revision):
        if cid not in committed:
            return cid, group
    return None
