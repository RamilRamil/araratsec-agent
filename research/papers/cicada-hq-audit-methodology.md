# Анализ источника: cicada_HQ Audit Methodology

## Метаданные
- **Тип**: Practitioner methodology (не академическая статья)
- **Автор**: @cicada_HQ
- **Источник**: X/Twitter thread (2063348107601985592), ref blockthreat.com
- **Контекст**: Опубликовано во время активного 0xMarkets audit contest — реальный процесс, не теория

---

## 1. СУТЬ

Трёхфазная методология конкурентного аудита смарт-контрактов от практикующей команды: сначала архитектура и trust model, потом автоматизированный статический анализ, потом систематический ручной review по 5 предметным чеклистам — с фокусом на DeFi-специфичные паттерны (oracle manipulation, AMM, CEI).

---

## 2. МЕТОД

Это не исследование с метриками — это живая SOP аудиторской команды.

**Phase 1: SETUP**
- Карта: какие контракты вызывают какие
- Trust model: кто может upgrade, какие trusted roles
- Attack surface: прежде чем искать баги

**Phase 2: STATIC ANALYSIS**

Step 2.1 — Slither (приоритеты поиска):
```
reentrancy        → в unstake/withdraw/claim, нарушение CEI
controlled-delegatecall → может ли user input контролировать target?
arbitrary-send    → можно ли отправить средства на любой адрес?
incorrect-equality → == вместо >= при сравнении балансов
```

Step 2.3 — Mythril:
```
complex state machines → где require можно обойти
```

**Phase 3: MANUAL CODE REVIEW (5 шагов)**

**3.1 Access Control**
- Каждая функция: какой modifier?
- Red flags без onlyOwner: `migrate`, `emergencyWithdraw`, `upgradeTo`, `setImplementation`

**3.2 CEI Pattern**
```
1. Внешний вызов — последнее действие в функции?
2. Если нет — есть reentrancy guard?
3. Несколько внешних вызовов подряд → cross-function reentrancy risk
```

**3.3 Math / Integer Safety**
```
unchecked → только там, где overflow невозможен по логике?
Порядок операций: rate * amount / BASE  vs  amount * rate / BASE
→ разный rounding, важно для fee calculation
```

**3.4 Oracle Manipulation Checklist**
```
1. Тип оракула: TWAP? Spot? Uniswap V3? Chainlink?
2. Можно ли flash loan'ом сдвинуть цену в одном блоке?
3. Есть ли minimum periods для TWAP?
4. Можно ли заблокировать резолюцию (griefing оракула)?
5. Есть ли dispute window?

Attack pattern: открыть позицию → манипулировать оракулом → закрыть с прибылью
```

**3.5 AMM / Liquidity Pool**
```
1. First-deposit inflation (ERC4626): deposit 1 wei → donate → withdraw диспропорционально
2. Fee-on-transfer токены (баланс после transfer < amount)
3. Donation attack: прямой transfer в пул меняет share price
4. Withdrawal fee rounding (в чью пользу?)
5. Slippage protection: minimum output amount
```

---

## 3. СКЕПТИК

**Тип источника**: practitioner knowledge, не peer-reviewed. Нет метрик ASR, нет контролируемых экспериментов. Доверие строится на репутации команды и том, что это real-world process, а не теория.

