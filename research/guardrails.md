# Исследование: Модуль Guardrails

## Ключевые решения

| Решение | Обоснование |
|---------|-------------|
| Guardrails = семантическая валидация | Оркестратор проверяет структуру, Guardrails проверяет смысл |
| Conjunction check перед PoC | Дешёвый детерминированный фильтр до дорогой верификации |
| 4 статуса finding | confirmed / mock_review / unverified / false_positive |
| Mock-паттерны → автоэскалация | Статический анализ теста без LLM |
| 8 триггеров эскалации к человеку | Покрывают необратимость, неопределённость, незавершённость |
| Санитизация после [DATA] обёртки | Сначала граница «это данные», потом характеристика содержимого |

---

## 1. Роль Guardrails vs Оркестратор

```
Оркестратор проверяет СТРУКТУРУ:
  ├── JSON схема валидна?
  ├── tool в whitelist?
  ├── HMAC корректен?
  └── аргументы нужного типа?
       ↓ структурно валидно — передаёт в Guardrails

Guardrails проверяет СМЫСЛ:
  ├── severity соответствует preconditions?
  ├── этот input безопасно подавать в LLM?
  ├── находка требует эскалации к человеку?
  └── тест использует реалистичные допущения?
```

Структурно валидная запись может быть семантически неверной. Пример: `severity: medium` корректный enum — оркестратор пропускает. Guardrails проверяет: а соответствует ли это 4 активным preconditions без митигации?

---

## 2. Severity Validation и SCB

### Проблема

LLM систематически тянет Low и Critical к Medium — **Severity Centrality Bias** (из 2606.03128). Для аудита критично: заниженный Critical может стоить миллионов.

### Conjunction Check (детерминированный, дёшево)

Из AttackPathGNN: если ANY митигация присутствует — severity коллапсирует. AND-логика:

```python
def check_severity(finding: Finding) -> SeverityVerdict:
    active = [p for p in PRECONDITIONS_1_12 if finding.preconditions[p]]
    mitigations = finding.mitigations_present

    if mitigations:
        # Conjunction logic: любая защита снижает severity
        max_allowed = Severity.MEDIUM
        if finding.severity > max_allowed:
            return SeverityVerdict(
                override=max_allowed,
                reason=f"Mitigation present: {mitigations}"
            )

    if len(active) >= 4 and not mitigations:
        # Все ключевые preconditions активны, защит нет
        min_expected = Severity.HIGH
        if finding.severity < min_expected:
            return SeverityVerdict(
                override=min_expected,
                reason=f"SCB correction: {len(active)} preconditions active, no mitigation"
            )

    return SeverityVerdict(confirmed=finding.severity)
```

### Двухступенчатая верификация (из практики аудита)

```
Finding от LLM
    ↓
1. Conjunction check (Guardrails, O(1), без LLM):
   - severity скорректирована если нужно
    ↓
2. Если severity ≥ High → PoC тест (лёгкая модель: Qwen3-4B / local):
   - Foundry тест написан и запущен в Docker sandbox
   - Прошёл → проверить на mock-паттерны
   - Упал → статус unverified
    ↓
3. Если severity = Critical → human review до отчёта
```

Conjunction check делает PoC только для High/Critical — не для каждой находки.

---

## 3. Четыре статуса Finding после верификации

```python
class FindingStatus(Enum):
    CONFIRMED    = "confirmed"
    # PoC прошёл, mock-допущения реалистичны (human подтвердил)

    MOCK_REVIEW  = "mock_review"
    # PoC прошёл, но тест использует vm.mockCall / vm.assume
    # → нужен human для проверки реалистичности допущений

    UNVERIFIED   = "unverified"
    # Checklist говорит High, PoC не воспроизвёл
    # Причина неясна: false positive / плохой тест / сложный контекст
    # → нужен human или более мощная модель

    FALSE_POSITIVE = "false_positive"
    # Несколько независимых проверок: не эксплуатируется
```

`unverified` — не «выброси», а «нужно больше анализа». Автоматическое решение здесь невозможно.

---

## 4. Mock Detection

Из практики аудита: тест может «воспроизвести» уязвимость только из-за нереалистичных допущений в моках.

```python
MOCK_PATTERNS = [
    "vm.mockCall",       # подменяет ответ любого контракта
    "vm.mockCallExpects",
    "vm.assume",         # задаёт произвольные допущения для фаззинга
    "MockERC20",         # кастомный мок токена
    "MockOracle",        # кастомный мок оракула
    "deal(",             # Foundry: выдаёт ETH адресу
    "hoax(",             # Foundry: deal + prank в одном
]

def check_test_realism(test_code: str) -> TestQuality:
    found = [p for p in MOCK_PATTERNS if p in test_code]
    if found:
        return TestQuality(
            status=FindingStatus.MOCK_REVIEW,
            flags=found,
            reason="Verify mock assumptions are realistic before confirming severity"
        )
    return TestQuality(status="clean")
```

