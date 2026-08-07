# Анализ источника: Zealynx — Agentic DeFi Security

## Метаданные
- **Тип**: Practitioner research article (консалтинг/аудит)
- **Автор**: Zealynx (zealynx.io)
- **URL**: zealynx.io/research/adversarial-security/agentic-defi-security
- **Источник**: blockthreat.com newsletter
- **Контекст**: 2026, пишут про реальные инциденты (Bankr/Grok май 2026, ElizaOS, Walbi)

---

## 1. СУТЬ

DeFi-агенты (treasury management, trading, liquidations) образуют новую критическую поверхность атаки: «протокол может быть безупречно аудирован на уровне Solidity и всё равно потерять средства — потому что привилегированный актор, вызывающий контракт, это языковая модель, которую можно манипулировать текстом». Защита должна быть в коде на границе привилегий, а не в промпте.

---

## 2. МЕТОД

Practitioner research: реальные инциденты + OWASP ASI Framework + аудиторский чеклист. Не эксперимент — обобщение случаев и архитектурных принципов.

### Три роли агентов в DeFi (2026 реальность)

| Роль | Функция | Критическая уязвимость |
|------|---------|----------------------|
| Treasury CFO | Ротация капитала, 8-12% APY для DAO | «Если единственная защита — строчка в system prompt» |
| Trading Desk | Сплит ордеров, cross-chain rebalancing | Dual oracle attack: off-chain feed corrupting |
| Liquidator/Borrower | Мониторинг collateral ratio, millisecond liquidations | Correlated behavior → liquidation cascades |

### Реальный инцидент: Bankr/Grok, май 2026 (три шага)

```
Шаг 1: Attacker отправляет Bankr Club Membership NFT в кошелёк Grok
        → NFT автоматически расширяет permissions кошелька (включая swaps/transfers)
        → без подписи жертвы

Шаг 2: Attacker постит инструкцию в ответе на X в кодировке Морзе
        → обходит input filters (промпт-уровень)

Шаг 3: Agent декодирует → выполняет transfer ~3B DRB (~$150K-180K)
        → ~80-88% возвращено под давлением (НЕ recovery mechanism)
```

**Урок**: «Защита на уровне промпта и политик была defeated path'ом на уровне permissions».

### OWASP ASI Framework (декабрь 2025)

| Инцидент | OWASP категория |
|----------|----------------|
| NFT тихо расширяет permissions | Identity and privilege abuse |
| Morse encoding bypass | Agent goal hijack |
| Несанкционированный transfer | Tool misuse |
| Memory с инъекцией | Memory and context poisoning |
| Синхронные ликвидации | Cascading failures |

### CrAIBench (упоминается как benchmark)

150+ blockchain tasks + 500+ context-manipulation test cases на ElizaOS с реальным Ethereum и X.
Вывод: «модели значительно более уязвимы к memory injection, чем к prompt injection, а prompt-based defenses фундаментально недостаточны».

→ **Это независимое подтверждение статьи 2503.16248v3** (наш основной источник по MI).

### 10-пунктовый аудиторский чеклист (по приоритету)

```
1. Privilege Boundary    — максимальное unilateral действие: в коде или только в промпте?
2. Escalation Paths      — может ли входящий актив (NFT, token, airdrop) расширить permissions?
3. Context Surfaces      — карта всех каналов ввода, memory stores, external feeds
4. Memory Integrity      — тест именно memory injection (не только prompt injection)
5. Encoding Handling     — Morse, Base64, homoglyphs, role-play framing
6. Tool Supply Chain     — MCP серверы и дескрипторы зафиксированы? Могут ли инъектировать?
7. Feed Trust            — off-chain данные могут override нормальное рассуждение?
8. Kill Switch           — hard code-level pause, независимый от агента
9. Correlated Failure    — несколько агентов на одной модели/стратегии
10. Decision Auditability — можно ли восстановить и объяснить решение постфактум?
```

---

## 3. СКЕПТИК

**Тип источника**: консалтинг, не peer-reviewed. Но опирается на реальные инциденты (Bankr/Grok задокументирован) и ссылается на TradeTrap paper (декабрь 2025) и CrAIBench.

**Что заслуживает высокого доверия**:
- Bankr/Grok инцидент — задокументированный реальный случай, $150K+ потерь
- Независимое подтверждение MI > PI из CrAIBench — совпадает с 2503.16248v3
- NFT-как-вектор-расширения-permissions — конкретный новый attack vector, ранее не разбиравшийся
- «Защита в коде, не в промпте» — прямое подтверждение нашей Orchestration Plane архитектуры

**Что требует дополнительной проверки**:
- TradeTrap paper (декабрь 2025) упоминается без ссылки — найти и проанализировать отдельно
- CrAIBench: 150+ tasks / 500+ test cases — публично доступен? Можем использовать для FR-019?
- ERC-8004 Identity Standard — реально deployed? Поискать спецификацию

