from __future__ import annotations

import sys
from pathlib import Path

import click

from sr_agent.llm_core.router import ModelRouter
from audit_agent.config import config
from audit_agent.input_val import InputValidationError, validate_audit_input
from audit_agent.session import AuditInput, AuditSession, Principal


@click.group()
def cli() -> None:
    """SR-agent: memory-injection-resistant smart contract auditor."""


# ── chat mode helpers (feature 003) — module-level so tests import without the REPL ──

_STATUS_TO_SESSION = {
    "completed": "active",
    "budget_exhausted": "active",
    "paused_confirmation": "paused_confirmation",
    "paused_relay": "paused_relay",
    "blocked_local_unavailable": "blocked_local_unavailable",
}


def _facts_to_str(facts) -> str | None:
    """Render orchestrator-authored grounding facts for the model prompt (R6)."""
    if facts is None:
        return None
    parts = [f"bound_project={facts.project_id}"]
    if facts.known_finding_ids:
        parts.append("known_findings=" + ",".join(facts.known_finding_ids))
    if facts.recent_tool_summaries:
        parts.append("recent=" + " | ".join(facts.recent_tool_summaries))
    return "; ".join(parts)


def format_reply(result) -> str:
    """Render a turn result for the user, always surfacing the routing tier (FR-010/SC-006)."""
    tier = result.routing.tier if result.routing else "local"
    if result.status == "completed":
        return f"[{tier}] {result.answer}"
    if result.status == "blocked_local_unavailable":
        return "[blocked] local model unavailable — turn not processed. Re-run --resume once it's back (no relay fallback)."
    if result.status == "paused_confirmation":
        what = result.pending_action_type or "action"
        params = result.pending_action_params or {}
        return (
            f"[{tier}] will run {what} {params} — pending out-of-band confirmation "
            f"(id {result.pending_confirmation_id}). Approve with "
            f"`sr-agent confirm {result.pending_confirmation_id} --approve`, then "
            f"`sr-agent chat --resume <session_id>`."
        )
    if result.status == "paused_relay":
        return (
            f"[relay] escalated to the manual relay (request {result.relay_request_id}). "
            f"Run `sr-agent relay --show {result.relay_request_id}`, answer via Claude, "
            f"`sr-agent relay --respond`, then `sr-agent chat --resume <session_id>`."
        )
    return f"[{tier}] {result.answer}"


def handle_turn(loop, session, memory, user_message: str):
    """Run one chat turn and persist it. Returns the TurnResult.

    Separated from the click REPL so it's testable with a fake reasoning
    provider (no stdin, no real Ollama).
    """
    from datetime import datetime, timezone

    from sr_agent.models.chat import ChatTurn
    from sr_agent.models.memory import SourceType
    from sr_agent.orchestrator.chat_session import save_turn, update_facts

    result = loop.run_turn(user_message, system_prompt="")
    # Grounding facts are orchestrator-authored from real results, never model text
    # (US4/R6): known findings + a bounded trail of what's already been looked at,
    # so a long investigation session stays coherent past the model's window.
    for finding in result.findings:
        update_facts(session, finding_id=finding.finding_id)
    for summary in result.tool_summaries:
        update_facts(session, tool_summary=summary)

    session.status = _STATUS_TO_SESSION.get(result.status, "active")
    session.pending_confirmation_id = result.pending_confirmation_id
    session.pending_relay_request_id = result.relay_request_id

    turn = ChatTurn(
        session_id=session.session_id,
        user_message=user_message,
        routing_decision=result.routing,
        agent_action=None,
        source_type=SourceType.external_llm_output,
        completed_at=datetime.now(timezone.utc) if result.status == "completed" else None,
    )
    save_turn(session, turn, memory)
    return result


