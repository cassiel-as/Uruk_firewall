"""Merge a controller LoRA adapter and prepare an Ollama Modelfile."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT = (ROOT / "training" / "controller_system_prompt.txt").read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge and export the URUK Controller Model for Ollama.")
    parser.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--merged-dir", default=str(ROOT / "training" / "artifacts" / "uruk-controller-merged"))
    parser.add_argument("--ollama-name", default="uruk-controller")
    parser.add_argument("--create", action="store_true", help="Run ollama create after writing the Modelfile.")
    args = parser.parse_args()

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "Export dependencies are missing. Install training/requirements-training.txt "
            f"in the training virtual environment. Missing import: {exc}"
        )

    merged_dir = Path(args.merged_dir).resolve()
    merged_dir.mkdir(parents=True, exist_ok=True)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    base = AutoModelForCausalLM.from_pretrained(args.base_model, torch_dtype=dtype, device_map="auto")
    merged = PeftModel.from_pretrained(base, args.adapter).merge_and_unload()
    merged.save_pretrained(str(merged_dir), safe_serialization=True)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    tokenizer.save_pretrained(str(merged_dir))

    escaped_prompt = SYSTEM_PROMPT.replace('"""', "'''")
    modelfile = merged_dir / "Modelfile"
    modelfile.write_text(
        f'FROM {merged_dir}\n'
        'PARAMETER temperature 0\n'
        'PARAMETER num_ctx 4096\n'
        f'SYSTEM """{escaped_prompt}"""\n',
        encoding="utf-8",
    )
    if args.create:
        try:
            subprocess.run(["ollama", "create", args.ollama_name, "-f", str(modelfile)], check=True)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                "Ollama could not import the merged Hugging Face architecture. "
                "The merged model is preserved; convert it to GGUF before ollama create. "
                f"Command exit code: {exc.returncode}"
            )
    print(f"Merged model: {merged_dir}")
    print(f"Ollama Modelfile: {modelfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
