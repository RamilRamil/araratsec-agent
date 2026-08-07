"""Fine-tune Qwen3-4B for Stage 2 with QLoRA (T088).

Runs on a GPU (Unsloth + bitsandbytes). Not exercised in CI — it is the training
entrypoint. Consumes data/finetune/train.jsonl (ShareGPT) and writes a LoRA
adapter to adapters/qwen3-4b-stage2/.

Usage (on a CUDA box):
    pip install "unsloth[cu121] @ git+https://github.com/unslothai/unsloth.git" trl
    python -m scripts.finetune.finetune_stage2
"""
from __future__ import annotations

from pathlib import Path

BASE_MODEL = "Qwen/Qwen3-4B"
ADAPTER_OUT = "adapters/qwen3-4b-stage2"
TRAIN_FILE = "data/finetune/train.jsonl"


def main() -> None:  # pragma: no cover - requires GPU + Unsloth
    from datasets import load_dataset
    from trl import SFTTrainer, SFTConfig
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=4096,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "v_proj"],
        lora_alpha=16,
        use_gradient_checkpointing="unsloth",
    )
    tokenizer = get_chat_template(tokenizer, chat_template="chatml")

    def fmt(row):
        return {"text": tokenizer.apply_chat_template(
            [{"role": "user" if m["from"] == "human" else "assistant", "content": m["value"]}
             for m in row["conversations"]],
            tokenize=False,
        )}

    ds = load_dataset("json", data_files=TRAIN_FILE, split="train").map(fmt)

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        args=SFTConfig(
            per_device_train_batch_size=2, gradient_accumulation_steps=4,
            warmup_steps=5, num_train_epochs=1, learning_rate=2e-4,
            logging_steps=10, output_dir="outputs", optim="adamw_8bit",
        ),
        dataset_text_field="text", max_seq_length=4096,
    )
    trainer.train()

    Path(ADAPTER_OUT).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(ADAPTER_OUT)
    tokenizer.save_pretrained(ADAPTER_OUT)
    print(f"LoRA adapter saved to {ADAPTER_OUT}")


if __name__ == "__main__":
    main()
