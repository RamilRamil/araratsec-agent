# Chat turn flow — `sr-agent chat` (feature 003)

One turn of the interactive chat loop, through `OrchestratorLoop.run_turn`. Local-first, no paid API. The loop is the task-agnostic [kernel](../kernel.md); the tool dispatch, domain escalation, and finding persistence shown below are supplied by the [audit pack](../audit-agent.md) through its `CapabilityPack` (the kernel keeps the control flow + every invariant). Same DATA-wrapping / `validate_action` / out-of-band confirmation on any surface (CLI or the operator frontend).

```mermaid
sequenceDiagram
    participant U as User (REPL)
    participant CLI as cli.chat / handle_turn
    participant Loop as OrchestratorLoop.run_turn
    participant Prov as ChatReasoningProvider
    participant Local as LocalClient (Ollama)
    participant Guard as evaluate_triggers
    participant Mem as EpisodicMemory

    U->>CLI: types a message
    CLI->>Loop: run_turn(user_message)
    Note over Loop: user_message wrapped [DATA START]..[DATA END]<br/>session_facts folded in (grounding)
    loop until answer / pause / budget
        Loop->>Prov: complete(messages)
        Prov->>Local: ready()?  (deep probe, R10)
        alt not ready
            Prov-->>Loop: blocked_local_unavailable (FR-011, no relay fallback)
        else ready
            Prov->>Local: generate (fmt=json)
            Local-->>Prov: AgentAction JSON
            Prov->>Guard: evaluate_triggers(finding, session)
            alt guard fires OR model self-report
                Prov-->>Loop: paused_relay (files relay request)
            else no escalation
                Prov-->>Loop: action(AgentAction)
            end
        end
        alt next_action == complete
            Loop-->>CLI: TurnResult(completed, answer, tier)
        else read_file / search_code
            Loop->>Loop: validate_action → _dispatch → wrap_data(result)
            Note over Loop: result re-enters as DATA next iteration<br/>tool-call budget (SC-005)
        else write_poc / run_tests (irreversible)
            Loop-->>CLI: TurnResult(paused_confirmation, notice)
        end
    end
    CLI->>Mem: save_turn + update_facts (orchestrator-authored)
    CLI-->>U: [tier] answer  (or pause/blocked instructions)
```

## The paused paths (do not block the REPL)

- `paused_confirmation` (write_poc/run_tests): the CLI prints the `ConsequentialActionNotice` and exits; the user approves via `sr-agent confirm <id> --approve` and re-runs `sr-agent chat --resume <id>`, which ingests the decision and runs the action **only then** (`execute_confirmed` is the sole run path — no in-turn shortcut).
- `paused_relay` (deterministic escalation or model self-report): prints the relay request id and exits; user answers via the `sr-agent relay` flow, then resumes.
- `blocked_local_unavailable`: prints "local model unavailable"; **no** relay fallback (FR-011); re-run `--resume` once the model is back.

## Trust invariants preserved (Constitution I/II)

- Every tool result and prior-turn artifact re-enters context as DATA on every turn — never executed as an instruction.
- Model/relay output stays `external_llm_output`; the roadmap's PoC status is `tool_output` and a passing PoC is a reproduction, **not** a verdict. Chat has no action that writes a privileged `status_change` — that authority lives only in `sr-agent memory`/`confirm`.