def resume_confirmation(loop, session, memory) -> str:
    """Ingest a resolved OOB confirmation and finish the paused write_execute (US2/T018).

    Approved → reconstruct the action from the confirmation record and dispatch it
    (the ONLY path that runs it — approval never happens in a model turn). Records
    a mechanical PoC status event (never a verdict). Rejected/timeout → not executed.
    """
    from sr_agent.models.action import Action, ActionType
    from sr_agent.orchestrator.action import validate_action
    from sr_agent.orchestrator.chat_session import record_poc_status, save_session, update_facts
    from sr_agent.orchestrator.confirmation import load_request

    cid = session.pending_confirmation_id
    if not cid:
        return "no pending confirmation on this session."
    try:
        payload = load_request(cid, loop._confirmations_dir)
    except FileNotFoundError:
        return f"confirmation {cid} not found."

    status = payload.get("status", "pending")
    if status == "pending":
        return f"confirmation {cid} still pending — approve/reject out-of-band first."

    if status != "approved":
        session.status = "active"
        session.pending_confirmation_id = None
        save_session(session, memory)
        return f"confirmation {cid} was {status} — action not executed."

    # Approved: rebuild + re-validate the action, then execute out-of-band-gated.
    action = Action(action_type=ActionType(payload["action_type"]), params=payload.get("params", {}))
    validate_action(action, loop._audit_root, loop._pack)   # re-annotate class/reversibility
    action.human_confirmation = True
    summary, event = loop.execute_confirmed(action)
    if event is not None:
        record_poc_status(session, event, memory)
        update_facts(session, tool_summary=f"{event.status}: {event.finding_id}")

    session.status = "active"
    session.pending_confirmation_id = None
    save_session(session, memory)
    return summary


@cli.command()
@click.argument("path_or_address", required=False)
@click.option("--path", "-p", type=click.Path(), help="Path to .sol files directory")
@click.option("--address", "-a", help="EIP-55 contract address for on-chain audit")
@click.option("--exclude", multiple=True, type=click.Path(), help="Paths to exclude")
@click.option("--focus", multiple=True, type=click.Path(), help="Restrict to these files")
@click.option("--no-imports", is_flag=True, help="Exclude OpenZeppelin/library imports from SIG")
@click.option("--no-smartgraphical", is_flag=True, help="Disable the SmartGraphical engine")
@click.option("--output", "-o", type=click.Path(), default="audit-report.md")
@click.option("--project-id", default=None, help="Override project ID (default: derived from path)")
@click.option("--resume", "--resume-session", default=None, help="Resume a session by ID")
def audit(
    path_or_address: str | None,
    path: str | None,
    address: str | None,
    exclude: tuple[str, ...],
    focus: tuple[str, ...],
    no_imports: bool,
    no_smartgraphical: bool,
    output: str,
    project_id: str | None,
    resume: str | None,
) -> None:
    """Run a security audit on a smart contract codebase or on-chain address."""

    # Resolve positional arg
    if path_or_address:
        if path_or_address.startswith("0x"):
            address = path_or_address
        else:
            path = path_or_address

    audit_path = Path(path) if path else None
    derived_project_id = project_id or (audit_path.name if audit_path else address or "unknown")

    principal = Principal(
        user_id="cli-user",
        platform="cli",
        project_id=derived_project_id,
    )

    audit_input = AuditInput(
        path=audit_path,
        address=address,
        exclude_paths=[Path(e) for e in exclude],
        focus_files=[Path(f) for f in focus],
        include_imports=not no_imports,
        principal=principal,
        resume_session_id=resume,
    )

    try:
        validate_audit_input(audit_input, audit_root=Path("."))
    except InputValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    click.echo(f"Starting audit for project '{derived_project_id}'…")

    if audit_path is None:
        click.echo(
            "The relay pipeline needs a local path; address-based audit is not "
            "yet supported.", err=True,
        )
        sys.exit(2)

    from sr_agent.eval.tracer import Tracer
    from sr_agent.io.progress import ProgressStream
    from sr_agent.memory.episodic import EpisodicMemory
    from audit_agent.pipeline import start_audit

    memory = EpisodicMemory(config.memory_root, config.secret_key)
    relay_dir = config.relay_root
    runs_dir = config.relay_root / "runs"
    tracer = Tracer(
        secret_key=config.langfuse_secret_key,
        public_key=config.langfuse_public_key,
        host=config.langfuse_host,
    )

    result = start_audit(
        audit_input, audit_path, memory, relay_dir, runs_dir,
        output=output, progress=ProgressStream(), stage2_provider="auto",
        smartgraphical_root="" if no_smartgraphical else config.smartgraphical_root,
        tracer=tracer,
    )

    if result.status == "paused":
        click.echo(f"Stage 1 done. {result.pending} target(s) need analysis via relay:")
        click.echo("  1. sr-agent relay --list                      # pending request ids")
        click.echo("  2. sr-agent relay --show <id>                 # copy into Claude")
        click.echo("  3. sr-agent relay --respond <id> <file>       # submit each answer")
        click.echo(f"  4. sr-agent resume {result.session_id}")
        sys.exit(0)

    click.echo(f"Audit complete: {result.findings_count} finding(s) → {result.report_path}")
    sys.exit(0)


