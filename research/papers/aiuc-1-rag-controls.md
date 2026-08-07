# AIUC-1 and RAG / Retrieval Controls

**Sources**:
- https://www.aiuc-1.com/
- https://aiuc.com/research/aiuc-1-mitre-atlas
- https://aiuc.com/research/framework-comparison

**Caveat**: The full text of AIUC-1's 130 controls is behind a demo wall. This note is based on AIUC's publicly published pillars + their MITRE ATLAS crosswalk + security-community readings, not verbatim control text.

---

## AIUC-1 does not name "RAG" as a category

There is no dedicated "RAG pillar." Retrieval/knowledge-base concerns are distributed across two of the six pillars plus the MITRE ATLAS mapping.

### 1. Security pillar
Covers **prompt injection defense** — including *indirect prompt injection*, where the malicious instruction arrives not from the user but from retrieved content. This is exactly the RAG attack vector.

### 2. Data & Privacy pillar
Covers data integrity and isolation — including **data poisoning** of the source corpus that retrieval draws from.

### 3. MITRE ATLAS mapping
AIUC-1 operationalizes ATLAS techniques, including:
- Training / data poisoning
- Indirect prompt injection via retrieved content
- Stored (persistent) injection — attacker seeds the database; the payload stays dormant until the model retrieves it

This is Memory Injection expressed in ATLAS vocabulary.

---

## Five retrieval controls AIUC-1 prescribes

| AIUC-1 control | SR-agent equivalent |
|---|---|
| **Source verification** — retrieve only from trusted, authenticated sources | `project_id` as a hard key + principal isolation |
| **Content integrity** — cryptographic hashing to detect unauthorized modification | **HMAC-SHA256 on every memory record** — literally this control |
| **Input scanning** — check retrieved content for injection patterns before it reaches the LLM | `sanitize()` (NFKC, zero-width, encoding detection) + `[DATA START]...[DATA END]` wrapping |
| **Access controls** — restrict who can write to the knowledge base | Append-only memory + status gate (`REQUIRES_HUMAN_CONFIRMATION`) |
| **Monitoring** — track retrieval patterns, flag anomalies | Langfuse tracer (Phase 9) |

---

## Key observation: HMAC = AIUC-1's "content integrity"

AIUC-1's prescribed control "content integrity via cryptographic hashing to detect unauthorized modifications to retrieved documents" is a direct description of what our HMAC layer does. Every memory record is signed; a record whose HMAC does not verify is silently dropped on load.

We arrived at this independently from the Memory Injection threat model (2503.16248) — and it maps cleanly onto the industry standard's requirement.

---

## The architectural difference

- **AIUC-1 assumes you have RAG** and prescribes wrapping it in controls (hashing, scanning, monitoring). It treats the symptom — a retrieval pipeline you must defend.
- **SR-agent removes semantic retrieval from agent memory entirely.** Memory is loaded by exact key (`project_id` + `target`), not by embedding similarity. No probabilistic search → nothing to poison. It treats the cause.

The relevant research number AIUC-1 implicitly addresses: **5 poisoned documents in a corpus of millions can manipulate AI responses ~90% of the time** (RAG poisoning research). This is precisely why agent memory is not built on retrieval here.

---

## Implications for SR-agent

1. **We exceed the standard on memory.** Where AIUC-1 asks for content integrity on retrieved docs, we don't retrieve by similarity at all — and still sign everything.

2. **Gap to close before any future knowledge base.** The `knowledge_chunks` parameter in `build_messages()` is a placeholder for a future reference KB (e.g. vulnerability-pattern excerpts). If/when populated, it MUST inherit the same five controls:
   - read-only, statically curated (source verification)
   - hashed (content integrity)
   - wrapped in `[DATA START]` + sanitized (input scanning)
   - never writable by the LLM (access control)
   - This KB is a *reference corpus about vulnerabilities*, never the agent's decision memory. The two layers must stay separate.

3. **Marketing/post angle.** "An industry standard (AIUC-1) requires cryptographic integrity on retrieved content. Most popular RAG frameworks don't even do that. SR-agent goes further and removes the poisonable retrieval step from memory entirely."

---

## Related

See also:
- [[composable-security-prompt-injection-mistakes]] — Mistake 2 (one-way filtering) and Mistake 4 (input sanitization alone) overlap directly with the RAG indirect-injection vector
- [[2606.15465-audit-gap]] — human-vector attacks; stored injection is a software analog