**Корреляционный риск ликвидаций**: интересная системная угроза, но для нашего MVP не в приоритете — SR-agent не liquidation bot.

---

## 4. МОДУЛЬ

- [x] **Guardrails** — 10-пунктовый чеклист = ready-made audit framework для нашего слоя
- [x] **Память** — независимое подтверждение MI > PI, encoding bypass как attack vector
- [x] **Инструменты** — NFT/token escalation как новый тип поверхности атаки
- [x] **Оркестратор** — kill switch, decision auditability
- [x] **I/O** — encoding handling (Morse, Base64, homoglyphs)

---

## 5. РЕШЕНИЕ

**5.1 NFT / входящий актив как attack surface (НОВОЕ)**

Атаку Bankr/Grok мы не рассматривали: **входящий актив автоматически расширяет permissions**. Для SR-agent это означает:

```python
# Guardrail: ЛЮБОЕ расширение permissions требует явного одобрения
# через out-of-band канал — не через агента
class PermissionChangeEvent:
    trigger: str         # "NFT received", "token transfer", "airdrop"
    current_perms: set
    proposed_perms: set
    # → ВСЕГДА out-of-band confirmation, даже если trigger кажется безопасным
```

Принцип: агент не должен иметь возможности расширить свои собственные permissions ни через какой канал.

**5.2 Encoding bypass → Guardrails sanitization layer**

Morse, Base64, homoglyphs, role-play framing — всё это обходы на уровне текста. Для нашего агента-аудитора:

```python
# Перед подачей любого external content в LLM Context Plane:
def sanitize_input(text: str) -> str:
    # 1. Detect and flag encoded content (Morse, Base64, hex)
    # 2. Normalize unicode (homoglyphs → ASCII)
    # 3. Strip role-play framing ("Ignore previous instructions", "You are now...")
    # 4. Wrap in explicit data delimiter
    return f"[DATA START]\n{cleaned}\n[DATA END]"
```

Sanitization живёт в Orchestration Plane — до попадания в LLM Context Plane.

**5.3 CrAIBench → кандидат для FR-019**

500+ context-manipulation test cases на blockchain задачах — это готовый evaluation suite для нашего FR-019 (воспроизводимый набор MI-атак). Найти публичный доступ и сравнить с нашими сценариями.

**5.4 10-пунктовый чеклист → self-audit SR-agent**

Ironically: наш агент-аудитор сам должен проходить этот чеклист. Каждый пункт маппится на конкретный защитный механизм:

| Пункт | Наш механизм |
|-------|-------------|
| 1. Privilege Boundary | Whitelist в Orchestration Plane (FR-007) |
| 2. Escalation Paths | Out-of-band confirmation для любого permission change |
| 3. Context Surfaces | Карта всех входных каналов в spec (FR-003) |
| 4. Memory Integrity | Подписи записей памяти (FR-014) |
| 5. Encoding Handling | Sanitization layer перед LLM |
| 6. Tool Supply Chain | Инструменты изолированы, описания зафиксированы |
| 7. Feed Trust | Результаты инструментов = данные, не инструкции (FR-003) |
| 8. Kill Switch | Circuit breaker в оркестраторе (Orchestration Plane) |
| 9. Correlated Failure | Для MVP: single agent, вопрос снят |
| 10. Decision Auditability | Append-only трассировка (FR-019) |

Все 10 пунктов уже закрыты нашей архитектурой — это валидация spec.md.

**5.5 «Dual oracle attack» → расширение PATTERN-01**

Статья вводит новый вектор: **off-chain oracle manipulation** (corrupting external data feeds перед тем как агент их прочитает) — дешевле и эффективнее on-chain manipulation.

Расширяем PATTERN-01 из 2606.05418:

```
PATTERN-01a: AMM on-chain oracle manipulation (оригинал)
PATTERN-01b: Off-chain feed injection (НОВОЕ)
  → агент читает внешний API/feed перед торговым решением
  → feed содержит manipulated data или injected instructions
  → для SR-agent: результаты любого внешнего инструмента = потенциальный MI вектор
```

---

## 6. ВОПРОСЫ

- **TradeTrap paper (декабрь 2025)**: найти полную статью, проанализировать по нашему шаблону. Упоминается как доказательство нестабильности LLM-trading-агентов под атаками.
- **CrAIBench**: публично доступен? Repo/paper? Может стать нашим FR-019 evaluation suite.
- **ERC-8004**: спецификация deployed 2026 — изучить как стандарт идентификации агентов. Влияет ли на I/O модуль?
- **NFT permission escalation**: есть ли уже известные случаи кроме Bankr/Grok? Насколько это general pattern?
- **Least agency principle**: статья даёт хорошее определение, но не алгоритм. Как формально определить «minimum autonomy required for bounded task»?