@cli.command("resume")
@click.argument("session_id")
def resume_cmd(session_id: str) -> None:
    """Resume a paused audit: ingest relay responses, finish the report."""
    from sr_agent.io.progress import ProgressStream
    from sr_agent.memory.episodic import EpisodicMemory
    from audit_agent.pipeline import resume_audit

    memory = EpisodicMemory(config.memory_root, config.secret_key)
    relay_dir = config.relay_root
    runs_dir = config.relay_root / "runs"

    try:
        result = resume_audit(session_id, memory, relay_dir, runs_dir, progress=ProgressStream())
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    if result.status == "paused":
        click.echo(f"Still waiting on {result.pending} response(s). Run `sr-agent relay --list`.")
        sys.exit(0)

    click.echo(f"Audit complete: {result.findings_count} finding(s) → {result.report_path}")
    sys.exit(0)


@cli.command("demo-attack")
@click.option("--scenario", default=None, help="Run a single scenario by ID (e.g. MI-001)")
@click.option("--no-baseline", is_flag=True, help="Skip baseline (unprotected) measurement")
@click.option("--output", "-o", default=None, help="Write JSON report to file")
def demo_attack(scenario: str | None, no_baseline: bool, output: str | None) -> None:
    """Demonstrate Memory Injection attack scenarios and verify protection.

    Runs 5 reproducible MI attack scenarios from 2503.16248v3.
    Reports ASR (Attack Success Rate) with and without protection.
    Exits 0 if protected ASR = 0, exits 1 if any attack succeeded.
    """
    import json
    from tests.security.mi_scenarios import SCENARIOS, TEST_SECRET, run_scenario, measure_asr
    from sr_agent.memory.episodic import EpisodicMemory
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        memory = EpisodicMemory(Path(tmp), TEST_SECRET)

        scenarios_to_run = SCENARIOS
        if scenario:
            scenarios_to_run = [s for s in SCENARIOS if s.scenario_id == scenario]
            if not scenarios_to_run:
                click.echo(f"Unknown scenario: {scenario}", err=True)
                sys.exit(2)

        click.echo("\n── SR-agent Memory Injection Demo ──────────────────────────")
        click.echo(f"Running {len(scenarios_to_run)} scenario(s)\n")

        report = {"scenarios": [], "protected_asr": 0.0, "baseline_asr": None}
        any_failed = False

        for s in scenarios_to_run:
            protected_result = run_scenario(s, memory, protected=True)
            status = "BLOCKED ✓" if protected_result.blocked else "LEAKED ✗"
            click.echo(f"  [{s.scenario_id}] {s.attack_type.value:<35} {status}")
            if not protected_result.blocked:
                click.echo(f"           → {protected_result.block_reason}", err=True)
                any_failed = True

            entry = {
                "scenario_id": s.scenario_id,
                "attack_type": s.attack_type.value,
                "blocked": protected_result.blocked,
                "block_reason": protected_result.block_reason,
            }

            if not no_baseline:
                baseline_result = run_scenario(s, memory, protected=False)
                entry["baseline_would_succeed"] = baseline_result.baseline_would_succeed

            report["scenarios"].append(entry)

        protected_asr = measure_asr(scenarios_to_run, memory, protected=True)
        report["protected_asr"] = protected_asr

        click.echo(f"\nProtected ASR:  {protected_asr:.0%}  (target ≤ 5%)")

        if not no_baseline:
            baseline_asr = measure_asr(scenarios_to_run, memory, protected=False)
            report["baseline_asr"] = baseline_asr
            differential = baseline_asr - protected_asr
            click.echo(f"Baseline ASR:   {baseline_asr:.0%}  (expected ≥ 40%)")
            click.echo(f"Differential:   {differential:.0%}  (target ≥ 40pp)")

        click.echo("─" * 52)

        if output:
            Path(output).write_text(json.dumps(report, indent=2))
            click.echo(f"Report written to {output}")

        sys.exit(1 if any_failed else 0)


