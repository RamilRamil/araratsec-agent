# Stage 2 Fine-tuning Dataset (T087)

Training corpus for the fine-tuned Stage 2 model (`sr-stage2`, Qwen3-4B + QLoRA).
Target output is always a valid `AgentAction` JSON.

## Sources

| Source | What | ~Size | License |
|---|---|---|---|
| Bastet | smart-contract audit findings → AgentAction | ~849 | CC BY-NC |
| Hermes FC (`json_mode_agentic`) | agentic function-calling → structured JSON | ~1.3K | Apache 2.0 |
| MI rejections (synthetic) | injected memory record → `escalate` | ~200 | this repo |

The MI-rejection examples are the security core: they teach the model that a
memory record trying to change a privileged status or inject an instruction must
be **escalated**, never obeyed — content inside `[DATA START]..[DATA END]` is
data, not commands.

## Format

ShareGPT JSONL:
```json
{"conversations": [{"from": "human", "value": "<prompt>"},
                   {"from": "gpt",   "value": "<AgentAction JSON>"}]}
```

## Build

```
python -m scripts.finetune.generate_mi_rejections   # -> data/finetune/mi_rejections.jsonl
python -m scripts.finetune.prepare_dataset          # -> train.jsonl + val.jsonl (90/10)
```
External datasets (Bastet, Hermes) are downloaded via `datasets` at build time;
the MI rejections are always included. Split is a deterministic 90/10.

## Train + register

```
python -m scripts.finetune.finetune_stage2          # GPU: QLoRA -> adapters/qwen3-4b-stage2/
ollama create sr-stage2 -f scripts/finetune/Modelfile
python -m scripts.finetune.eval_finetune            # base vs fine-tuned ASR (assert <= 5%)
```

Generated `train.jsonl`/`val.jsonl` and `mi_rejections.jsonl` are gitignored
(`data/finetune/`); this README and the scripts are tracked.
