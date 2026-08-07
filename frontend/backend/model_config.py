"""Runtime reasoning-backend config + warm (feature 005, US6/R8).

Per-process config the operator sets from the UI: the local-model endpoint
(localhost or a cloud-GPU tunnel), the model name, and an OPTIONAL paid key.
The paid backend is an EXPLICIT selection, never a silent fallback (FR-021). The
key is held only here (in memory), never returned by the API, never persisted,
never logged (Constitution V).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sr_agent.llm_core.gemini_client import SIMPLE_MODELS, GeminiClient
from sr_agent.llm_core.local_client import DEFAULT_HOST, LocalClient
from sr_agent.llm_core.openrouter_client import OPENROUTER_MODELS, OpenRouterClient
from audit_agent.config import config


@dataclass
class ModelConfig:
    endpoint: str = DEFAULT_HOST          # LocalClient(host=…) — localhost or a tunnel
    model: str | None = None              # None → for_stage2() (local) / SIMPLE_MODELS[0] (gemini)
    backend: str = "local"                # "local" | "paid" — EXPLICIT operator choice.
    # "paid" builds a GeminiClient — the only paid provider today (spec 018); the
    # UI labels it "Gemini". Kept as "paid" so the generic explicit-paid-selection
    # invariant (and its tests) stay intact.
    _paid_key: str | None = None          # UI Gemini key; overrides env; never returned/logged

    def public(self) -> dict:
        """Serializable view — the secret is write-only (only `has_paid_key`)."""
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "backend": self.backend,
            "has_paid_key": self._paid_key is not None,
        }

    def local_client(self) -> LocalClient:
        """Build a LocalClient from the current config (used to (re)build a
        session's provider so a config change takes effect next turn — FR-019)."""
        if self.model:
            return LocalClient(model=self.model, host=self.endpoint)
        return LocalClient.for_stage2(host=self.endpoint)

    def effective_gemini_key(self) -> str:
        """The key to use: the UI-provided one wins over the env key (spec 018)."""
        return self._paid_key or config.gemini_api_key

    def effective_openrouter_key(self) -> str:
        """OpenRouter key: UI-provided wins over the env key (spec 020)."""
        return self._paid_key or config.openrouter_api_key

    def reasoning_client(self) -> LocalClient | GeminiClient | OpenRouterClient:
        """The client the session's reasoning provider runs on. Branches on the
        EXPLICIT backend — never a silent fallback."""
        if self.backend == "paid":
            return GeminiClient(
                api_key=self.effective_gemini_key(),
                model=self.model or SIMPLE_MODELS[0],
            )
        if self.backend == "openrouter":
            return OpenRouterClient(
                api_key=self.effective_openrouter_key(),
                model=self.model or OPENROUTER_MODELS[0],
            )
        return self.local_client()

    def additional_client(self) -> LocalClient | GeminiClient | OpenRouterClient | None:
        """The ADDITIONAL-agent client consulted on escalation (spec 019), or None
        when the slot is off / unconfigured. `None` → escalation falls back to the
        file relay. A hosted method with no effective key is also unconfigured (no
        silent keyless call)."""
        if self.backend == "off":
            return None
        if self.backend == "paid":
            if not self.effective_gemini_key():
                return None
            return GeminiClient(api_key=self.effective_gemini_key(),
                                model=self.model or SIMPLE_MODELS[0])
        if self.backend == "openrouter":
            if not self.effective_openrouter_key():
                return None
            return OpenRouterClient(api_key=self.effective_openrouter_key(),
                                    model=self.model or OPENROUTER_MODELS[0])
        return self.local_client()


# Two process-wide slots for this single-operator surface (spec 019):
#   CONFIG     — the MAIN agent, serves every non-escalated turn (reasoning_client()).
#   ADDITIONAL — consulted automatically on escalation (additional_client());
#                "off" by default, so escalation falls back to the file relay.
# CONFIG keeps its name/behavior from spec 005/018 (its tests rebind it), so
# set_config below reads the LIVE module global rather than capturing it.
CONFIG = ModelConfig()
ADDITIONAL = ModelConfig(backend="off")


def _apply(cfg: ModelConfig, *, endpoint, model, backend, paid_key,
           allowed: tuple[str, ...]) -> dict:
    if endpoint is not None:
        cfg.endpoint = endpoint
    if model is not None:
        cfg.model = model or None
    if backend is not None:
        if backend not in allowed:
            raise ValueError(f"backend must be one of {allowed}")
        cfg.backend = backend
    if paid_key is not None:
        cfg._paid_key = paid_key or None
    return cfg.public()


def set_config(endpoint: str | None = None, model: str | None = None,
               backend: str | None = None, paid_key: str | None = None) -> dict:
    """Set the MAIN slot. Reads the live module-global CONFIG (its tests rebind it)."""
    return _apply(CONFIG, endpoint=endpoint, model=model, backend=backend,
                  paid_key=paid_key, allowed=("local", "paid", "openrouter"))


def set_additional(endpoint: str | None = None, model: str | None = None,
                   backend: str | None = None, paid_key: str | None = None) -> dict:
    """Set the ADDITIONAL slot — `backend="off"` disables it (relay fallback)."""
    return _apply(ADDITIONAL, endpoint=endpoint, model=model, backend=backend,
                  paid_key=paid_key, allowed=("local", "paid", "openrouter", "off"))


# ── Tunnel keep-alive + liveness indicator (US6) ─────────────────────────────
# A light periodic ping keeps a cloudflared quick tunnel's connection from idling
# out (~60-100s idle timeout — roadmap gotcha #11) and feeds the live UI dot.
_HEARTBEAT: dict = {"state": "unknown", "endpoint": None, "model": None, "checked_at": None, "fails": 0}


def heartbeat_once() -> dict:
    """One light liveness ping (GET /api/tags) against the current endpoint. Keeps
    the tunnel connection warm and refreshes the indicator state. Never raises."""
    client = CONFIG.local_client()
    try:
        ok = client.available()
    except Exception:
        ok = False
    _HEARTBEAT["endpoint"] = CONFIG.endpoint
    _HEARTBEAT["model"] = client.model
    _HEARTBEAT["checked_at"] = time.time()
    if ok:
        _HEARTBEAT.update(state="up", fails=0)
    else:
        _HEARTBEAT["fails"] = _HEARTBEAT.get("fails", 0) + 1
        _HEARTBEAT["state"] = "down"
    return dict(_HEARTBEAT)


def heartbeat_state() -> dict:
    """The last observed liveness (cheap read — no tunnel traffic)."""
    s = dict(_HEARTBEAT)
    if s.get("checked_at") is not None:
        s["age_s"] = round(time.time() - s["checked_at"], 1)
    return s


def warm() -> dict:
    """Load the model and report state — distinguishes ready from reachable (FR-020).

    Reads the SAME readiness the health projection uses (single source, A2).
    """
    client = CONFIG.local_client()
    start = time.monotonic()
    loaded = client.warm()
    ready = client.ready() if loaded else False
    elapsed = round(time.monotonic() - start, 1)
    if ready:
        state, reason = "ready", None
    elif loaded:
        state, reason = "warming", "loaded but not ready yet"
    else:
        state, reason = "failed", "could not reach/load the model (is Ollama up at the endpoint?)"
    return {"state": state, "reason": reason, "model": client.model, "elapsed_s": elapsed}
