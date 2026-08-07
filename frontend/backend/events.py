"""In-process event bus (feature 005) — the loop's event_sink → WS clients.

Single-operator, in-memory. The loop's `event_sink` (sync) publishes TraceEvents;
WS handlers subscribe with an asyncio.Queue. Publish is non-blocking and never
raises into the loop (observability must not affect control flow).
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

# session_id → set of subscriber queues
_SUBS: dict[str, set[asyncio.Queue]] = defaultdict(set)
_LOOP: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Record the server event loop so the sync event_sink can hand events across."""
    global _LOOP
    _LOOP = loop


def subscribe(session_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _SUBS[session_id].add(q)
    return q


def unsubscribe(session_id: str, q: asyncio.Queue) -> None:
    _SUBS[session_id].discard(q)
    if not _SUBS[session_id]:
        _SUBS.pop(session_id, None)


def publish(session_id: str, event: dict) -> None:
    """Called from the loop's event_sink (sync, possibly off-thread). Fans the
    event to every subscriber's queue. Drops silently if there is no loop or the
    queue is full — a slow/absent observer must never stall the loop."""
    subs = _SUBS.get(session_id)
    if not subs or _LOOP is None:
        return

    def _fan() -> None:
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    try:
        _LOOP.call_soon_threadsafe(_fan)
    except RuntimeError:
        pass


def make_sink(session_id: str):
    """Build an event_sink callable bound to a session for OrchestratorLoop."""
    def sink(event: dict) -> None:
        publish(session_id, dict(event))
    return sink
