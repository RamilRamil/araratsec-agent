# Обзор фреймворков по модулям SR-agent

Для каждого из 7 модулей: что существует, что берём, что пишем сами и почему.

---

## 1. Оркестратор

### Ландшафт фреймворков

| Фреймворк | Модель | Сильные стороны | Слабые стороны |
|-----------|--------|-----------------|----------------|
| **LangGraph** | Граф состояний (nodes + edges) | Checkpointing first-class, HITL, audit trail, v1.0 2025, Enterprise-ready | Завязан на LangChain экосистему |
| **CrewAI** | Role-based агенты | Быстрый прототип, роли + tasks интуитивны | Слабый state management, сложно в production |
| **AutoGen / AG2** | Conversational multi-agent | Мульти-агент через диалог, event-driven (v0.4) | GroupChat — избыточен для линейного pipeline |
| **Pydantic AI** | Type-safe agents | Strict schemas из коробки, zero boilerplate | Молодой, меньше экосистемы |
| **smolagents** | Минималистичный | Простота, Hugging Face интеграция | Нет production checkpointing |

### SR-agent решение: **custom orchestrator поверх Anthropic SDK**

Почему не LangGraph:
- LangGraph абстрагирует именно то, что нам нужно контролировать вручную: передачу контекста в LLM и выполнение действий. Наш Orchestration Plane — это детерминированный код с HMAC, [DATA] wrapping и source_type rules. Если передать это LangGraph — framework становится векотором атаки (его state может быть модифицирован).
- HMAC на каждую запись памяти, human gate, append-only — всё это требует кастомной логики между LLM вызовом и state persistence.

**Что берём из LangGraph идей**: checkpointing pattern (Stage 1/2/3 boundaries), HITL approval pattern для out-of-band confirmation.

---

## 2. Память

### Ландшафт фреймворков

| Фреймворк | Хранилище | Retrieval | Запись | Особенности |
|-----------|-----------|-----------|--------|-------------|
| **Mem0** | Vector + KG + KV (три одновременно) | Семантический (параллельный по всем бэкендам) | LLM управляет, extraction pipeline | ~48K GitHub stars, $24M Series A, managed cloud или self-host |
| **Zep** | Knowledge Graph (Graphiti) | Graph traversal + temporal reasoning | Автоматическая экстракция фактов | Силён в entity relationships, временная логика |
| **LangMem** | Любой через LangGraph store | Semantic по умолчанию | LLM через tool calls | Только внутри LangChain/LangGraph |
| **Letta** | Pluggable backends | Configurable | LLM через in-context memory blocks | Глубокий контроль над state |
| **Кастомный JSONL** | Файлы | Явная адресация | Оркестратор | Полный контроль, нет зависимостей |

### SR-agent решение: **кастомный JSONL append-only + Knowledge Base с 3-model pipeline**

Почему не Mem0 / Zep:
- Все три фреймворка дают LLM доступ к write path памяти. Это именно тот вектор, который мы закрываем: `ALLOWED_MEMORY_ACTIONS = {"write_memory"}` — только через оркестратор с HMAC.
- Mem0 extraction pipeline — LLM решает что хранить и где. Для нас это неприемлемо: инъецированная модель может хранить вредоносные записи как "факты".
- Zep graph memory — Graphiti engine использует семантический поиск для retrieval. Retrieval poisoning vector остаётся открытым.
- Managed cloud (Mem0) — код клиентов уходит во внешний API.

**Что берём из Mem0 идей**: концепция трёх параллельных бэкендов (vector + structured + episodic) — применяем её к Knowledge Base, где нет LLM write path и retrieval poisoning невозможен.

---

## 3. Инструменты (Tools)

### Ландшафт инструментальных слоёв

| Подход | Пример | Что даёт |
|--------|--------|----------|
| **MCP (Model Context Protocol)** | Anthropic MCP, любой MCP-сервер | Стандарт обмена инструментами между агентами |
| **LangChain Tools** | `@tool` декоратор | Быстрое оборачивание функций в инструменты |
| **Function Calling** | OpenAI API, Anthropic API | Native tool definitions через API |
| **Pydantic AI Tools** | `@agent.tool` | Type-safe параметры |

### Статические анализаторы (специфично для домена)

| Инструмент | Тип | Скорость | Точность | Особенности |
|------------|-----|----------|----------|-------------|
| **Slither** | Статический AST анализ | < 1 сек/контракт | 80+ детекторов, low FP | Trail of Bits, золотой стандарт |
| **Aderyn** | Статический AST анализ (Rust) | Очень быстро | Verbose, много FP | Foundry-native, Markdown output |
| **Mythril** | Символьное выполнение | Медленно (минуты) | Глубокие state machines | Хорош для сложных путей |
| **Certora Prover** | Формальная верификация | Часы | Математическая гарантия | Для critical contracts |
| **Echidna / Medusa** | Fuzzing | Минуты-часы | Покрытие | Property-based testing |
| **Semgrep** | Pattern matching | Секунды | Кастомные правила | Легко добавлять детекторы |

