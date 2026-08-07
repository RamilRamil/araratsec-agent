# Исследование: Evaluation Infrastructure

## Проблема

Агент недетерминирован. Тот же контракт → разные findings при разной temperature, версии модели, изменении промпта. Без eval инфраструктуры невозможно понять:
- После какого изменения агент перестал находить reentrancy
- Почему Stage 3 не идентифицировал комбинированную атаку
- Не регрессировал ли Stage 2 после fine-tuning

---

## Два класса поведения → два подхода к тестированию

```
Orchestration Plane (детерминированный)    → pytest, обычные unit/integration тесты
  HMAC verify, conjunction check,
  mock detect, whitelist enforcement

LLM Context Plane (недетерминированный)    → eval инфраструктура
  Stage 1 нашёл правильные цели?
  Stage 3 идентифицировал комбинацию?
  Агент не зациклился?
  reasoning осмысленный?
```

Детерминированный слой тестируем классически. Недетерминированный — через eval.

---

## Три слоя eval инфраструктуры

### 1. Трассировка (Observability)

Каждый LLM-вызов логируется: что ушло → что вернулось → сколько токенов → какой инструмент вызвался.

```python
@dataclass
class LLMTrace:
    trace_id: str
    session_id: str
    stage: int                    # 1 | 2 | 3
    task_type: str                # stage1_discovery, stage2_check, ...
    model: str                    # claude-opus-4-8, qwen3-4b-local
    input_messages: list[dict]    # полный контекст (без секретов)
    output: AgentAction           # structured response
    thinking_excerpt: str | None  # первые 500 chars thinking trajectory
    tokens_used: int
    latency_ms: int
    timestamp: datetime
```

Хранится в `traces/{session_id}.jsonl` — отдельно от Episodic Memory (не HMAC-подписанные, не часть аудитного контекста).

**Без трассировки**: "агент зациклился, но непонятно на каком шаге и почему". С трассировкой: открываешь traces/ и видишь точный LLM input/output на шаге N.

### 2. Eval датасет

Набор `(target_contract, expected_criteria)` — не точный ожидаемый ответ, а **критерии**:

```python
@dataclass
class EvalCase:
    case_id: str
    contract_path: str              # путь к контракту в eval/contracts/
    known_vulnerabilities: list[str]  # ["reentrancy-withdraw", "oracle-manipulation-swap"]
    expected_criteria: list[EvalCriterion]

@dataclass
class EvalCriterion:
    criterion_id: str
    description: str                # "Stage 1 должен поставить withdraw() в приоритетные цели"
    criterion_type: Literal[
        "tool_called",              # конкретный инструмент был вызван
        "finding_present",          # finding с таким bastet_tag найден
        "severity_correct",         # severity не занижен/завышен
        "no_infinite_loop",         # агент завершил Stage за MAX_ITERATIONS
        "memory_not_leaked",        # данные не покинули репо
        "escalation_triggered",     # нужная эскалация произошла
    ]
    params: dict                    # {"tag": "Reentrancy", "min_severity": "high"}
    weight: float                   # важность критерия (0.0-1.0)
```

**Источник контрактов**: Damn Vulnerable DeFi (DVDF) — open-source набор намеренно уязвимых DeFi контрактов. Известные уязвимости → можно проверять recall.

### 3. LLM-as-Judge + Regression Pipeline

```
Eval run:
  for case in eval_dataset:
    run sr-agent audit on case.contract
    for criterion in case.expected_criteria:
      score = check_criterion(criterion, audit_result)
    case_score = weighted_average(scores)

  overall_score = mean(case_scores)
  report: {score, regressions_vs_baseline, per_case_breakdown}
```

Судья для `criterion_type = finding_present / severity_correct` — детерминированный код (проверяем structured JSON finding, не текст). LLM-as-Judge нужен только для свободного текста (reasoning качество, escalation обоснование).

---

## Eval фреймворки

| Инструмент | Подход | Подходит |
|------------|--------|----------|
| **Langfuse** | Open source, self-hosted, framework-agnostic, трассировка + eval + prompt management | ✓ Выбрано |
| **LangSmith** | LangChain ecosystem | ✗ Завязан на LangChain |
| **Arize Phoenix** | Open source, LLM eval + трассировка | ✓ Альтернатива |
| **Helicone** | Proxy-based трассировка | ✓ Проще, но нет eval |
| **Кастомный JSONL** | traces/ директория | ✓ Fallback если Langfuse недоступен |

**Решение**: Langfuse self-hosted с самого начала — не откладывать на "после MVP".

```
sr_agent/eval/tracer.py   ← тонкая обёртка, graceful degradation если Langfuse выключен
claude_client.py          ← @observe() или Tracer.generation() на каждом вызове
eval/runner.py            ← постит scores в Langfuse Dataset
```

**Изоляция**: Langfuse — отдельный Docker сервис с отдельными volumes. У агента нет инструмента `read_trace`. Langfuse не имеет доступа к `memory/`. Трейсы ≠ агентная память.

---

## Метрики

### Security-специфичные (primary)

```
Recall@known_vulns = найденные_известные / все_известные_уязвимости
Precision@findings = confirmed_findings / all_findings
ASR (MI resistance) = заблокированные_атаки / все_атаки  ← уже в tasks.md
FPR = false_positives / all_findings
```

### Agent health (secondary)

```
Loop completion rate = сессии_завершённые_без_loop / все_сессии
Stage2 per-target latency (p50, p95)
Token budget utilization (не должен постоянно хитить 85%)
Escalation rate (слишком высокий → агент не уверен в себе)
```

---

## Regression gate

При изменении промпта / модели / fine-tuning:

```
Recall@known_vulns  ≥ 0.80   (не пропускать >20% известных уязвимостей)
FPR                 ≤ 0.20   (не больше 20% ложных срабатываний)
ASR                 ≤ 0.05   (MI resistance — из spec.md SC-001)
Loop completion     ≥ 0.95   (агент не зависает)
```

Если любой порог нарушен → блокировать изменение, расследовать по traces/.

---

## Открытые вопросы

- **Eval контракты**: только DVDF или также реальные аудированные протоколы (с известными исправленными уязвимостями из Code4rena)?
- **LLM-as-Judge для reasoning**: нужен ли отдельный judge-промпт или достаточно структурных критериев?
- **Eval vs production memory**: traces не должны попадать в Episodic Memory агента — нужна явная изоляция директорий.
- **Eval периодичность**: при каждом коммите (дорого, ~30 мин) или по расписанию (ночью)?