@cli.command("memory")
@click.argument("subcommand", type=click.Choice(["list", "show", "verify"]))
@click.option("--project-id", required=True)
@click.option("--target", default=None)
def memory_cmd(subcommand: str, project_id: str, target: str | None) -> None:
    """Inspect or verify episodic memory records."""
    from sr_agent.memory.episodic import EpisodicMemory

    mem = EpisodicMemory(config.memory_root, config.secret_key)

    if subcommand == "list":
        root = config.memory_root / project_id
        if not root.exists():
            click.echo("No memory found for this project.")
            return
        for f in root.glob("*.jsonl"):
            click.echo(f.stem)

    elif subcommand == "verify":
        report = mem.verify_integrity(project_id)
        for target_stem, (t_total, t_valid, t_invalid) in sorted(report.per_target.items()):
            marker = "OK" if t_invalid == 0 else f"{t_invalid} INVALID"
            click.echo(f"  {target_stem}: {t_valid}/{t_total} valid  [{marker}]")
        click.echo(
            f"Total: {report.valid}/{report.total} valid, {report.invalid} invalid"
        )
        sys.exit(1 if report.has_invalid else 0)

    elif subcommand == "show" and target:
        records = mem.load(project_id, target)
        for r in records:
            click.echo(r.model_dump_json(indent=2))


@cli.command("confirm")
@click.argument("confirmation_id")
@click.option("--approve", is_flag=True, help="Approve the pending irreversible action")
@click.option("--reject", is_flag=True, help="Reject the pending irreversible action")
@click.option("--show", is_flag=True, help="Show the pending action details")
def confirm_cmd(confirmation_id: str, approve: bool, reject: bool, show: bool) -> None:
    """Approve, reject, or inspect a pending out-of-band confirmation.

    This is the out-of-band channel: it runs as a separate process from the
    agent loop, so the agent can never approve its own irreversible actions.
    """
    import json
    from sr_agent.orchestrator.confirmation import load_request, resolve_confirmation

    confirmations_dir = config.confirmations_root

    if show:
        try:
            req = load_request(confirmation_id, confirmations_dir)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)
        click.echo(json.dumps(req, indent=2))
        return

    if approve == reject:  # both flags or neither
        click.echo("Specify exactly one of --approve / --reject (or --show).", err=True)
        sys.exit(2)

    try:
        status = resolve_confirmation(confirmation_id, confirmations_dir, approve=approve)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    click.echo(f"Confirmation {confirmation_id}: {status.value}")


@cli.command("lessons")
@click.argument("subcommand",
                type=click.Choice(["list", "show", "approve", "dismiss", "verify", "add"]))
@click.argument("sig_id", required=False)
@click.option("--from", "from_file", type=click.Path(exists=True),
              help="JSON candidate file for `add` (seeding a hand-authored lesson).")
@click.option("--edit", "edit_file", type=click.Path(exists=True),
              help="Markdown replacement content for `approve`.")