Профессиональные аудиторы комбинируют: Slither + Aderyn (статика) + Echidna (фаззинг) + Mythril (символьное) + Certora (формальная верификация для high-value).

### SR-agent решение: **whitelist с hash-verification + Docker sandbox**

Почему не native MCP tool serving:
- MCP-сервер может изменить описание инструмента (tool supply chain attack) — именно это закрывает `description_hash` в TOOL_REGISTRY.
- LangChain `@tool` не даёт контроля над параметрами на уровне enum-whitelist: `run_command(cmd: str)` vs `run_slither(target: FilePath, detectors: list[SlitherDetector])`.

**Что берём**: Slither как основной статический анализатор (MVP), Aderyn как параллельный быстрый скан, Mythril опционально.

---

## 4. Guardrails

### Ландшафт фреймворков защиты

| Фреймворк | Подход | Сильные стороны | Слабые стороны |
|-----------|--------|-----------------|----------------|
| **NeMo Guardrails** (NVIDIA) | Colang DSL + dialog flow | Полный control над dialog pipeline, 5 interception stages, -40% overhead в 2026 | DSL overhead, сложная настройка |
| **Guardrails AI** | Input/output validation | Validators как плагины, легко добавлять схемы | Только валидация, не control flow |
| **LlamaGuard 4** | LLM-based safety classifier | Классификация output safety | Требует LLM вызов, latency |
| **Presidio** (Microsoft) | PII detection + anonymization | Stripped PII at ingress, 30+ entity recognizers | Только PII, не security |
| **Prompt Guard 2** | Injection detection | Inline injection detection | Только PI, не MI |
| **OpenGuardrails** | Unified configurable layer | Multi-framework унификация | Экспериментальный |

Стек который многие команды собирают: Presidio (PII strip) → Prompt Guard 2 (injection detect) → NeMo Guardrails (dialog policy) → LlamaGuard 4 (output classify) → schema validator (structured output).

### SR-agent решение: **детерминированный код, без LLM-based guardrails**

Почему не NeMo / Guardrails AI:
- **NeMo Guardrails** сам использует LLM для оценки — это создаёт зависимость от ещё одного LLM вызова, который сам может быть инъецирован. Для security-домена это неприемлемо.
- **Guardrails AI validators** часто используют LLM для проверки — та же проблема.
- **LlamaGuard** — LLM-based классификатор. MI attack может обойти LLM-based safety check так же, как обходит основной агент.

Наш подход: **все guardrails = детерминированный код**:
- Conjunction check: чистый Python, O(1)
- Mock detection: `pattern in test_code`, нет LLM
- Escalation triggers: `lambda` функции над typed полями
- HMAC verify: `hmac.compare_digest()`

Единственный случай где LLM-based классификация могла бы помочь — novel attack patterns. Но для MVP это `unknown_pattern` trigger → эскалация к человеку.

**Что берём из Guardrails идей**: концепция pipeline interception stages (до LLM / после LLM) — применяем в orchestrator/loop.py.

---

## 5. Планировщик

### Ландшафт паттернов планирования

| Паттерн | Описание | Когда применять |
|---------|----------|-----------------|
| **ReAct** | Reason + Act в цикле | Открытые задачи, неизвестная структура |
| **Plan-and-Execute** | Сначала план, потом выполнение | Сложные многошаговые задачи, нужен upfront plan |
| **for-loop (deterministic)** | Фиксированный список задач | Известный конечный список, нет рассуждений о порядке |
| **Graph-based (LangGraph)** | Nodes + edges + conditions | Production workflows с branching и rollback |
| **Tree of Thoughts** | Параллельные ветви рассуждений | Исследование пространства решений |
| **ReWOO** | Параллельные tool calls, один reasoning step | Эффективность при многих инструментах |

### SR-agent решение: **гибрид ReAct + for-loop + ReAct**

- **Stage 1** (Discovery) → ReAct: scope неизвестен, нужна адаптивная стратегия
- **Stage 2** (CheckRunner) → for-loop: список целей известен из Stage 1, нет рассуждений о порядке нужны
- **Stage 3** (Synthesis) → ReAct + extended thinking: пространство комбинаций неизвестно

Почему не LangGraph для планировщика:
- LangGraph graph-based orchestration отлично подходит для этой структуры (Stage 1→2→3 = три node-а с conditional edges). Это честная альтернатива нашему custom loop.
- **Компромисс**: LangGraph дал бы нам built-in checkpointing и HITL approval nodes бесплатно. Но мы теряем контроль над тем, что именно попадает в LLM context (LangGraph сам управляет state).

