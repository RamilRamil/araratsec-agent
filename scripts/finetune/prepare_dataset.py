"""Prepare the Stage 2 fine-tuning dataset (T085).

Combines security-audit examples (Bastet) + agentic function-calling examples
(Hermes FC `json_mode_agentic` subset) + the synthetic MI-rejection examples
(generate_mi_rejections) into a single ShareGPT-format corpus whose target
output is always a valid AgentAction JSON. Splits 90/10 into train/val.

The external-dataset loaders are gated on the `datasets` library / network; the
conversion and split logic are pure and unit-tested.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from scripts.finetune.generate_mi_rejections import generate as generate_mi


def to_sharegpt(human_text: str, gpt_json: str) -> dict:
    """Wrap a (prompt, target-AgentAction-JSON) pair in ShareGPT format."""
    return {"conversations": [
        {"from": "human", "value": human_text},
        {"from": "gpt", "value": gpt_json},
    ]}


def split_90_10(examples: list[dict], seed: int = 0) -> tuple[list[dict], list[dict]]:
    """Deterministic 90/10 train/val split."""
    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    cut = max(1, int(len(shuffled) * 0.9)) if len(shuffled) > 1 else len(shuffled)
    return shuffled[:cut], shuffled[cut:]


def load_bastet() -> list[dict]:  # pragma: no cover - needs datasets + network
    """Load the Bastet audit dataset and convert to ShareGPT. Gated."""
    try:
        from datasets import load_dataset
    except Exception as e:
        raise RuntimeError(f"datasets library unavailable: {e}") from e
    ds = load_dataset("bastet", split="train")  # placeholder id; set real id at run time
    out = []
    for row in ds:
        human = f"Analyze this contract for vulnerabilities.\n\n{row.get('contract','')}"
        gpt = json.dumps(row.get("agent_action", {}))
        out.append(to_sharegpt(human, gpt))
    return out


def load_hermes_agentic() -> list[dict]:  # pragma: no cover - needs datasets + network
    """Load the Hermes FC json_mode_agentic subset and convert. Gated."""
    try:
        from datasets import load_dataset
    except Exception as e:
        raise RuntimeError(f"datasets library unavailable: {e}") from e
    ds = load_dataset("NousResearch/hermes-function-calling-v1", "json_mode_agentic", split="train")
    out = []
    for row in ds:
        convs = row.get("conversations", [])
        if convs:
            out.append({"conversations": convs})
    return out


def main() -> None:  # pragma: no cover - orchestration
    examples: list[dict] = []
    for loader in (load_bastet, load_hermes_agentic):
        try:
            examples.extend(loader())
        except Exception as e:
            print(f"skip {loader.__name__}: {e}")
    examples.extend(generate_mi(200))  # always include MI rejections

    train, val = split_90_10(examples)
    out_dir = Path("data/finetune")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, split in (("train", train), ("val", val)):
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for ex in split:
                f.write(json.dumps(ex) + "\n")
    print(f"train={len(train)} val={len(val)} -> {out_dir}")


if __name__ == "__main__":
    main()
