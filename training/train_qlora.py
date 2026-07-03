"""Launch QLoRA SFT for the narrow URUK Controller Model.

This script intentionally imports training-only dependencies lazily so the
main URUK runtime does not require PyTorch, Transformers, PEFT, TRL, or
bitsandbytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "Qwen/Qwen3-1.7B"
DEFAULT_DATA_DIR = ROOT / "training" / "generated"
DEFAULT_OUTPUT_DIR = ROOT / "training" / "artifacts" / "uruk-controller-qwen3-1.7b-lora"
SYSTEM_PROMPT = (ROOT / "training" / "controller_system_prompt.txt").read_text(encoding="utf-8")


def _to_prompt_completion(example: dict) -> dict:
    return {
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(example["input"], ensure_ascii=False, separators=(",", ":"))},
        ],
        "completion": [
            {"role": "assistant", "content": json.dumps(example["output"], ensure_ascii=False, separators=(",", ":"))},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the URUK Controller Model with QLoRA.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--epochs", type=float, default=4.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    args = parser.parse_args()

    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            "Training dependencies are missing. Install training/requirements-training.txt "
            f"in a separate virtual environment. Missing import: {exc}"
        )
    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA is not available in this Python environment. QLoRA training is blocked "
            "to prevent an accidental CPU-only run. Use training/bootstrap_windows.ps1 "
            "and verify with training/preflight.py."
        )

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_files = {
        "train": str(data_dir / "train.jsonl"),
        "validation": str(data_dir / "validation.jsonl"),
    }
    dataset = load_dataset("json", data_files=data_files)
    remove_columns = dataset["train"].column_names
    dataset = dataset.map(_to_prompt_completion, remove_columns=remove_columns)

    compute_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        device_map="auto",
        quantization_config=quantization,
        torch_dtype=compute_dtype,
    )
    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    training_args = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation,
        max_length=args.max_length,
        packing=False,
        completion_only_loss=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=5,
        report_to="none",
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        gradient_checkpointing=True,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    print(f"Saved URUK Controller LoRA adapter to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