**Вывод**: для MVP — custom loop; если проект растёт — рассмотреть LangGraph для Phase 8 (Audit Pipeline) при условии, что Orchestration Plane (HMAC, [DATA] wrapping) остаётся нашим кодом под LangGraph.

---

## 6. I/O

### Ландшафт CLI и reporting

| Инструмент | Роль | Статус 2026 |
|------------|------|-------------|
| **Typer** | CLI argument parsing (type-hint based) | Де-факто стандарт для новых Python CLI, поверх Click |
| **Click** | CLI argument parsing (decorator-based) | Зрелый, Typer строится на нём |
| **Rich** | Terminal UI: progress bars, tables, syntax highlight | Интеграция с Typer — стандартный стек |
| **Pydantic** | Schema validation + serialization | v2, повсеместно используется |
| **SARIF** | Стандарт security findings для CI/CD | ISO стандарт, GitHub/VS Code native support |
| **Markdown** | Human-readable report | Везде работает: GitHub, Notion, PDF export |

Рекомендуемый стек 2026: **Typer + Rich** для новых проектов.

### SR-agent решение: **Typer + Rich + Markdown report**

- CLI: Typer (поверх Click) — type hints вместо декораторов, меньше boilerplate
- Progress stream: Rich `Progress` + `Live` — нативная поддержка multi-task прогресс-баров
- Final report: Markdown (`.md`) — работает везде, `--output` флаг
- Machine output: JSONL с HMAC (Episodic Memory)

Опционально: SARIF формат для CI/CD интеграции (открытый вопрос из io.md).

---

## 7. LLM Core

### Ландшафт inference и routing фреймворков

| Уровень | Инструмент | Роль |
|---------|------------|------|
| **API gateway / routing** | **LiteLLM** | Единый endpoint для 100+ провайдеров, virtual keys, fallbacks, cost tracking |
| **Local inference (dev)** | **Ollama** | Две команды запустить модель, Metal на M-серии Mac, offline |
| **Local inference (production)** | **vLLM** | 6-16x throughput vs Ollama под нагрузкой, PagedAttention, NVIDIA GPU |
| **Local inference (embedded)** | **llama.cpp** | Минимальные зависимости, везде работает, GGUF формат |
| **Fine-tuning** | **Unsloth** / **TRL** | 2-4x ускорение fine-tuning на consumer GPU |
| **Embedding** | **sentence-transformers** | gemma-300M и аналоги через HuggingFace |

### Hybrid pattern (рекомендуется 2026)

```
Prototype:   Ollama на ноутбуке (Qwen3-4B локально)
Production:  vLLM на GPU сервере (тот же Qwen3-4B)
Routing:     LiteLLM как proxy — одинаковый client code в обоих случаях
Cloud:       Claude Opus через Anthropic API напрямую (не через LiteLLM — для ZDR)
```

### SR-agent решение: **Ollama для MVP + LiteLLM как опция + Anthropic SDK напрямую**

- **Stage 1/3 → Claude Opus**: Anthropic SDK напрямую. LiteLLM не нужен — нет multi-provider routing для Opus (только Anthropic), ZDR требует прямой API.
- **Stage 2 → Qwen3-4B local**: Ollama в Docker контейнере (`ollama/ollama` официальный образ) для MVP, vLLM если нужна скорость.
- **LiteLLM**: опционально добавить как abstraction layer для Stage 2 routing — позволит переключаться между Ollama/vLLM/Groq без изменения client code.
- **Fine-tuning pipeline**: Unsloth + TRL (на Bastet датасете) для Qwen3-4B Stage 2.

---

## Общий вывод: что берём, что пишем сами

| Модуль | Фреймворк | Что берём | Почему custom |
|--------|-----------|-----------|---------------|
| Оркестратор | LangGraph | Идеи checkpointing, HITL | Нельзя отдать context management фреймворку |
| Память | Mem0/Zep | Концепция multi-store | LLM write path — нельзя отдавать |
| Инструменты | MCP стандарт | Tool definition format | description_hash verification требует custom registry |
| Guardrails | NeMo концепция pipeline stages | Input/output interception структура | Нельзя использовать LLM-based guardrails для MI-defence |
| Планировщик | LangGraph (future), ReAct паттерн | Stage структура | Гибрид ReAct+for-loop не покрывается одним фреймворком |
| I/O | **Typer + Rich** | Полностью берём | Нет security reason писать custom CLI |
| LLM Core | **Ollama + Anthropic SDK**, LiteLLM опционально | Берём inference stack | Custom только ModelRouter поверх |

**Ключевой принцип**: берём фреймворк там, где он не управляет тем, что мы должны контролировать детерминированно (context assembly, memory write, action execution). Typer/Rich/Ollama/Slither — берём целиком, они не в Orchestration Plane.
