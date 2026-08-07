# Исследование: Хостинг локальной модели на эфемерном облачном GPU

Контекст: локальное железо (4-ядерный i5, без пригодного GPU) непригодно для 7b/14b
инференса (roadmap gotcha #4 — один вызов >30 мин на CPU). Для теста PoC-workability
и вообще «локальной» модели нужен внешний GPU. Бесплатные варианты — Google Colab и
Kaggle Notebooks + `ollama serve` + `cloudflared` quick-tunnel, `LocalClient(host=<url>)`.

## Ключевые решения

| Решение | Обоснование |
|---------|-------------|
| **Kaggle > Colab-free** для этой задачи | Явная предсказуемая квота (30ч/нед, сброс еженедельно) vs непубличные плавающие лимиты Colab и отказ в GPU в пик |
| **Квоту жжёт активная GPU-сессия, НЕ туннель** | GPU-часы тикают, пока kernel жив с включённым ускорителем — даже вхолостую; cloudflared невесом и бесплатен |
| **Ограниченный батч → сразу Stop Session** | Один сфокусированный заход вместо многих мелких с простоями; не держать сессию «на всякий случай» |
| **Интерактивная сессия, не batch/commit** | Раннер локальный и дёргает удалённый Ollama через туннель в реальном времени — нужен живой reachable endpoint, а не headless-прогон своих ячеек |
| **`--max-minutes` (раннер) + ручной Stop** | Программного self-stop у ноутбуков нет; ограничиваем РАБОТУ, сессию гасит оператор (+ idle-timeout как бэкстоп) |
| **Отказ от cross-gap keep-alive пингера** | Держать туннель тёплым в паузах между прогонами = держать GPU-сессию живой вхолостую = жечь квоту |
| **In-run keep-alive оставляем** | Пинг каждые 30с ВНУТРИ прогона нужен, чтобы cloudflared не отвалился в idle-окне docker-компиляции (gotcha #11) |

---

## 1. Google Colab (free) — модель и лимиты

- **Макс. время сессии / жизнь VM:** до ~12ч, «depending on availability and your usage
  patterns». VM удаляется по достижении лимита жизни.
- **Idle-timeout:** ~90 мин бездействия (нет исполняющихся ячеек + нет взаимодействия с
  вкладкой) → отключение.
- **Лимиты НЕ публикуются и плавают:** «Colab does not publish these limits, in part
  because they can vary over time… overall usage limits, idle timeout periods, maximum VM
  lifetime, GPU types available… vary over time». Это осознанная политика ради бесплатности.
- **GPU:** T4 «when available»; в пик free-юзеру могут вообще не дать GPU. Никаких гарантий.
- **«Maximum connection time reached»** (что мы поймали) = упёрлись в динамический
  usage-cap / лимит жизни VM. Сбрасывается через несколько часов, непредсказуемо.

**Вывод:** Colab-free = непрозрачный, короткий idle (90 мин), может отказать в GPU, лимиты
не видны. Плохо для повторяемого метеринга.

## 2. Kaggle Notebooks — модель и лимиты

- **Квота GPU:** **30 часов/неделю гарантированно** (+ иногда бонус по алгоритму
  спрос/предложение), **сброс еженедельно в субботу 00:00 UTC**.
- **Макс. длина сессии:** интерактивная — до **9ч**; на ~12ч непрерывного использования
  всплывает «are you still there?».
- **Idle-timeout интерактива:** ~**40 мин** без правок/запуска ячейки (в части отчётов —
  60 мин) → сессия останавливается.
- **Как тратится квота — ГЛАВНОЕ:** GPU-часы считаются, пока сессия жива **с включённым
  ускорителем** (attached), а НЕ только во время вычислений. Пользователи стабильно
  сообщают о списании квоты в простое → **idle GPU жжёт квоту**. Значит экономия = гасить
  сессию, а не оставлять её висеть.
- **Keep-alive:** интерактиву нужен keepalive ~раз в минуту (браузер). Взаимодействие хотя
  бы раз в час держит сессию до 9ч. **Batch** (Save & Run All / «save a new version») —
  headless в фоне, но тоже ест квоту и запускает СВОИ ячейки, а не служит внешнему туннелю.
- **Internet:** для скачивания Ollama/модели/cloudflared нужен тумблер **Internet = On**
  (требует верификации по телефону). GPU-ускоритель — там же в Settings.

**Вывод:** Kaggle = явные 30ч/нед, предсказуемый сброс, сессии длиннее и стабильнее.
Лучший бесплатный путь для нашего повторяемого воркфлоу.

## 3. Сравнение

| | Colab (free) | Kaggle Notebooks |
|---|---|---|
| Квота | Непубличная, плавает | **30ч/нед**, сброс сб 00:00 UTC |
| Сессия макс | ~12ч (без гарантий) | 9ч интерактив / ~12ч |
| Idle-timeout | ~90 мин | ~40 мин |
| GPU | T4 when available, в пик отказ | T4×2 / P100, стабильнее |
| Прозрачность | Низкая | Высокая (видно остаток квоты) |
| Что жжёт бюджет | Время VM | **GPU-часы активной сессии** |

## 4. Как это ложится на наш воркфлоу

Архитектура: **раннер локальный**, гонит `write_poc`→docker-compile локально, а инференс
шлёт на удалённый Ollama через cloudflared. Значит:

1. GPU на Kaggle простаивает во время локальной docker-компиляции (~20-40с ×попытки
   ×находки) — но сессия жива → **квота тикает даже в этот простой**. Неизбежно в этой
   архитектуре; минимизируем ограниченным батчем.
2. **Экономный цикл:** поднять сессию → прогнать малый батч (`--limit N --max-minutes M`)
   → раннер печатает `done` → **сразу Stop Session** (освобождает GPU мгновенно) →
   офлайн-анализ карантинных черновиков (без GPU) → правка рычага → повтор.
3. Бэкстоп «забыл выключить»: закрыть вкладку → Kaggle сам гасит по idle (~40 мин); либо
   ячейка-будильник `time.sleep(M*60); print("STOP")`.
4. **Прикидка:** ~4-5 мин/находка (14b, depth-2 grounding). 30ч/нед ≈ несколько полных
   проходов по 23 находки (~1.5-2ч) + итерации. Сигнальный заход (3 находки) ≈ 20 мин.

## 5. Gotchas (подтверждены на практике)

- **`zstd` нужен установщику Ollama** (подтверждено на Kaggle 2026-07): свежий
  `install.sh` распаковывает пакет через zstd; в минимальном образе Kaggle его нет →
  «ERROR: This version requires zstd», бинарник не ставится, дальше `FileNotFoundError:
  'ollama'`. Ставить `apt-get install -y zstd` ДО `curl … install.sh | sh`.
- **`pciutils` ДО первого `ollama serve`** (roadmap gotcha #4): без `lspci` Ollama не
  детектит GPU и молча уходит на CPU. Детекция — при старте сервера, не лениво.
- **`r2u.stat.illinois.edu … Sources`** warning на `apt-get update` в Kaggle — безобидный
  шум предустановленного R-репозитория; на установку из main-репо не влияет.
- **cloudflared quick-tunnel idle ~60-100с** (gotcha #11): `stream: true` (NDJSON) внутри
  генерации + in-run keep-alive пинг /api/tags каждые 30с держат соединение.
- **Internet=On + верификация телефона** — иначе скачать нечего.
- **Туннель умирает вместе с сессией** — «закрыть туннель после прогона» = «остановить
  сессию Kaggle»; отдельно гасить cloudflared смысла для квоты нет.

## Источники

- [Google Colab FAQ](https://research.google.com/colaboratory/faq.html)
- [Colab GPU: free access, limits, alternatives — Hivenet](https://www.hivenet.com/post/google-colaboratory-gpu-complete-guide-to-free-cloud-gpu-access-and-limitations)
- [Kaggle: floating GPU quota (30h + бонус)](https://www.kaggle.com/product-feedback/173129)
- [Kaggle: weekly GPU quota reset (сб UTC)](https://www.kaggle.com/general/135810)
- [Kaggle: Efficient GPU Usage Tips](https://www.kaggle.com/docs/efficient-gpu-usage)
- [Kaggle: losing GPU hours when idle](https://www.kaggle.com/product-feedback/158058)
- [Kaggle: quota counted after session initialized](https://www.kaggle.com/product-feedback/168365)
- [Kaggle: "are you still there?" 12h](https://www.kaggle.com/questions-and-answers/306441)