def lessons_cmd(subcommand: str, sig_id: str | None,
                from_file: str | None, edit_file: str | None) -> None:
    """Experiential knowledge loop (feature 014) — review and promote lesson candidates.

    Out-of-band, a separate process from the agent/harness loop: `approve` is the ONLY
    path that promotes a lesson into the retrievable corpus (the agent can never promote
    its own knowledge — Principle IV). Promotion signs the lesson (tamper-evident) and
    grants authorization=human_input while keeping origin=llm_inference (honest audit).
    """
    import json
    from dataclasses import asdict

    from sr_agent.memory.lessons import LessonCandidate, LessonStore

    store = LessonStore(config.lessons_root, config.knowledge_root, config.secret_key)

    if subcommand == "list":
        pending = store.list_pending()
        if not pending:
            click.echo("No pending lessons.")
            return
        for c in pending:
            click.echo(f"{c.sig_id}  [{c.category}]  {c.symptom[:70]}")
        return

    if subcommand == "verify":
        report = store.verify()
        for sid, status in sorted(report.per_lesson.items()):
            click.echo(f"  {sid}: {status}")
        click.echo(f"Total: {report.valid}/{report.total} valid, {report.invalid} invalid")
        sys.exit(1 if report.has_invalid else 0)

    if subcommand == "add":
        if not from_file:
            click.echo("`add` requires --from <file>.", err=True)
            sys.exit(2)
        data = json.loads(Path(from_file).read_text(encoding="utf-8"))
        cand = LessonCandidate.create(
            trigger_signature=data["trigger_signature"],
            symptom=data.get("symptom", ""),
            fix=data.get("fix", ""),
            category=data.get("category", "poc-compile"),
        )
        store.add(cand)
        click.echo(f"Candidate {cand.sig_id} queued for review.")
        return

    # remaining subcommands need a sig_id
    if not sig_id:
        click.echo(f"`{subcommand}` requires <sig_id>.", err=True)
        sys.exit(2)

    if subcommand == "show":
        cand = store.show(sig_id)
        if cand is None:
            click.echo(f"No pending lesson {sig_id}.", err=True)
            sys.exit(2)
        click.echo(json.dumps(asdict(cand), indent=2))
        return

    if subcommand == "dismiss":
        if store.dismiss(sig_id):
            click.echo(f"Lesson {sig_id} dismissed.")
            return
        click.echo(f"No pending lesson {sig_id}.", err=True)
        sys.exit(2)

    if subcommand == "approve":
        edited = Path(edit_file).read_text(encoding="utf-8") if edit_file else None
        try:
            lesson = store.promote(sig_id, edited_content=edited)
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)
        ok = store.verify().per_lesson.get(sig_id) == "OK"
        click.echo(f"Lesson {sig_id} promoted (category {lesson.category}); "
                   f"signature {'verifies' if ok else 'FAILED'}.")
        return


@cli.command("relay")
@click.argument("request_id", required=False)
@click.option("--show", is_flag=True, help="Print the request packet to copy into Claude")
@click.option("--respond", "respond_file", default=None, type=click.Path(),
              help="Ingest a saved Claude response file for REQUEST_ID")
@click.option("--list", "list_flag", is_flag=True, help="List requests awaiting a response")
def relay_cmd(request_id: str | None, show: bool, respond_file: str | None, list_flag: bool) -> None:
    """Manual LLM relay: show a request, submit a response, or list pending.

    Relayed responses are external_llm_output — carrying a file does not grant
    human authority (use `sr-agent confirm` for that).
    """
    from sr_agent.orchestrator.relay import list_pending, read_request, save_response
    from audit_agent.relay_ingest import ingest_response
    relay_dir = config.relay_root

    if list_flag:
        pending = list_pending(relay_dir)
        if not pending:
            click.echo("No pending relay requests.")
        for rid in pending:
            click.echo(rid)
        return

    if not request_id:
        click.echo("A REQUEST_ID is required (or use --list).", err=True)
        sys.exit(2)

    if show:
        try:
            click.echo(read_request(request_id, relay_dir))
        except FileNotFoundError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)
        return

    if respond_file:
        text = Path(respond_file).read_text(encoding="utf-8")
        save_response(request_id, relay_dir, text)
        result = ingest_response(request_id, relay_dir, response_text=text)
        if result.needs_resend:
            click.echo(
                f"Response saved but unparseable — please resend. "
                f"({'; '.join(result.errors)})",
                err=True,
            )
            sys.exit(1)
        click.echo(
            f"Response saved: {len(result.findings)} finding(s) parsed, "
            f"{len(result.errors)} error(s)."
        )
        for err in result.errors:
            click.echo(f"  ! {err}", err=True)
        return

    click.echo("Specify one of --show / --respond <file> / --list.", err=True)
    sys.exit(2)


