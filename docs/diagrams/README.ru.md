---
type: Reference
title: Индекс диаграмм
description: Индекс диаграмм архитектуры и потоков исполнения; двуязычная конвенция EN/RU.
tags: [index, diagrams, ru]
lang: ru
status: stable
generated:
  by: araratsec-agent/claude-opus-4.8
  at: 2026-08-07T20:55:00Z
sources:
  - resource: /diagrams/README.md
    title: English original
---

# Диаграммы

> 🇬🇧 English version: [README.md](README.md)

Диаграммы архитектуры и потоков исполнения SR-agent, отражающие **то, что реально подключено и
работает сегодня**. Исходники на Mermaid, рендерятся в GitHub/VS Code/большинстве markdown-вьюеров.

**Двуязычные доки.** У каждого дока есть английский базовый файл (`name.md`) и русский сосед
(`name.ru.md`); они перекрёстно ссылаются вверху. Держи пару в синхроне при изменении проводки.

- [agent-overview-flow.ru.md](agent-overview-flow.ru.md) · [🇬🇧](agent-overview-flow.md) — **весь
  агент**: capability-пайплайн (Discovery → CheckRunner → Synthesis → отчёт) и ось безопасности
  ядра, которая его оборачивает, с PoC-слоем как отсоединённым downstream-блоком. Помечает
  wired vs vision.
- [poc-lifecycle-flow.ru.md](poc-lifecycle-flow.ru.md) · [🇬🇧](poc-lifecycle-flow.md) — зум в
  PoC-блок: отчёт → вердикт по находке → измерительный каскад → триаж качества. Помечает, что
  подключено сегодня (стадии 1–13) vs где суждение всё ещё вручную (14–15).
- [poc-writing-flow.ru.md](poc-writing-flow.ru.md) · [🇬🇧](poc-writing-flow.md) — внутренний цикл
  `scripts/poc_queue_runner.py`: модель извлекает свой список находок, затем draft → grounded →
  compile → fix. Чеклист target-side харнесса/RPC:
  [../poc-target-prerequisites.ru.md](../poc-target-prerequisites.ru.md).
- [architecture-overview.ru.md](architecture-overview.ru.md) · [🇬🇧](architecture-overview.md) —
  карта модулей: таск-агностичное [ядро](https://github.com/RamilRamil/secure-agent-kernel), [аудит-пак](../audit-agent.ru.md),
  подключающийся к нему, два composition roots (CLI + фронтенд оператора) и отдельный PoC-эксперимент.
- [chat-turn-flow.ru.md](chat-turn-flow.ru.md) · [🇬🇧](chat-turn-flow.md) — один ход `sr-agent chat`
  через `OrchestratorLoop.run_turn` (DATA-обёртка, validate_action, эскалация, OOB-пауза).

Обновляй их при изменении проводки — диаграмма, которая врёт о том, что подключено, хуже, чем
отсутствие диаграммы.
