---
name: best-practices-review
description: Review code against concrete engineering best practices with verifiable rules (error handling, resource safety, boundaries, naming, testability). Use this skill whenever the user asks to review code, check code quality, find code smells, audit error handling, or says things like "проверь код", "code review", "проверь на best practices", "ревью" - and also after generating any substantial new code (more than ~50 lines) as a self-check before presenting it. Do NOT use for architecture-level review; that is the architecture-critic skill.
---

# Best Practices Review

Check code against a fixed list of concrete, verifiable rules. This is deliberately NOT a general "make the code better" pass: every finding must cite a rule from this list (or a project-specific rule, see below) and point to an exact location.

## Scope discipline

- Review what was asked. If given a diff, review the diff - pre-existing issues in surrounding code get at most a one-line note.
- This skill covers code-level quality. Structural/architectural concerns (wrong boundaries, questionable technology choice, missing component) are out of scope - note them in one line and recommend the `architecture-critic` skill.
- Before reviewing, check for project-specific conventions: `.specify/memory/constitution.md`, linter configs, CONTRIBUTING.md. Project rules override the defaults below when they conflict.

## The rules

Each rule has an ID (use it in findings), a check, and a bad→good example.

### Errors and exceptions

**E1 - No swallowed failures.** Every catch/except must either handle the error meaningfully, or rethrow/propagate with context. An empty catch block, or one that only logs at debug level and continues, is a finding - always, no judgment call needed.
```python
# BAD
try:
    process(order)
except Exception:
    pass

# GOOD
try:
    process(order)
except PaymentError as e:
    raise OrderProcessingError(f"order {order.id}: payment step failed") from e
```

**E2 - Errors carry place and cause.** A raised/propagated error must answer: *what* operation failed, on *what* object, and *why* (chain the original cause). Bare `raise ValueError("invalid")` with no context is a finding.
```java
// BAD
throw new RuntimeException("failed");

// GOOD
throw new ConfigLoadException(
    "cannot parse retry policy in " + path + " line " + lineNo, cause);
```

**E3 - Catch narrow, not broad.** Catching `Exception`/`Throwable`/bare `except:` at a non-boundary layer hides bugs (including typos and NPEs) as "handled" errors. Broad catch is acceptable only at process boundaries (request handler, main loop, thread entry) and must log the full stack trace there.

**E4 - No errors as control flow for expected cases.** If a case is expected (key absent, item not found), use a return value/Optional/sentinel, not an exception. Exceptions are for violated expectations.

### Resources and external calls

**R1 - Deterministic cleanup.** Files, connections, locks, subscriptions: acquired resources are released via the language's scoped construct (`with`, `try-with-resources`, `defer`, RAII), not manual close calls that a thrown exception can skip.

**R2 - Every external call has a timeout.** Network/DB/queue calls without an explicit timeout are a finding: the default is usually "infinite", and one hung dependency freezes the caller.
```python
# BAD
resp = requests.get(url)

# GOOD
resp = requests.get(url, timeout=(3.0, 10.0))
```

**R3 - Retries only for retriable failures, with backoff and a cap.** Retrying non-idempotent operations, retrying on any exception type, or retrying in a tight loop are each findings.

### Functions and data

**F1 - No mutation of input arguments** unless mutation is the function's documented purpose. Callers must be able to trust that passing a list/dict/object doesn't change it.

**F2 - No magic values.** Unexplained literals (numbers, string flags, status codes) inline in logic must be named constants or enums. `if status == 3` is a finding; `if status == Status.SHIPPED` is not. Obvious values (0, 1, empty string as identity/default) are exempt.

**F3 - Honest signatures.** A function's name and signature must not lie: no hidden I/O in something named like a pure getter, no `get_user` that creates a user on miss (name it `get_or_create_user`), no boolean-flag parameters that make the call site unreadable (`render(true, false)` → split the function or use named/enum parameters).

**F4 - Validate at the boundary, trust inside.** External input (API payloads, file contents, env vars) is validated once at the entry point and converted to typed/internal structures. Re-validating the same data at every layer, or worse, validating nowhere, are both findings.

### Concurrency and state

**C1 - Shared mutable state must have a stated ownership/synchronization story.** Any variable written from more than one thread/task without a lock, atomic, actor, or single-writer rule is a finding.

**C2 - No time bombs.** `sleep` as synchronization, ordering assumptions between async tasks without an explicit await/join, check-then-act on filesystem or shared maps (TOCTOU) - each is a finding.

### Logging and observability

**L1 - Log at the right level with context.** Errors that abort an operation → error level with identifiers (order id, request id), not just the message. Expected control flow → not at warn/error. Secrets, tokens, passwords, full card numbers in logs → always a finding, severity High.

**L2 - One failure, one log.** Log-and-rethrow at every layer produces N stack traces per incident. Log where the error is finally handled; layers in between add context to the exception, not to the log.

### Tests (when tests are in scope of the review)

**T1 - A test asserts behavior, not implementation.** Tests that break on any refactor (asserting on internal call order via mocks of everything) are a finding.

**T2 - No shared mutable fixtures between tests; no order dependence.**

## Output format

ALWAYS use this structure:

```
## Review: <files or diff reviewed>

### High
Findings that can cause data loss, silent corruption, hangs, or security issues.
- **[E1] path/file.py:42** - description. Fix: <concrete fix, with code if short>

### Medium
Findings that will cause debugging pain or maintenance cost.
- **[F3] ...**

### Low / style
One line each. Skip entirely if empty.

### Out of scope, noted
Architecture-level observations (one line each) + pointer to architecture-critic
if warranted.

### Clean
Rules checked with no findings - one line, list the rule IDs. This shows the
review actually covered them.
```

Rules for findings:
- Every finding: rule ID + exact location + why it bites + concrete fix. A finding without a fix proposal is incomplete.
- Do not pad. If the code is clean, the whole review can be five lines, and that's a good outcome.
- When the same violation repeats many times, report it once with a count and 2-3 representative locations, not a wall of duplicates.
- Severity is set by consequence, not by rule category: a swallowed exception in a payment path is High; the same pattern in a debug script may be Low.
