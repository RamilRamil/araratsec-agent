# Исследование: Модуль I/O

## Ключевые решения

| Решение | Обоснование |
|---------|-------------|
| Три типа вывода | Machine JSON / Progress stream / Final report — разные читатели, разные форматы |
| Final report = Markdown | Работает везде: GitHub, Notion, экспорт в PDF |
| Severity-first ordering | Security team видит Critical первым |
| Раздел «не проверено» | Молчаливая неполнота опаснее явной; клиент знает scope |
| Progress bar + чекпоинты | Аудит длится 20+ минут — нужно видимое движение |
| Input: path + address | Source + on-chain верификация, оба типа |
| Resumption через Episodic Memory | Checkpoints Stage 1/2/3 позволяют продолжить с места остановки |

---

## 1. Три типа вывода

```
Machine JSON      ← агент → агент
  Checkpoints, structured findings, SIG, stage state
  Читатель: следующая стадия агента
  Формат: JSONL, HMAC-подписанный, в Episodic Memory

Progress stream   ← агент → человек (во время работы)
  Видимые чекпоинты, прогресс по стадиям, текущее действие
  Читатель: аудитор следящий за сессией
  Формат: human-readable строки + progress bar

Final report      ← агент → человек (по завершении)
  Структурированный аудиторский отчёт
  Читатель: security team
  Формат: Markdown (.md)
```

---

## 2. Input

### Два типа источников (оба поддерживаются)

```
Тип A: Путь к директории
  "audit /projects/vault-protocol/src/"
  → Slither парсит Solidity исходники
  → build_graph на локальных файлах

Тип B: Адрес контракта (on-chain)
  "audit 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
  → decompile_bytecode (для неверифицированных)
  → analyze_transactions (история)
  → если верифицирован на Etherscan → Тип A + on-chain данные

Комбинация (рекомендуется):
  Исходники + адрес → source-verified audit с on-chain контекстом
```

### Input validation (оркестратор, до старта)

```python
def validate_input(audit_input: AuditInput) -> ValidationResult:
    if audit_input.path:
        # Путь существует?
        # Содержит .sol файлы?
        # Не выходит за пределы разрешённой директории?
        pass

    if audit_input.address:
        # Валидный EIP-55 checksum адрес?
        # Контракт существует (не EOA)?
        # RPC доступен?
        pass

    # Scope specification валидна?
    # Не пустой scope?
```

### Scope specification

```
audit /src/core/ --exclude /src/mocks/
audit 0xA0b8... --include-imports false
audit /src/ --focus Vault.sol Pool.sol
```

---

## 3. Progress Stream

Аудит занимает 20+ минут. Человек должен видеть движение, а не пустой экран.

### Структура вывода во время работы

```
[SR-Agent] Audit started: VaultProtocol
────────────────────────────────────────
Stage 1: Discovery  [████████░░░░░░░░]  50%  ETA ~4 min
  ✓ build_graph: 12 contracts, 47 functions, 3 can_reenter paths
  ✓ red_flag_functions: migrate (no timelock), upgradeTo (no onlyOwner)
  → analyzing Vault.sol:withdraw [2/8 priority targets]

────────────────────────────────────────
Stage 2: Checking  [░░░░░░░░░░░░░░░░]   0%
Stage 3: Synthesis [░░░░░░░░░░░░░░░░]   0%
────────────────────────────────────────
```

### Checkpoint events (видимые переходы)

```python
PROGRESS_EVENTS = [
    "stage1.graph_built",       # ✓ SIG построен
    "stage1.targets_ready",     # ✓ Stage 1 завершён, N целей
    "stage2.target_N_done",     # ✓ Цель N/M проверена
    "stage2.poc_confirmed",     # ✓ Critical finding подтверждён PoC
    "stage2.human_escalation",  # ⚠️ Требует внимания: ...
    "stage3.combinations_done", # ✓ Комбинации проверены
    "report.ready",             # ✓ Отчёт готов
]
```

Каждый event — строка в progress stream. Человек видит «живое» движение по стадиям.

---

## 4. Session Resumption

Аудит прерван на Stage 2 (5 из 8 целей проверено). Перезапуск:

```
Человек: "Resume audit of VaultProtocol"
         ↓
Оркестратор: загружает checkpoint из Episodic Memory
         ↓
Checkpoint:
  stage: 2
  completed_targets: [Vault.sol:withdraw, Pool.sol:swap, ...]  ← 5 из 8
  remaining_targets: [Oracle.sol:getPrice, Router.sol:execute, Pool.sol:addLiquidity]
  finding_ids: [rec-001, rec-002]
         ↓
Stage 2 продолжает с remaining_targets[0]
Progress bar показывает 5/8 уже выполненных
```

Checkpoints сохраняются в Episodic Memory автоматически оркестратором после каждой завершённой цели. Resumption — стандартный flow, не специальный режим.

---

## 5. Final Report (Markdown)

### Структура

```markdown
# Security Audit Report: VaultProtocol

**Date**: 2026-06-24
**Scope**: /src/core/ (12 contracts)
**Auditor**: SR-Agent v1.0

---

## Executive Summary

| Severity  | Confirmed | Unverified |
|-----------|-----------|------------|
| Critical  | 1         | 0          |
| High      | 2         | 1          |
| Medium    | 3         | 0          |
| Low       | 5         | 0          |

**Overall risk**: CRITICAL — immediate action required

---

## Critical Findings

### [CRIT-001] Reentrancy in withdraw() — CONFIRMED
**Location**: Vault.sol:47
**Severity**: Critical
**Status**: Confirmed (PoC reproduced)
**Estimated loss**: up to N ETH per transaction

**Attack path**:
1. Attacker calls `withdraw()`
2. External call triggered before `balances[msg.sender] = 0`
3. Attacker re-enters via fallback — drains pool

**Evidence**: `test/poc/CRIT-001-reentrancy.sol`
**Fix**: Move `balances[msg.sender] = 0` before external call (CEI pattern)

---

## High Findings
...

## Unverified Findings (требуют ручной проверки)

### [UNVER-001] Potential oracle manipulation in swap()
**Location**: Pool.sol:swap
**Status**: Unverified — PoC не воспроизвёл эксплойт
**Reason**: Требует специфического состояния AMM — ручная проверка
...

---

## Coverage

**Analyzed** (12 contracts):
- Vault.sol, Pool.sol, Router.sol, Oracle.sol, ...

**Not analyzed** (out of scope / skipped):
- /src/mocks/ (исключено из scope)
- LiquidityHelper.sol (Slither compilation failed — pragma incompatibility)

**Tools run**: Slither v0.11.5, Mythril v0.24.8, AttackPath analysis

---

## Disclaimer
Этот отчёт покрывает scope указанный выше. Контракты вне scope не проверялись.
Unverified findings требуют ручной проверки перед выводами о безопасности.
```

---

## 6. Открытые вопросы

- **Report signing**: нужна ли цифровая подпись финального отчёта? MD-файл легко изменить после генерации.
- **Streaming vs batch**: прогресс — push (SSE/websocket) или pull (polling)? Зависит от интерфейса (CLI vs web).
- **Multi-language support**: отчёт на русском или английском? Зависит от аудитории.
- **Report versioning**: если аудит возобновлялся несколько раз — один отчёт или delta?
- **Machine-readable output**: нужен ли SARIF формат (стандарт для security findings) для интеграции с CI/CD?
