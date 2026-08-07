"""Session management (feature 005, US1).

Builds an OrchestratorLoop per chat session — the SAME wiring as cli.py's chat
command (pack=AUDIT_PACK, ChatReasoningProvider over a LocalClient) — plus the
event_sink so the live trace streams to the WS. A provider factory can be
overridden (tests inject a fake provider so a turn can be driven without Ollama).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from sr_agent.llm_core.chat_reasoning import ChatReasoningProvider
from sr_agent.llm_core.router import ModelRouter
from audit_agent.config import config
from sr_agent.memory.episodic import EpisodicMemory
from sr_agent.models.chat import ChatSession
from sr_agent.models.principal import Principal
from sr_agent.orchestrator.chat_session import save_session
from sr_agent.orchestrator.loop import OrchestratorLoop
from audit_agent.escalation import domain_escalation
from audit_agent.pack import AUDIT_PACK
from audit_agent.reasoning import AUDIT_CHAT_SYSTEM, signal_from
from audit_agent.session import AuditInput, AuditSession

from frontend.backend import events
from frontend.backend.clone import CloneError, clone_repo, validate_repo_url
from frontend.backend.model_config import ADDITIONAL, CONFIG

# Test seam: override to inject a fake reasoning provider (drive a turn w/o Ollama).
provider_factory: Callable[[], object] | None = None

# The agent's own repo root (…/frontend/backend/sessions.py → repo root). A session
# is never allowed to be scoped here — the audited target stays strictly external.
_AGENT_ROOT = Path(__file__).resolve().parents[2]

# Max chars of an audit report folded into session grounding (spec 019). Bounds
# how much a large report can crowd the context; build_messages drops lowest-
# priority content first, and the report is truncated with an explicit marker.
REPORT_BUDGET_CHARS = 12_000


def _read_report(audit_path: str) -> str:
    """Read an EXTERNAL audit-report file, budgeted. Raises ValueError on a bad path
    (missing / not a file / inside the agent repo — target material stays external)."""
    p = Path(audit_path).expanduser()
    if not p.is_file():
        raise ValueError(f"audit path is not an existing file: {audit_path}")
    resolved = p.resolve()
    if resolved == _AGENT_ROOT or _AGENT_ROOT in resolved.parents:
        raise ValueError("audit file must be EXTERNAL, not inside the agent repo")
    text = resolved.read_text(encoding="utf-8", errors="replace")
    if len(text) > REPORT_BUDGET_CHARS:
        text = text[:REPORT_BUDGET_CHARS] + "\n…[report truncated]…"
    return text


class Session:
    def __init__(self, chat: ChatSession, loop: OrchestratorLoop) -> None:
        self.chat = chat
        self.loop = loop


class SessionManager:
    def __init__(self, memory: EpisodicMemory) -> None:
        self._memory = memory
        self._sessions: dict[str, Session] = {}

    def start(self, project_path: str | None = None, project_id: str | None = None,
              audit_path: str | None = None, repo_url: str | None = None) -> Session:
        # The target is ALWAYS an explicit, existing, EXTERNAL folder — either a
        # pasted path or a git URL cloned into an external workspace (spec 021).
        # Exactly one input; never a silent fallback to "." (that would scope the
        # session at the agent's own repo — see feedback_no_target_code_in_agent).
        has_path = bool(project_path and str(project_path).strip())
        has_url = bool(repo_url and str(repo_url).strip())
        if has_path == has_url:  # both or neither
            raise ValueError("provide exactly one of a target path or a repository URL")
        if has_url:
            try:
                url = validate_repo_url(repo_url)
                workspace = clone_repo(url, config.workspaces_root, config.git_token)
            except CloneError as e:
                raise ValueError(str(e)) from e   # clear message; carries no token
            project_path = str(workspace)
        p = Path(project_path).expanduser()
        if not p.is_dir():
            raise ValueError(f"project path is not an existing directory: {project_path}")
        audit_root = p.resolve()
        if audit_root == _AGENT_ROOT or _AGENT_ROOT in audit_root.parents:
            raise ValueError("project path must be an EXTERNAL target, not the agent repo itself")
        pid = project_id or audit_root.name
        principal = Principal(user_id="ui", platform="cli", project_id=pid)
        chat = ChatSession(principal=principal)
        save_session(chat, self._memory)

        report = _read_report(audit_path) if audit_path else None
        loop = self._build_loop(chat, principal, audit_root, report)
        s = Session(chat, loop)
        self._sessions[chat.session_id] = s
        return s

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def _build_loop(self, chat: ChatSession, principal: Principal, audit_root: Path,
                    report: str | None = None) -> OrchestratorLoop:
        audit_session = AuditSession(
            principal=principal, audit_input=AuditInput(path=audit_root, principal=principal),
        )
        if provider_factory is not None:
            provider = provider_factory()
        else:
            provider = ChatReasoningProvider(
                local=CONFIG.reasoning_client(), session=audit_session, relay_dir=config.relay_root,
                additional=ADDITIONAL.additional_client(),   # spec 019 — None → relay fallback
                system_prompt=AUDIT_CHAT_SYSTEM, signal_from=signal_from,
                domain_escalation=domain_escalation,
            )
        # Report grounding (spec 019): the report joins session_facts, which
        # build_messages DATA-wraps — untrusted reference, never instructions.
        facts_provider = None
        if report is not None:
            def facts_provider() -> str:
                return f"AUDIT REPORT (reference only):\n{report}"
        return OrchestratorLoop(
            audit_session, self._memory, audit_root,
            pack=AUDIT_PACK, reasoning_provider=provider,
            confirmations_dir=config.confirmations_root,
            event_sink=events.make_sink(chat.session_id),
            session_facts_provider=facts_provider,
            chat_model=ModelRouter(config.model_roles).route("stage2"),
        )
