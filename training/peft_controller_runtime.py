"""Reusable PEFT runtime for the narrow URUK controller model."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from training.run_controller_candidate import SYSTEM_PROMPT, parse_decision


class PeftControllerRuntime:
    """Load one adapter once and serialize GPU inference calls."""

    def __init__(
        self,
        *,
        adapter: Path,
        base_model: str = "Qwen/Qwen3-1.7B",
        context_window: int = 2048,
        max_new_tokens: int = 512,
    ) -> None:
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(f"Training environment dependency missing: {exc}") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the PEFT controller runtime.")

        self.adapter = str(Path(adapter))
        self.base_model = base_model
        self.context_window = context_window
        self.max_new_tokens = max_new_tokens
        self._torch = torch
        self._lock = threading.Lock()
        compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto",
            quantization_config=quantization,
            dtype=compute_dtype,
        )
        self.model = PeftModel.from_pretrained(model, self.adapter)
        self.model.eval()

    def predict(self, model_input: dict[str, Any]) -> dict[str, Any]:
        user_content = json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        encoded = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.context_window,
        )
        encoded = {key: value.to(self.model.device) for key, value in encoded.items()}
        with self._lock, self._torch.inference_mode():
            generated = self.model.generate(
                **encoded,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        new_tokens = generated[0, encoded["input_ids"].shape[1]:]
        raw = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        decision, error = parse_decision(raw)
        if error or decision is None:
            raise ValueError(error or "controller returned no decision")
        return decision

