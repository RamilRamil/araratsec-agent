---
type: Diagram
title: Флоу написания PoC — poc_queue_runner
description: Внутренний цикл draft → grounded → compile → fix раннера PoC-workability.
tags: [poc, diagram, draft-loop, foundry, ru]
lang: ru
status: stable
generated:
  by: araratsec-agent/claude-opus-4.8
  at: 2026-08-07T20:55:00Z
sources:
  - resource: /diagrams/poc-writing-flow.md
    title: English original
  - resource: scripts/poc_queue_runner.py
    title: PoC queue runner
---

# Флоу написания PoC — `scripts/poc_queue_runner.py`

> 🇬🇧 English version: [poc-writing-flow.md](poc-writing-flow.md)

**Эксперимент на работоспособность PoC**: может ли локальная модель, ведомая хорошим честным
grounding-ом, автономно писать proof-of-code для *каждой* находки внешнего аудит-отчёта —
сама составляя свой список задач (детекция) и сама драфтя/чиня PoC? Отдельный скрипт (не
чат-оркестратор), который говорит с локальной моделью через Ollama и запускает каждый PoC в
сетево-изолированном sandbox.

Цель — её контракты, отчёт и сгенерированные PoC — живёт **целиком вне этого репо**
(`POC_PROJECT` / `POC_REPORT`); ничего таргет-специфичного сюда не коммитится.

**Требования оператора (target-side харнесс, RPC, ожидания по скаффолду):** см.
[../poc-target-prerequisites.ru.md](../poc-target-prerequisites.ru.md). Раннер наследует
deploy-базу проекта; он не бутстрапит полный стек протокола из пустого `test/`.

```mermaid
flowchart TB
    START["прогретая локальная модель<br/>(Ollama, часто туннель к облачной GPU)"] --> PRE
    PRE{"pre-flight: операторский скаффолд резолвится?<br/>fork RPC задан если --fork? модель поднята?"}
    PRE -->|"что-то не выполнено"| ABORT["ABORT прогона (exit 2)<br/>блокер всего прогона — спека 001 FR-011"]
    PRE -->|"ок"| EX
    EX["extract_tasks: МОДЕЛЬ читает отчёт<br/>и составляет свой список находок (без предфильтра)"] --> SR

    SR{"по находке: deploy-база резолвится?"}
    SR -->|"нет & --no-scaffold (абляция)"| GND
    SR -->|"нет & НЕ отключено"| BINS["исход = base-insufficient<br/>nature harness-infra — ОКРУЖЕНИЕ,<br/>ИСКЛЮЧЕНО из модельного рейта (спека 001)"]
    SR -->|"да"| MT{"скаффолд декларирует<br/>нужный тип находки?"}
    MT -->|"да"| GND
    MT -->|"нет (гейт: драфт на<br/>недостаточной базе ЗАПРЕЩЁН)"| SYN["synthesize_scaffold:<br/>расширить существующую базу (feature 011)"]
    SYN -->|"компилируется"| GND
    SYN -->|"синтез пропущен/провален →<br/>маршрут lookup не смог запуститься"| BINS
    SYN -->|"синтез пропущен/провален →<br/>lookup ЗАПУСТИЛСЯ, модель промахнулась"| LF["исход = lookup_failed<br/>nature model — ОСТАЁТСЯ в знаменателе"]

    subgraph LOOP["по находке — draft → compile → fix (N попыток, бюджет wall-clock)"]
        direction TB
        GND["grounding (только git-TRACKED / оригинальный код):<br/>· scaffold — своя PoC-база проекта для наследования<br/>· file map — каждый реальный контракт/интерфейс + путь импорта<br/>· callable_api — реальные сигнатуры функций контрактов находки<br/>· few-shot — реальный PoC проекта (другая находка)<br/>· source — интерфейсы цели + зависимостей"]
        DRAFT["draft(): LocalClient.generate"]
        FIX["детерминированный post-fix:<br/>setUp-guard · корректор путей импорта/SPDX"]
        RUN["write_poc → run_tests<br/>DockerSandbox, --network none --offline"]
        GATE["структурный гейт _poc_defects<br/>(нет вакуумных/mock/unimported) + детект компиляции"]
        GND --> DRAFT --> FIX --> RUN --> GATE
        GATE -->|"провал компиляции / дефекты"| REPAIR["fix(): подать ошибки forge + дефекты + grounding"] --> FIX
    end

    GATE -->|"компилируется + структурно реален"| OK["исход = compiled (путь A)<br/>или passed если зелёный (нужен mainnet fork)"]
    GATE -->|"попытки исчерпаны"| QUAR["карантин некомпилирующегося PoC"]
```

Разделение `base-insufficient` vs `lookup_failed` — это линия честности: **environment**-разрыв
(нет резолвящейся/синтезируемой базы, либо маршрут lookup не смог запуститься) покидает
знаменатель модели; **model**-промах (lookup запустился, а модель всё ещё не имела пригодного
деплоя) остаётся в нём. См. [../poc-target-prerequisites.ru.md](../poc-target-prerequisites.ru.md) §3.

## Как это читать

- **Модель делает работу end-to-end** — сама извлекает список находок (детекция) и сама драфтит
  + чинит каждый PoC. Оператор только запускает харнесс и даёт путь к цели; находки/PoC здесь
  никогда не пишутся вручную.
- **Grounding честен** — подаётся только собственный **git-tracked (оригинальный)** код цели;
  skill-сгенерированные PoC исключены, чтобы модели никогда не давали ответ. File map +
  callable_api противостоят привычке модели выдумывать имена интерфейсов / сигнатуры методов;
  скаффолд позволяет ей наследовать реальную deploy-базу проекта.
- **Детерминированные guard'ы бьют промпт на механических ошибках** — маленькая модель то и дело
  переопределяет невиртуальный `setUp` (4334) или выдаёт неверную глубину импорта / голую строку
  SPDX; это чинится в коде после генерации, а не оставляется промпту.
- **Планка успеха честна к sandbox** — PoC этой цели суть mainnet-fork тесты, которые не могут
  быть зелёными под `--network none`; поэтому путь A засчитывает PoC, который **компилируется и
  структурно реален** («compiled»), и только зелёный `forge`-прогон — это «passed»
  (`--require-pass`). Проход с вакуумным/замоканным тестом отклоняется гейтом.

См. [../poc-target-prerequisites.ru.md](../poc-target-prerequisites.ru.md) — чеклист оператора
перед прогоном, [../audit-agent.ru.md](../audit-agent.ru.md) — как драфт PoC связан с аудит-паком.
