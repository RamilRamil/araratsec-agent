# Исследование: Модуль LLM-ядро

## Ключевые решения

| Решение | Обоснование |
|---------|-------------|
| Разные модели для разных задач | Качество / стоимость / конфиденциальность варьируются по задачам |
| Stage 1/3 → Claude API (Opus) | Требуют лучшего рассуждения, нет альтернативы по качеству |
| Stage 2 → локальная fine-tuned (Qwen3-4B) | ASR 1.7%, экономия стоимости, код не уходит во внешний API |
| Extended thinking на всех Stage 1/3 вызовах | MI resistance × 5, не опция — требование безопасности |
| Bastet датасет → training data для Stage 2 | 849 экспертных примеров → fine-tuning precondition-чеклиста |
| `human_relayed_tool` source type для MVP | Человек-прокси: содержимое от инструмента, но неверифицируемо оркестратором |

---

## 1. Model Routing

Один размер не подходит для всех задач. Оркестратор выбирает модель по типу задачи:

```
Stage 1 Discovery    → Claude Opus (API, extended thinking)
Stage 2 CheckRunner  → Qwen3-4B fine-tuned (локально)
Stage 3 Synthesis    → Claude Opus (API, extended thinking)
PoC writing          → Qwen3-Coder (локально) / Claude Sonnet (API)
Conjunction check    → чистый код, без модели
Guardrails eval      → чистый код, без модели
```

Конфигурация через environment variables — легко переключить без изменения архитектуры:

```python
MODEL_CONFIG = {
    "stage1": env("SR_STAGE1_MODEL", default="claude-opus-4-8"),
    "stage2": env("SR_STAGE2_MODEL", default="qwen3-4b-local"),
    "stage3": env("SR_STAGE3_MODEL", default="claude-opus-4-8"),
    "poc":    env("SR_POC_MODEL",    default="qwen3-coder-local"),
}
```

---

## 2. Extended Thinking — требование безопасности

Из исследования 2503.16248v3: **thinking trajectories в 5 раз эффективнее против MI** чем обычный промптинг.

Extended thinking включается на **всех** вызовах Stage 1 и Stage 3 — не выборочно:

```python
# Не знаешь заранее какой вызов будет атакован
# Extended thinking = baseline security, не опция

stage1_response = claude.messages.create(
    model="claude-opus-4-8",
    thinking={"type": "enabled", "budget_tokens": 8000},
    messages=[...]
)
```

Дополнительно: расширенное мышление улучшает качество сложных задач — security и quality совпадают.

---

## 3. Гибридная архитектура: Local + API

### Зачем локальная модель для Stage 2

Stage 2 — самый частый вызов: один на каждую цель из Stage 1 (8-15 вызовов за аудит). Fine-tuned Qwen3-4B:

```
ASR (attack success rate): 85% → 1.7% после fine-tuning (из 2503.16248v3)
Стоимость: $0 per call (локально)
Конфиденциальность: код не покидает машину
Скорость: на consumer GPU достаточно быстро для CheckRunner
```

Stage 2 задача структурированная и повторяемая — хорошо подходит для меньшей специализированной модели.

### Запуск Ollama в Docker

Не нативная установка — официальный образ `ollama/ollama` в docker-compose:

```yaml
services:
  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama   # модели персистентны между перезапусками
    # для NVIDIA GPU раскомментировать deploy.resources.reservations.devices

volumes:
  ollama_models:
```

`LocalClient` обращается к `http://ollama:11434/v1` внутри compose-сети. При переходе на vLLM меняется только базовый URL — клиентский код не трогаем.

### Privacy и NDA

Клиентский код под NDA. При использовании Claude API:
- **Anthropic ZDR** (Zero Data Retention): данные не хранятся, не используются для обучения
- Доступно для enterprise API — стандартный выбор для аудиторов

Для максимальной изоляции Stage 2 (самый частый доступ к коду) → всегда локально.

---

## 4. Fine-tuning Stage 2 модели

### Что нужно

Qwen3-4B должен надёжно применять 12 preconditions к функциям контракта и возвращать structured JSON. Нужны обучающие примеры:

```
Input:  исходный код функции + список preconditions
Output: {bastet_tag, severity, preconditions_active, mitigations}
```

### Источник training data

**Bastet датасет** (2606.03387) — 849 экспертно размеченных находок Code4rena аудитов:
- До этого мы рассматривали его как evaluation датасет
- Для Stage 2 он также является training data: реальные функции → экспертные теги

```
849 примеров × (function_code, preconditions) → (finding JSON) = base training set
+ MI attack examples → correct rejection
→ fine-tuned Qwen3-4B: ASR ~1.7%, structured output надёжный
```

