---
type: Reference
title: Аудит-агент — первый capability-пак
description: Как аудит-CapabilityPack подключается к secure-agent-kernel, что он добавляет и как ограничен по конструкции.
tags: [audit-agent, capability-pack, kernel, architecture, ru]
lang: ru
status: stable
generated:
  by: araratsec-agent/claude-opus-4.8
  at: 2026-08-07T20:55:00Z
sources:
  - resource: /audit-agent.md
    title: English original
  - resource: audit_agent/pack.py
    title: AUDIT_PACK
---

# Аудит-агент — первый capability-пак

> 🇬🇧 English version: [audit-agent.md](audit-agent.md)

Аудит-агент — это **не** отдельная программа; это **capability-пак**, который подключает ядро к
одной задаче: аудиту безопасности смарт-контрактов. Всё специфичное для задачи живёт под
`sr_agent/packs/audit/` и достаёт ядро через единственный интерфейс
[`CapabilityPack`](https://github.com/RamilRamil/secure-agent-kernel). Убери пак — и [ядро](https://github.com/RamilRamil/secure-agent-kernel) стоит,
таск-агностичное; вставь другой пак — и те же гарантии безопасности применяются к другому домену.

Его цель двоякая: **делать аудиторскую работу** и, делая её, **демонстрировать, что безопасность
ядра держится под реальной состязательной нагрузкой** (он аудирует контракты, написанные
атакующими, и глотает недоверенный вывод инструментов целыми днями).

## Что добавляет пак

- **Доменная модель** (`finding.py`) — находки, `Severity`, SIG-теги, статус PoC. Это
  аудиторские концепты; ядро их никогда не видит, кроме как непрозрачные payload'ы, которые
  оно подписывает.
- **Инструменты** (`tools/`) — `static_analysis` (Slither/Mythril в sandbox), `smartgraphical`
  (анализ call-graph / структуры), `onchain` (чтение on-chain состояния через провайдера),
  `write_execute` (написать PoC, запустить `forge test` — необратимое, подтверждаемое через гейт
  действие).
- **Методология** (`planner/`, `pipeline.py`) — 3-стадийный аудит-пайплайн:
  Discovery → CheckRunner → Synthesis.
- **Рассуждение + эскалация** (`reasoning.py`, `escalation.py`) — системный промпт аудит-чата и
  доменные триггеры эскалации, инъектируемые в общую машинерию ядра.
- **Сборка** (`pack.py`) — `AUDIT_PACK`, тот `CapabilityPack`, который composition roots передают
  ядру.

Пак **ограничен по конструкции**: он может регистрировать инструменты и помечать действия
`write_execute` как высокорисковые, но не может пропустить гейт подтверждения, подделать
trust-tier или писать в память напрямую — ядро само подписывает и само задаёт tier источника.

## Жёсткое правило: аудируемая цель никогда не входит в это репо

**Код аудируемой / bug-bounty цели, имена контрактов, находки и отчёты живут целиком вне этого
репозитория.** Агент читает их из внешнего пути проекта в рантайме; сгенерированные PoC пишутся
в тот внешний проект (`<target>/audit/poc/`), никогда сюда. Примеры в этом репо используют
обобщённые имена (`Vault.sol`, `reentrancy`). Это держит агента чистым переиспользуемым
инструментом и избегает утечки чужого кода в него.

## Что нужно, чтобы запустить

Всё, что [нужно ядру](https://github.com/RamilRamil/secure-agent-kernel), плюс:

- **Docker-образы** для инструментов анализа/исполнения — `docker/Dockerfile.{slither, mythril,
  foundry}` (образ Foundry запекает `solc`, чтобы PoC компилировались офлайн под `--network none`).
- **Локальная coder-модель** (через Ollama) для локального рассуждения / драфта PoC, либо relay
  для более сильных моделей. На слабом локальном железе размести модель на облачной GPU и
  наведи `LocalClient` на туннель (см. [research/cloud-gpu-hosting.md](../research/cloud-gpu-hosting.md)).
- **Опционально**: `ALCHEMY_API_KEY` / `TENDERLY_API_KEY` для on-chain аудитов;
  `SR_SMARTGRAPHICAL_ROOT` для структурного инструмента; платный `ANTHROPIC_API_KEY` только если
  ты добровольно включаешь платный бэкенд (никогда не обязателен).

## Как его запускать

```bash
export SR_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Интерактивный аудит-чат, привязанный к ВНЕШНЕЙ папке цели:
sr-agent chat /path/to/target/contracts --project-id my-project

# Одобрить приостановленное действие write_execute, внеполосно (отдельный вызов):
sr-agent confirm <id> --approve

# Инспектировать подписанную память / запустить батч-пайплайн / relay:
sr-agent memory --project my-project
sr-agent --help
```

Тот же пак приводят в действие две другие поверхности:

- **Фронтенд оператора** (`frontend/`) — веб-консоль на одного оператора (FastAPI + Svelte) для
  запуска/наблюдения/одобрения соло, с панелью конфига модели и живым трейсом. Та же
  `OrchestratorLoop(pack=AUDIT_PACK, …)`, платный API не нужен. См.
  [specs/005-operator-frontend](../specs/005-operator-frontend/).
- **PoC-workability раннер** (`scripts/poc_queue_runner.py`) — эксперимент, проверяющий, может ли
  локальная модель автономно писать proof-of-code для находок внешнего отчёта end-to-end
  (список детекции + PoC), заземлённая только на собственном оригинальном (git-tracked) коде цели.
  Запускается против внешних `POC_PROJECT`/`POC_REPORT`. Перед прогоном **цели** нужен пригодный
  deploy/PoC-скаффолд (и RPC для fork PASS) — см.
  [poc-target-prerequisites.ru.md](poc-target-prerequisites.ru.md).

## Где проведена граница

См. [репозиторий secure-agent-kernel](https://github.com/RamilRamil/secure-agent-kernel) для инвариантов и интерфейса `CapabilityPack`, и
`specs/004-kernel-pack-boundary/` — как аудит-специфику извлекли за него (арх-тест утверждает,
что ядро импортирует ноль модулей пака).