@cli.command("chat")
@click.argument("project_or_path", required=False)
@click.option("--resume", "resume_session", default=None, help="Resume a chat session by id")
@click.option("--project-id", default=None, help="Override/select project id")
@click.option("--model", "model", default=None, help="Local Ollama model override (default: for_stage2 resolution)")
def chat_cmd(project_or_path: str | None, resume_session: str | None, project_id: str | None, model: str | None) -> None:
    """Interactive chat bound to one project (feature 003).

    Local-first; escalates to relay only on a deterministic trigger, never as a
    fallback for an unavailable local model. Irreversible actions still route
    through `sr-agent confirm` — the chat cannot bypass the gate.
    """
    from sr_agent.llm_core.chat_reasoning import ChatReasoningProvider
    from sr_agent.llm_core.local_client import LocalClient
    from sr_agent.memory.episodic import EpisodicMemory
    from sr_agent.models.chat import ChatSession
    from sr_agent.orchestrator.chat_session import load_session, save_session
    from sr_agent.orchestrator.loop import OrchestratorLoop
    from audit_agent.escalation import domain_escalation
    from audit_agent.pack import AUDIT_PACK
    from audit_agent.reasoning import AUDIT_CHAT_SYSTEM, signal_from

    memory = EpisodicMemory(config.memory_root, config.secret_key)

    if resume_session:
        pid = project_id or project_or_path
        if not pid:
            click.echo("--resume requires --project-id (or the project positional).", err=True)
            sys.exit(2)
        session = load_session(resume_session, pid, memory)
        if session is None:
            click.echo(f"Error: chat session {resume_session!r} not found for project {pid!r}.", err=True)
            sys.exit(2)
        principal = session.principal
        derived_pid = principal.project_id
        audit_root = Path(".")
        if session.status in ("paused_relay", "blocked_local_unavailable"):
            # relay/local resume ingest lands in a later phase.
            click.echo(f"note: {session.status!r} resume is not wired yet — continuing as a fresh turn.")
    else:
        if not project_or_path:
            click.echo("A project id or path is required (or use --resume).", err=True)
            sys.exit(2)
        p = Path(project_or_path)
        if p.exists() and p.is_dir():
            audit_root, derived_pid = p, (project_id or p.name)
        else:
            audit_root, derived_pid = Path("."), (project_id or project_or_path)
        principal = Principal(user_id="cli-user", platform="cli", project_id=derived_pid)
        session = ChatSession(principal=principal)
        save_session(session, memory)

    audit_session = AuditSession(
        principal=principal,
        audit_input=AuditInput(path=audit_root, principal=principal),
    )
    local_client = LocalClient(model=model) if model else LocalClient.for_stage2()
    provider = ChatReasoningProvider(
        local=local_client, session=audit_session, relay_dir=config.relay_root,
        system_prompt=AUDIT_CHAT_SYSTEM, signal_from=signal_from,
        domain_escalation=domain_escalation,
    )
    _router = ModelRouter(config.model_roles)
    loop = OrchestratorLoop(
        audit_session, memory, audit_root,
        pack=AUDIT_PACK,
        reasoning_provider=provider,
        session_facts_provider=lambda: _facts_to_str(session.session_facts),
        confirmations_dir=config.confirmations_root,
        chat_model=_router.route("stage2"),
    )
    provider.existing_findings = loop._findings  # share for evaluate_triggers (R3)

    # Warm the local model once so the first turn's readiness probe doesn't fail on
    # a cold load (a larger model can take minutes to load on CPU).
    click.echo(f"warming {local_client.model} (first load can take a few minutes on CPU)…")
    if not local_client.warm():
        click.echo(
            f"note: {local_client.model} not ready — the first turn may report "
            "'blocked'; it recovers automatically once the model is up."
        )

    # Resuming a session paused on an OOB confirmation: ingest the decision and
    # finish (or cancel) the write_execute before accepting new input (T018).
    if resume_session and session.status == "paused_confirmation":
        click.echo(resume_confirmation(loop, session, memory))

    click.echo(f"chat session {session.session_id} (project {derived_pid}). Ctrl-D to quit.")
    while True:
        try:
            user_message = click.prompt("you", prompt_suffix="> ")
        except (EOFError, click.exceptions.Abort):
            click.echo("")
            break
        if not user_message.strip():
            continue
        result = handle_turn(loop, session, memory, user_message)
        click.echo(format_reply(result))
        if result.status in ("paused_confirmation", "paused_relay", "blocked_local_unavailable"):
            click.echo(
                f"(session paused — resume with "
                f"`sr-agent chat --resume {session.session_id} --project-id {derived_pid}`)"
            )
            break
    sys.exit(0)


if __name__ == "__main__":
    cli()
