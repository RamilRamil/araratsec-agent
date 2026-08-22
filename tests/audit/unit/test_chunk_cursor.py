"""Deterministic chunk identity (FR-013)."""
from __future__ import annotations

import os
import time

from audit_agent.methodology.cursor import chunk_id_for, partition_chunks


def test_same_listing_same_chunk_ids():
    files = [f"contracts/C{i:02d}.sol" for i in range(40)]
    first = partition_chunks(files, roadmap_revision=1)
    time.sleep(0.01)
    os.getpid()
    second = partition_chunks(files, roadmap_revision=1)
    assert first == second
    assert len(first) == 2
    assert first[0][0] == chunk_id_for(1, files[:32])
    assert all(len(cid) == 64 for cid, _ in first)
