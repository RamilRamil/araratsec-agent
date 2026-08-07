# Исследование: Модуль Планировщика

## Ключевые решения

| Решение | Обоснование |
|---------|-------------|
| Stage 1 → ReAct, Stage 2 → for-loop, Stage 3 → ReAct | Стратегия планирования соответствует структуре задачи |
| Stage 1 stopping = человек | Scope аудита знает человек, не агент |
| Stage 2 stopping = список исчерпан | Конечный известный список целей |
| Stage 3 фильтр через SIG | Только пары с interference рёбрами — кандидаты для комбинаций |
| Stage 3 анализ = большая модель, max thinking | Поиск нетривиальных цепочек требует максимальных рассуждений |

---

## 1. Принцип: стратегия под структуру задачи

```
Открытое исследование   → задачи неизвестны заранее  → ReAct (адаптивный)
Конечный список целей   → задачи перечислимы         → for-loop (детерминированный)
Синтез и комбинации     → нет предсказуемой структуры → ReAct (адаптивный)
```

ReAct (Reasoning + Acting): `Observe → Think → Act → Observe → ...`

На каждом шаге Think — планировщик решает что делать следующим на основе текущего состояния.

---

## 2. Stage 1: Discovery (ReAct)

### Scope задаётся человеком

```
Человек:   "Проанализируй /src/core/ и /src/defi/, найди высокоприоритетные цели"
              ↓
Stage 1:   Исследует scope, составляет список целей для Stage 2
              ↓
Агент:     Выдаёт структурированный отчёт
              ↓
Человек:   Решает: "Достаточно" / "Добавь Oracle.sol" / "Запускай Stage 2"
```

### Порядок шагов внутри ReAct

```
1. build_graph(contracts_in_scope)     → State Interference Graph
2. find_red_flag_functions()           → migrate, upgradeTo, emergencyWithdraw без modifier
3. Приоритизация по SIG:
   - Функции с can_reenter рёбрами → первыми
   - Функции с interferes рёбрами → следующими
4. read_file + анализ для каждого приоритетного узла
5. Пополнять список кандидатов для Stage 2
```

### Stopping condition

Stage 1 не имеет автоматического stopping condition кроме circuit breaker (max_iterations). Человек видит отчёт и принимает решение.

### Формат вывода для человека

```
Stage 1 Report
──────────────────────────────────────────
Проанализировано:   Vault.sol, Pool.sol, Router.sol
Не проверено:       Oracle.sol (вне начального scope)

Цели для Stage 2 (8 функций):
  🔴 Vault.sol:withdraw      — can_reenter в SIG, 4/12 preconditions active
  🔴 Pool.sol:swap           — AMM oracle dependency (PATTERN-01)
  🟡 Router.sol:execute      — controlled-delegatecall (Slither)
  ...

Red flags (ручной взгляд):
  ⚠️  Vault.sol:migrate      — нет onlyOwner, нет timelock
  ⚠️  Pool.sol:upgradeTo     — нет onlyOwner

Cross-contract пары: 3, can_reenter пути: 1
──────────────────────────────────────────
Достаточно для Stage 2? Добавить контракты?
```

Три секции: что сделано / что пропущено / что найдено. Человек видит coverage и решает.

---

## 3. Stage 2: CheckRunner (for-loop)

### Детерминированный перебор

Список целей известен из Stage 1. Нет необходимости в рассуждениях о порядке:

```python
for target in stage1_targets:
    result = check_target(target)  # запускает чеклист preconditions
    
    if result.severity >= HIGH:
        poc = write_poc(target, result)
        verified = run_poc(poc)
        guardrails.evaluate(result, verified)
    
    memory.write(finding)          # structured, HMAC
    checkpoint.update(target)      # оркестратор обновляет прогресс
```

### Stopping condition

Список исчерпан. Или circuit breaker (timeout / max_iterations). Нет адаптивных решений — каждый target получает одинаковый процесс.

### Retry → Skip

Если инструмент падает на конкретном target:
```
retry N раз → если всё равно падает → findings = None (не [])
→ explicit skip с причиной → в отчёт Stage 3
```

---

## 4. Stage 3: Synthesis (ReAct)

### Два вопроса

```
1. Подтверждение: finding из Stage 2 реально эксплуатируется?
2. Комбинации:   что если X + Y используются вместе в одной атаке?
```

### SIG-фильтр для комбинаций

Из 8 findings теоретически 28 пар. SIG сокращает до значимых кандидатов:

```python
candidates = []
for (finding_a, finding_b) in combinations(stage2_findings, 2):
    fn_a = finding_a.location.function
    fn_b = finding_b.location.function
    
    if sig.has_edge(fn_a, fn_b):  # делят mutable storage
        candidates.append((finding_a, finding_b))

# Сортировать: Critical+Critical первыми
candidates.sort(key=lambda p: p[0].severity + p[1].severity, reverse=True)
```

Из 28 пар → 5-7 реальных кандидатов с SIG-рёбрами.

### Анализ комбинаций

Для каждого кандидата — большая модель, max thinking (extended reasoning):

```
"Findings:
 A: reentrancy в withdraw() — CEI нарушен, balances обновляется после call
 B: oracle manipulation в swap() — использует spot price из AMM

Вопрос: если атакующий сначала манипулирует оракулом (B),
        создаёт ли это условия для более выгодной reentrancy (A)?
        Опиши точный путь атаки если да."
```

Нетривиальные цепочки атак (The DAO + оракул = amplified exploit) требуют глубокого рассуждения. for-loop здесь неприменим — структура неизвестна заранее.

### Non-transitivity (из 2606.05418)

A безопасен с B, B безопасен с C ≠ A+B+C безопасны вместе. Stage 3 должен проверять не только пары но и тройки для Critical findings. SIG-фильтр применяется рекурсивно.

### Stopping condition

- Все SIG-кандидаты проверены
- Или circuit breaker (max_iterations, token budget)
- Или человек прерывает

---

## 5. Что раскроется при разработке

Текущий документ фиксирует скелет. Следующие вопросы откроются на практике:

- **Промптинг ReAct Think-шага**: как именно формулировать reasoning step для Stage 1 и Stage 3, чтобы агент не зацикливался и не пропускал важное?
- **Тройки и выше**: при каком количестве находок стоит искать комбинации из трёх? SIG-фильтр + severity threshold?
- **Инкрементальный аудит**: кодовая база изменилась с прошлого аудита — как Stage 1 приоритизирует изменённые контракты?
- **Очень большие кодовые базы**: 100+ контрактов — Stage 1 не сможет прочитать всё. Нужна стратегия sampling на основе SIG.
- **Stage 2 параллелизм**: независимые targets можно проверять параллельно. Как оркестратор управляет параллельными Stage 2 потоками?

---

## 6. Открытые вопросы

- Как Stage 1 обрабатывает import-зависимости (OpenZeppelin, Uniswap V3 core)? Включать в SIG или исключать как trusted?
- Что если Stage 1 находит 50 целей? Нужен threshold для Stage 2 или человек всегда решает?
- Stage 3 non-transitivity для троек: как выбрать threshold severity при котором тройки проверяются?
