"""Fetch a git-URL audit target into an isolated workspace (spec 021).

A cloned repo is untrusted TARGET DATA. Cloning FETCHES but never EXECUTES it:
shallow, single-branch, no submodules, hooks disabled. The workspace lives under a
controlled root OUTSIDE the agent repo (the session's external-only guard applies).

Private repos authenticate with a token that MUST NOT leak: it is never placed in
argv, the clone URL, or any log. The URL carries only a non-secret username
(`x-access-token`); the token is handed to git via GIT_ASKPASS (a mode-0700 helper
whose literal text references only `$SR_GIT_TOKEN` — the value lives only in the
child's environment). Uses the standard library only (git via subprocess — the
already-accepted benign pattern); no new package.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

_ALLOWED_SCHEMES = {"http", "https", "git"}
_ASKPASS_BODY = '#!/bin/sh\nprintf %s "$SR_GIT_TOKEN"\n'


class CloneError(Exception):
    """Invalid URL, authentication required with no token, or a failed clone."""


def validate_repo_url(url: str) -> str:
    """Accept only network git URLs (http/https/git with a host). Reject file://,
    bare local paths, ssh/git@ forms, and hostless URLs — so the URL field can't be
    used to read arbitrary local files."""
    if not url or not url.strip():
        raise CloneError("no repository URL provided")
    parts = urlsplit(url.strip())
    if parts.scheme not in _ALLOWED_SCHEMES or not parts.netloc:
        raise CloneError(
            f"unsupported repository URL: {url!r} — use an http(s) or git URL with a host"
        )
    return url.strip()


def _auth_url(url: str) -> str:
    """Insert a NON-secret username so git asks GIT_ASKPASS for the password."""
    parts = urlsplit(url)
    if parts.scheme in {"http", "https"} and "@" not in parts.netloc:
        return url.replace(f"{parts.scheme}://", f"{parts.scheme}://x-access-token@", 1)
    return url


def clone_repo(url: str, dest_root: Path, token: str = "") -> Path:
    """Shallow-clone `url` into `dest_root/<uuid>` and return that path.

    On failure removes the partial dir and raises `CloneError` with a token-free
    message. Never executes the target's code (hooks off, no submodules).
    """
    url = validate_repo_url(url)
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / str(uuid4())

    argv = [
        "git", "-c", "core.hooksPath=/dev/null",
        "clone", "--depth", "1", "--no-tags", "--single-branch",
    ]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    askpass: str | None = None
    if token:
        # Token goes to the child ENV only; the helper text references $SR_GIT_TOKEN,
        # never the value. URL gets a non-secret username. Nothing secret in argv.
        fd, askpass = tempfile.mkstemp(prefix="sr-askpass-")
        with os.fdopen(fd, "w") as fh:
            fh.write(_ASKPASS_BODY)
        os.chmod(askpass, 0o700)
        env["GIT_ASKPASS"] = askpass
        env["SR_GIT_TOKEN"] = token
        clone_url = _auth_url(url)
    else:
        clone_url = url
    argv += [clone_url, str(dest)]

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, env=env)  # noqa: S603
    except OSError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise CloneError(f"could not run git: {e}") from e
    finally:
        if askpass:
            os.unlink(askpass)

    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        err = (proc.stderr or "").strip()
        low = err.lower()
        if "authentication" in low or "could not read" in low or proc.returncode == 128:
            hint = "" if token else " (set GITHUB_TOKEN for a private repo)"
            raise CloneError(f"authentication required or repository not accessible{hint}")
        raise CloneError(f"git clone failed: {err[-300:]}")
    return dest