**Что заслуживает доверия**:
- Слова «Slither», «CEI», «oracle manipulation», «first-deposit» — industry consensus, многократно подтверждённые в реальных взломах
- Oracle manipulation checklist совпадает с теорией из 2606.05418 (AMM-as-oracle) — независимое подтверждение
- CEI precondition (#3 у AttackPathGNN) — совпадает

**Что требует осторожности**:
- Step 2.3 — «Mythril» без детализации: что именно проверять? Mythril медленный на больших контрактах, нет конкретных команд
- «First-deposit» attack описан как «key finding type» — но в современных протоколах часто уже закрыт через виртуальные shares (ERC4626 best practice). Проверять, но не ожидать находку

**Пропуски** (нет в методологии, но важно для нашего контекста):
- Cross-contract composability (из 2606.05418) — не упоминается
- Memory Injection / LLM-specific угрозы — вне scope (это про smart contract, не про агента)
- Severity assessment — есть checklist, но нет критериев severity

---

## 4. МОДУЛЬ

- [x] **Инструменты** — конкретный список инструментов и их приоритеты
- [x] **Планировщик** — три фазы = готовая структура Stage 1 → Stage 2 → Stage 3
- [x] **LLM-ядро** — checklists как structured prompts для каждого шага

---

## 5. РЕШЕНИЕ

**5.1 Три фазы → маппинг на наш pipeline**

```
Phase 1 (Setup)          → Stage 1 пред-шаг: build_trust_model(contracts)
Phase 2 (Static)         → Stage 1 инструменты: run_slither(), run_mythril()
Phase 3.1-3.5 (Manual)  → Stage 2 CheckRunner: по одному чеклисту на каждый пункт
```

Cicada's methodology — это practitioner-валидация нашей иерархической архитектуры. Независимо от академических статей, практики пришли к той же структуре: сначала картина → потом автоматика → потом ручной по шагам.

**5.2 Конкретные инструменты для Stage 1**

```python
SLITHER_DETECTORS = [
    "reentrancy-eth",
    "reentrancy-no-eth",
    "controlled-delegatecall",
    "arbitrary-send-eth",
    "incorrect-equality",
]
# Запускать именно эти, не все — снизит шум
```

**5.3 Расширение 8 preconditions AttackPathGNN**

Из Step 3.4 и 3.5 добавляем 4 DeFi-precondition:

```
Precondition 9:  uses_external_oracle  (Spot/TWAP/Chainlink?)
Precondition 10: oracle_flashloan_manipulable (один блок = цена меняется?)
Precondition 11: first_deposit_unprotected (ERC4626 без virtual shares?)
Precondition 12: donation_attack_surface (прямой transfer меняет share ratio?)
```

Это DeFi-слой поверх reentrancy-ориентированных preconditions из AttackPathGNN.

**5.4 Oracle checklist → prompt для Stage 2**

```
For oracle dependency found in Stage 1:
1. Identify oracle type: [spot | TWAP | Chainlink | custom]
2. If spot or Uniswap V3 spot → flag: flashloan_manipulable = True
3. If TWAP → check: minimum_periods > 0?
4. Construct attack path: open_position → manipulate_price → close_position
5. Check: is resolution griefable?
```

**5.5 Math rounding → guardrail правило**

Порядок умножения/деления имеет значение:
```
rate * amount / BASE  → truncation favours protocol
amount * rate / BASE  → может быть другим
```
Stage 2 должна явно проверять обе формы и фиксировать направление rounding bias в structured output.

**5.6 Red flag функции → быстрый фильтр в Stage 1**

```python
RED_FLAG_FUNCTIONS = [
    "migrate", "emergencyWithdraw", "upgradeTo",
    "setImplementation", "setOwner", "transferProxy"
]
# Stage 1: сначала найти эти функции и проверить modifiers
# Если нет onlyOwner / timelock → immediate flag
```

---

## 6. ВОПРОСЫ

- **Phase 1 детализация**: «trust model» описан кратко. Как именно документировать — граф контрактов (как SIG из AttackPathGNN)? Нужен формальный формат.
- **Mythril timeout**: на реальных DeFi-контрактах Mythril часто timeout'ится. Какой `--execution-timeout` разумен? Нужно тестировать.
- **First-deposit в 2026**: большинство новых ERC4626-протоколов уже используют virtual shares. Стоит ли держать этот check или он даёт много FP?
- **Part 2 этой методологии**: автор обещал «threat modeling, exploit-path construction, advanced bug-hunting» — найти и проанализировать следующие части.
- **Связь с Bastet taxonomy**: Red flag functions → какой Bastet Tag? «Access Control» (10.0% в Bastet)?