Лицензия Bastet: CC BY-NC — для некоммерческого обучения подходит.

---

## 5. «Человек как API» — текущий MVP паттерн

### Текущая схема

```
Пользователь запускает skill вручную
  → получает результат
  → вставляет в разговор: "вот результат security-auditor для Vault.sol"
  → агент использует как tool output
```

### source_type: human_relayed_tool

Содержимое от инструмента (пользователь не меняет вывод), но оркестратор не может верифицировать это напрямую:

```python
# Прямой вызов (будущее):
{
    "source_type": "tool_output",
    "tool": "security-auditor",
    "target": "Vault.sol",
    "hmac": "a3f9..."  # оркестратор подписал сам
}

# MVP — человек-прокси:
{
    "source_type": "human_relayed_tool",
    "claimed_tool": "security-auditor",
    "claimed_target": "Vault.sol",
    "transitional": True,  # заменится прямым API вызовом
    "hmac": "b7d2..."      # HMAC на содержимое, но не верифицирует источник
}
```

Разница: не в доверии к пользователю, а в верифицируемости оркестратором. При появлении API — `human_relayed_tool` заменяется на `tool_output`, архитектура не меняется.

---

## 6. File Bridge — промежуточный паттерн

Улучшение над `human_relayed_tool`: внешний LLM пишет результат в предопределённую папку, SR-agent читает как файл. Нет ручного copy-paste, результат версионируем и аудируем.

```
Claude (отдельная сессия)
  → запускает security-auditor на Vault.sol
  → сохраняет /shared/results/security-auditor-Vault.sol.json
        ↓
SR-agent оркестратор
  → read_file("/shared/results/security-auditor-Vault.sol.json")
  → source_type: "external_llm_output"
```

### Структура результирующего файла

```json
{
  "tool": "security-auditor",
  "target": "Vault.sol",
  "timestamp": "2026-06-24T10:00:00Z",
  "content_hash": "sha256:a3f9c2...",  ← writing LLM считает сам
  "findings": [...]
}
```

### Новый source_type: external_llm_output

```python
TRUST_HIERARCHY = {
    "human_input":           4,  # наивысший
    "tool_output":           3,  # детерминированный инструмент
    "external_llm_output":   2,  # внешний LLM через file bridge
    "human_relayed_tool":    2,  # человек-прокси (переходный)
    "llm_inference":         1,  # внутреннее рассуждение агента
}
```

### Требования безопасности file bridge

```
1. File permissions: только writing LLM пишет, SR-agent только читает
   → предотвращает подмену result файла третьей стороной

2. content_hash в файле: базовая tamper detection
   → не HMAC с нашим ключом (writing LLM его не знает)
   → но оркестратор проверяет sha256(findings) == content_hash

3. Freshness check: timestamp не старше N минут
   → предотвращает replay старых результатов
```

### Upgrade путь

```
Сейчас:    human_relayed_tool  (ручной copy-paste)
  ↓
Interim:   external_llm_output (file bridge, автоматически)
  ↓
Target:    tool_output          (прямой API вызов, HMAC от оркестратора)
```

Архитектура не меняется при переходе — только source_type и канал доставки.

---

## 7. Context Window Management per Model

```
Claude Opus (API):     200K токенов → Stage 1/3 могут получать полный SIG + findings
Qwen3-4B (локально):  ~32K токенов → Stage 2 получает одну функцию за раз (нормально)
Qwen3-Coder (локально): ~32K токенов → PoC writing: одна находка + контракт
```

Оркестратор адаптирует контекст под модель: не пытается уместить всё в 32K для локальной модели.

---

## 8. Открытые вопросы

- **ZDR verification**: как убедиться что ZDR включён для конкретного API ключа? Нужна проверка при инициализации.
- **Local model deployment**: Ollama vs llama.cpp vs vLLM для Qwen3-4B? Зависит от железа пользователя.
- **Fine-tuning pipeline**: один раз при установке. `scripts/finetune/finetune_stage2.py` (Unsloth + QLoRA) → адаптер в `adapters/qwen3-4b-stage2/` → `ollama create sr-stage2`. Переобучение при появлении новых Bastet примеров или если ASR regression gate нарушен. ✓ Resolved
- **Model versioning**: если Anthropic обновит Claude Opus — нужно ли перепроверять MI resistance? Принципиально да.
- **Cost estimation per audit**: Stage 1/3 на Opus с extended thinking — какой примерный budget tokens? Нужна оценка на реальном аудите.
- **Fallback**: если локальная модель недоступна — Stage 2 переходит на Claude API с пониженным доверием?
