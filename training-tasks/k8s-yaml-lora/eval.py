"""Base vs. fine-tuned comparison: generate Kubernetes manifests for every
held-out eval instruction with the base model, then again with the LoRA adapter
applied, and report the schema-valid rate for each (via kubeconform).
"""

import json
import os
import re
import subprocess
import tempfile

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
ADAPTER_DIR = "./adapter_output"
EVAL_FILE = "data/eval.jsonl"
SYSTEM_PROMPT = "You are a Kubernetes expert. Given a description, output the corresponding Kubernetes manifest as YAML."

YAML_FENCE_RE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)


def load_eval_instructions(path: str) -> list[str]:
    instructions = []
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            instructions.append(row["messages"][1]["content"])
    return instructions


def generate(model, tokenizer, instruction: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output_ids[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True)


def extract_yaml(text: str) -> str | None:
    match = YAML_FENCE_RE.search(text)
    return match.group(1) if match else None


def kubeconform_valid(yaml_text: str) -> bool:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        path = f.name
    try:
        result = subprocess.run(["kubeconform", path], capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    finally:
        os.unlink(path)


def evaluate(model, tokenizer, instructions: list[str], label: str) -> dict:
    results = []
    for i, instruction in enumerate(instructions):
        raw_output = generate(model, tokenizer, instruction)
        yaml_text = extract_yaml(raw_output)
        valid = kubeconform_valid(yaml_text) if yaml_text else False
        results.append({"instruction": instruction, "output": raw_output, "valid": valid})
        print(f"[{label} {i+1}/{len(instructions)}] valid={valid}")

    valid_count = sum(r["valid"] for r in results)
    print(f"{label}: {valid_count}/{len(results)} schema-valid ({100 * valid_count / len(results):.0f}%)")
    return {"label": label, "results": results, "valid_count": valid_count, "total": len(results)}


def main() -> None:
    instructions = load_eval_instructions(EVAL_FILE)
    # For smoke-testing the pipeline without generating on the full eval set.
    if "EVAL_LIMIT" in os.environ:
        instructions = instructions[: int(os.environ["EVAL_LIMIT"])]

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.bfloat16, device_map="auto")

    base_summary = evaluate(model, tokenizer, instructions, "base")

    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    finetuned_summary = evaluate(model, tokenizer, instructions, "fine-tuned")

    print("\n=== Summary ===")
    print(f"base:       {base_summary['valid_count']}/{base_summary['total']} schema-valid")
    print(f"fine-tuned: {finetuned_summary['valid_count']}/{finetuned_summary['total']} schema-valid")

    with open("eval_results.json", "w") as f:
        json.dump({"base": base_summary, "fine_tuned": finetuned_summary}, f, indent=2)
    print("Wrote full results to eval_results.json")


if __name__ == "__main__":
    main()
    