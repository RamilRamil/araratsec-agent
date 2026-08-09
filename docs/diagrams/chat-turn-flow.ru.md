---
type: Diagram
title: Флоу хода чата — sr-agent chat
description: Один ход OrchestratorLoop.run_turn — DATA-обёртка, validate_action, эскалация, OOB-пауза.
tags: [chat, orchestrator, diagram, sequence, ru]
lang: ru
status: stable
generated:
  by: araratsec-agent/claude-opus-4.8
  at: 2026-08-07T20:55:00Z
sources:
  - resource: /diagrams/chat-turn-flow.md
    title: English original
  - resource: sr_agent/orchestrator/loop.py
    title: OrchestratorLoop.run_turn
---

# Флоу хода чата — `sr-agent chat` (feature 003)

> 🇬🇧 English version: [chat-turn-flow.md](chat-turn-flow.md)

Один ход интерактивной петли чата, через `OrchestratorLoop.run_turn`. Local-first, без платного
API. Петля — это таск-агностичное [ядро](https://github.com/RamilRamil/secure-agent-kernel); показанные ниже диспетч инструментов,
доменная эскалация и персист находок поставляются [аудит-паком](../audit-agent.ru.md) через его
`CapabilityPack` (ядро сохраняет поток управления + каждый инвариант). Те же DATA-обёртка /
`validate_action` / внеполосное подтверждение на любой поверхности (CLI или фронтенд оператора).

```mermaid
sequenceDiagram
    participant U as Пользователь (REPL)
    participant CLI as cli.chat / handle_turn
    participant Loop as OrchestratorLoop.run_turn
    participant Prov as ChatReasoningProvider
    participant Local as LocalClient (Ollama)
    participant Guard as evaluate_triggers
    participant Mem as EpisodicMemory

    U->>CLI: печатает сообщение
    CLI->>Loop: run_turn(user_message)
    Note over Loop: user_message обёрнут [DATA START]..[DATA END]<br/>session_facts подмешаны (grounding)
    loop пока ответ / пауза / бюджет
        Loop->>Prov: complete(messages)
        Prov->>Local: ready()?  (глубокая проба, R10)
        alt не готов
            Prov-->>Loop: blocked_local_unavailable (FR-011, нет relay-fallback)
        else готов
            Prov->>Local: generate (fmt=json)
            Local-->>Prov: AgentAction JSON
            Prov->>Guard: evaluate_triggers(finding, session)
            alt guard сработал ИЛИ само-отчёт модели
                Prov-->>Loop: paused_relay (заводит relay-запрос)
            else нет эскалации
                Prov-->>Loop: action(AgentAction)
            end
        end
        alt next_action == complete
            Loop-->>CLI: TurnResult(completed, answer, tier)
        else read_file / search_code
            Loop->>Loop: validate_action → _dispatch → wrap_data(result)
            Note over Loop: результат снова входит как DATA на след. итерации<br/>бюджет tool-call (SC-005)
        else write_poc / run_tests (необратимо)
            Loop-->>CLI: TurnResult(paused_confirmation, notice)
        end
    end
    CLI->>Mem: save_turn + update_facts (авторство оркестратора)
    CLI-->>U: [tier] ответ  (или инструкции паузы/блокировки)
```

## Пути с паузой (не блокируют REPL)

- `paused_confirmation` (write_poc/run_tests): CLI печатает `ConsequentialActionNotice` и
  выходит; пользователь одобряет через `sr-agent confirm <id> --approve` и перезапускает
  `sr-agent chat --resume <id>`, который принимает решение и запускает действие **только тогда**
  (`execute_confirmed` — единственный путь запуска, без внутриходового среза).
- `paused_relay` (детерминированная эскалация или само-отчёт модели): печатает id relay-запроса
  и выходит; пользователь отвечает через поток `sr-agent relay`, затем возобновляет.
- `blocked_local_unavailable`: печатает «local model unavailable»; **нет** relay-fallback
  (FR-011); перезапустить `--resume`, как только модель вернётся.

## Сохраняемые инварианты доверия (Конституция I/II)

- Каждый результат инструмента и артефакт прошлого хода снова входит в контекст как DATA на
  каждом ходу — никогда не исполняется как инструкция.
- Вывод модели/relay остаётся `external_llm_output`; статус PoC из roadmap — `tool_output`, а
  проходящий PoC — это воспроизведение, **не** вердикт. У чата нет действия, пишущего
  привилегированный `status_change` — эта власть живёт только в `sr-agent memory`/`confirm`.