Статический pattern-matching, никакого LLM. Guardrails находит `vm.mockCall` → автоэскалация к человеку.

---

## 5. Input Sanitization

### Порядок: [DATA] обёртка → санитизация внутри

Сначала устанавливается граница («это данные»), потом характеризуется содержимое:

```
Raw tool output
    ↓
[DATA START tool=X path=Y]   ← оркестратор устанавливает границу
    ↓
Guardrails sanitizes inside [DATA]:
  1. Unicode normalization: homoglyphs → ASCII
     (кириллическое 'а' → латинское 'a')
  2. Detect: Base64 блоки, Morse паттерны, zero-width chars
  3. Flag — не блокировать
     (код легитимно содержит Base64: подписи, encoded data)
    ↓
[DATA START tool=X path=Y encoding_flags=base64,homoglyphs]
<нормализованный контент>
[DATA END]
    ↓
LLM: (a) это данные, (b) содержит подозрительное кодирование
```

### Почему не блокировать

Смарт-контракты содержат Base64 легитимно (IPFS хэши, подписи, ABI-encoded данные). Блокировка сломает анализ. Флаг в заголовке блока даёт LLM контекст без потери данных.

---

## 6. Восемь триггеров эскалации к человеку

```python
ESCALATION_TRIGGERS = {

    # Необратимые действия
    "irreversible_action": lambda a: a.type in WRITE_EXECUTE_TOOLS,

    # Память
    "memory_status_change": lambda r: r.status in REQUIRES_HUMAN_CONFIRMATION,

    # Находки по severity
    "critical_finding": lambda f: f.severity == Severity.CRITICAL,

    # Верификация
    "unverified_high": lambda f: (
        f.severity >= Severity.HIGH and f.status == FindingStatus.UNVERIFIED
    ),
    "mock_test": lambda t: t.status == FindingStatus.MOCK_REVIEW,

    # Логические противоречия
    "contradicting_findings": lambda f: (
        f.location in previous_findings and
        previous_findings[f.location].verdict != f.verdict
    ),

    # Неизвестные паттерны
    "unknown_pattern": lambda f: (
        f.bastet_tag is None and
        sum(f.preconditions.values()) == 0
    ),

    # Ресурсы
    "resource_limit_approaching": lambda s: (
        s.token_budget_used > 0.85 or
        s.iterations > MAX_ITERATIONS * 0.9
    ),
}
```

### Почему каждый требует человека

| Триггер | Почему нельзя автоматически |
|---------|----------------------------|
| Необратимое действие | Нельзя отменить после выполнения |
| Memory verified/skip | Закрывает область от анализа навсегда |
| Critical finding | Цена ошибки слишком высока |
| Unverified High | Причина неизвестна: FP / плохой тест / сложный контекст |
| Mock-тест | Реалистичность допущений требует экспертной оценки |
| Противоречие | Агент не может решить кто прав — нужен контекст |
| Неизвестный паттерн | Новый класс уязвимости или FP — оба важны |
| Лимит ресурсов | Молчаливая неполнота опаснее явной остановки |

---

## 7. Полная схема Guardrails в пайплайне

```
INPUT PATH:
  Raw external content
    → [DATA] wrap (оркестратор)
    → Sanitize inside [DATA] (Guardrails)
    → encoding_flags в заголовке
    → LLM Context Plane

OUTPUT PATH:
  LLM JSON output
    → Schema validation (оркестратор)
    → Guardrails semantic checks:
        ├── Conjunction check → severity correction
        ├── Escalation trigger check → human / proceed
        └── If write_memory → source_type + status rules
    → Action execution (оркестратор)
    → If finding with severity ≥ High → PoC test pipeline
        ├── Run test in Docker sandbox
        ├── Mock detection
        └── Final status: confirmed / mock_review / unverified
```

---

## 8. Открытые вопросы

- **Conjunction threshold**: при скольких активных preconditions severity = High vs Critical? Нужна калибровка на реальных данных (Bastet датасет).
- **unverified timeout**: если finding остаётся в `unverified` статусе N дней без human review — что происходит? Автоматически в отчёт с пометкой?
- **Novel pattern handling**: как документировать неизвестный паттерн для пополнения Knowledge Base? Это новый workflow.
- **Contradiction resolution**: если сессии противоречат — какую информацию передавать человеку? Нужен diff-view обеих версий.
- **SCB калибровка**: пороги conjunction check (≥4 preconditions → High) нужно верифицировать на Bastet датасете, не задавать вручную.
