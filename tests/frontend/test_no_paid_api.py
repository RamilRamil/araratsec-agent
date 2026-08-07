"""No paid API is required for any surface, and the paid key never leaks
(feature 005, FR-016 / FR-021 / Constitution V).

The whole operator frontend must boot and answer on the local/relay backend with
no ANTHROPIC_API_KEY. If the operator DOES provide a paid key, it is held only in
memory and is never returned by the API — `public()` exposes `has_paid_key`, never
the secret. The paid backend is an explicit selection, never a silent fallback.
"""
from __future__ import annotations

import os

os.environ.setdefault("SR_SECRET_KEY", "00" * 32)
# Deliberately do NOT require a paid key — the surface must work without one.

import pytest
from fastapi.testclient import TestClient

from frontend.backend import model_config
from frontend.backend.app import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_config():
    yield
    model_config.CONFIG = model_config.ModelConfig()


# ── The paid key is write-only: set it, and it never comes back out ───────────

def test_paid_key_never_returned(client):
    r = client.post("/api/model/config", json={"backend": "paid", "paid_key": "sk-super-secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_paid_key"] is True
    assert "paid_key" not in body and "_paid_key" not in body
    assert "sk-super-secret" not in r.text

    r2 = client.get("/api/model/config")
    assert r2.status_code == 200
    assert "sk-super-secret" not in r2.text
    assert r2.json()["has_paid_key"] is True


def test_config_public_view_omits_secret():
    model_config.set_config(paid_key="sk-leak-me")
    pub = model_config.CONFIG.public()
    assert pub["has_paid_key"] is True
    assert "sk-leak-me" not in str(pub)


# ── Every read surface answers with NO paid key configured ────────────────────

def test_modules_surface_works_without_paid_key(client):
    r = client.get("/api/modules")
    assert r.status_code == 200
    body = r.json()
    assert body["active_pack"]  # the audit pack is wired
    assert body["kernel_invariants"]  # invariants are surfaced


def test_default_backend_is_local_not_paid(client):
    r = client.get("/api/model/config")
    assert r.json()["backend"] == "local"      # never defaults to the paid backend
    assert r.json()["has_paid_key"] is False


def test_backend_must_be_local_or_paid(client):
    r = client.post("/api/model/config", json={"backend": "nonsense"})
    assert r.status_code == 400


# ── Tunnel keep-alive indicator (US6) ─────────────────────────────────────────

def test_heartbeat_endpoint_shape(client):
    r = client.get("/api/model/heartbeat")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] in ("up", "down", "unknown")
    for key in ("endpoint", "model", "checked_at", "fails"):
        assert key in body


def test_heartbeat_ping_never_raises_and_marks_down_when_unreachable():
    # With no Ollama at the endpoint, one ping resolves to a clean "down".
    model_config.set_config(endpoint="http://127.0.0.1:1")  # nothing listens here
    state = model_config.heartbeat_once()
    assert state["state"] == "down"
    assert state["endpoint"] == "http://127.0.0.1:1"
