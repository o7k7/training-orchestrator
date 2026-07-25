"""LoRA SFT: fine-tune Qwen2.5-7B-Instruct to generate Kubernetes manifest YAML
from natural-language instructions, using the dataset in data/{train,eval}.jsonl
(see data/build_dataset.py for provenance).

Expects to run from this directory (training-tasks/k8s-yaml-lora), which is how
the orchestrator's git-clone init container lays out the cloned repo.

Env vars (all optional except the base model download, which needs none):
  WANDB_API_KEY, WANDB_PROJECT, WANDB_ENTITY  - injected by the platform when a
      job sets wandb_project; if WANDB_PROJECT is unset, W&B logging is skipped.
  HF_TOKEN, HF_HUB_REPO_ID                    - injected when a job sets
      push_to_hub_repo; if HF_HUB_REPO_ID is unset, the Hub push is skipped.
  CHECKPOINT_BUCKET                           - not a platform-injected var, pass
      it inline in the job's command (e.g. "CHECKPOINT_BUCKET=foo python train.py")
      if you want the adapter uploaded to S3 via the training-job ServiceAccount's
      IRSA role. Skipped if unset.
  BASE_MODEL                                  - override the model to fine-tune.
      Defaults to Qwen/Qwen2.5-7B-Instruct, which needs ~24GB VRAM and will OOM
      on anything smaller (e.g. an 8GB laptop GPU). For a local pipeline smoke
      test on a small GPU, override to a tiny model (e.g.
      "Qwen/Qwen2.5-0.5B-Instruct") - this proves the mechanics (data loading,
      LoRA/collator wiring, save, S3/Hub push, W&B logging) without needing the
      real 24GB GPU that the actual training run requires.
"""

import os
import uuid

import torch
import wandb
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import DataCollatorForCompletionOnlyLM, SFTConfig, SFTTrainer

BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
OUTPUT_DIR = "./adapter_output"
RUN_ID = os.environ.get("WANDB_RUN_ID") or uuid.uuid4().hex[:8]

# Qwen2.5's ChatML turn marker - everything before this in each tokenized example
# gets masked out of the loss (see DataCollatorForCompletionOnlyLM below), so the
# model is only ever trained to predict the assistant's YAML, not the system
# prompt or the user's instruction.
RESPONSE_TEMPLATE = "<|im_start|>assistant\n"

LORA_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]


def format_example(example: dict, tokenizer) -> dict:
    text = tokenizer.apply_chat_template(example["messages"], tokenize=False, add_generation_prompt=False)
    return {"text": text}


def upload_to_s3(local_dir: str) -> None:
    bucket = os.environ.get("CHECKPOINT_BUCKET")
    if not bucket:
        print("CHECKPOINT_BUCKET not set - skipping S3 upload.")
        return

    import boto3

    s3 = boto3.client("s3")
    prefix = f"k8s-yaml-lora/{RUN_ID}"
    for root, _, files in os.walk(local_dir):
        for name in files:
            local_path = os.path.join(root, name)
            key = f"{prefix}/{os.path.relpath(local_path, local_dir)}"
            s3.upload_file(local_path, bucket, key)
    print(f"Uploaded adapter to s3://{bucket}/{prefix}/")


def push_to_hub(model, tokenizer) -> None:
    repo_id = os.environ.get("HF_HUB_REPO_ID")
    if not repo_id:
        print("HF_HUB_REPO_ID not set - skipping Hub push.")
        return

    token = os.environ.get("HF_TOKEN")
    model.push_to_hub(repo_id, token=token)
    tokenizer.push_to_hub(repo_id, token=token)
    print(f"Pushed adapter to https://huggingface.co/{repo_id}")


def main() -> None:
    wandb_project = os.environ.get("WANDB_PROJECT")
    report_to = "wandb" if wandb_project else "none"
    if wandb_project:
        wandb.init(project=wandb_project, entity=os.environ.get("WANDB_ENTITY"), name=f"k8s-yaml-lora-{RUN_ID}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.bfloat16, device_map="auto")

    dataset = load_dataset(
        "json",
        data_files={"train": "data/train.jsonl", "eval": "data/eval.jsonl"},
    )
    dataset = dataset.map(lambda ex: format_example(ex, tokenizer), remove_columns=["messages"])

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=LORA_TARGET_MODULES,
        task_type="CAUSAL_LM",
    )

    # For smoke-testing the pipeline (does it download/train/save correctly?) without
    # waiting for a full run - e.g. MAX_STEPS=5 python train.py. Unset for a real run.
    max_steps = int(os.environ["MAX_STEPS"]) if "MAX_STEPS" in os.environ else -1

    training_args = SFTConfig(
        output_dir="./checkpoints",
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        num_train_epochs=3,
        max_steps=max_steps,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        gradient_checkpointing=True,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="no",  # only the final adapter matters, saved explicitly below
        max_seq_length=1024,
        dataset_text_field="text",
        report_to=report_to,
    )

    collator = DataCollatorForCompletionOnlyLM(RESPONSE_TEMPLATE, tokenizer=tokenizer)

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["eval"],
        peft_config=lora_config,
        data_collator=collator,
    )

    trainer.train()

    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"Saved adapter to {OUTPUT_DIR}")

    upload_to_s3(OUTPUT_DIR)
    push_to_hub(trainer.model, tokenizer)

    if wandb_project:
        wandb.finish()


if __name__ == "__main__":
    main()
