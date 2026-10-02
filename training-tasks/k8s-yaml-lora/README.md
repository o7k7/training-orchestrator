# k8s-yaml-lora

LoRA fine-tunes Qwen2.5-7B-Instruct to generate Kubernetes manifest YAML from
natural-language instructions, then evaluates the base model against the
fine-tuned one by checking what fraction of generated manifests actually pass
[kubeconform](https://github.com/yannh/kubeconform) schema validation.

## Data

`data/train.jsonl` (203 examples) / `data/eval.jsonl` (23 examples) - real
(instruction, YAML) pairs mined from the official Kubernetes documentation
(`kubernetes/website`), not synthetic. See `data/build_dataset.py` for the
extraction pipeline and its docstring/comments for exactly how pairs were
selected and filtered.

## Running

This is meant to run as a training job submitted to the training-orchestrator
platform (see the repo root), which clones this whole repo into the job's
container at `/code` and runs whatever `command` the job specifies from there
- so `train.py`/`eval.py` expect to run with this directory as the working
directory (`cd training-tasks/k8s-yaml-lora`), reading `data/*.jsonl` relatively.

**Strongly recommended: smoke-test locally on a real GPU before submitting to
any cloud infra that bills by the hour.** If you have a local kind cluster with
GPU passthrough set up (see `docs/gpu-scheduling-and-kueue.md` for how that was
done for this project), submit against that first.

**Important: the real base model needs ~24GB VRAM and will OOM on a smaller
GPU** (e.g. an 8GB laptop GPU) just loading the weights, regardless of
`MAX_STEPS`. For a local smoke test, override `BASE_MODEL` to something tiny -
this doesn't produce a meaningful fine-tune, it only proves the pipeline
mechanics (data loading, LoRA/collator wiring, save, S3/Hub push, W&B, the
kubeconform eval loop) actually work end to end:

```bash
docker build -t k8s-yaml-lora:local .
kind load docker-image k8s-yaml-lora:local --name <your-gpu-cluster>

python -m cli.main submit \
  --image k8s-yaml-lora:local \
  --repo-url <this-repo-url> \
  --command "cd training-tasks/k8s-yaml-lora && BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct MAX_STEPS=5 python train.py && BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct EVAL_LIMIT=2 python eval.py" \
  --experiment-id k8s-yaml-lora-smoketest \
  --gpu 1 \
  --cpu 4 --memory 8Gi \
  --deadline 1800
```

Only once that's confirmed working should you drop `BASE_MODEL`/`MAX_STEPS`/
`EVAL_LIMIT` for a real run, and only then point the same job at a real
(billed) GPU node group with enough VRAM (e.g. `g5.xlarge`, 24GB A10G - see
`infra/gpu-node-group`).

### Optional: W&B tracking

Submit with `--wandb-project <project>` (and optionally `--wandb-entity`) - the
platform injects `WANDB_API_KEY`/`WANDB_PROJECT`/`WANDB_ENTITY`, `train.py`
picks them up automatically. Omit to skip W&B entirely; training still runs
and logs to stdout.

### Optional: push the adapter to Hugging Face Hub

Submit with `--push-to-hub-repo <user>/<repo>` - the platform injects
`HF_TOKEN`/`HF_HUB_REPO_ID`, `train.py` picks them up automatically. Requires
`secrets.hfToken` to be set on the orchestrator's Helm release.

### Optional: upload the adapter to S3

Not a platform-level field - pass the bucket name inline in the job's `command`
itself, e.g.:
```
CHECKPOINT_BUCKET=<your-bucket> python train.py
```
Uses the training-job ServiceAccount's IRSA role (see
`infra/irsa-training-job-s3`) - no credentials needed in the command itself.

## What `eval.py` actually measures

Loads the base model once, generates on all 23 held-out eval instructions,
extracts the YAML from each response and validates it with `kubeconform`.
Then applies the LoRA adapter to the *same* loaded model (no second 7B copy in
memory) and repeats. Reports "N/23 schema-valid" for both, and writes full
per-example output to `eval_results.json` for inspection.

This measures manifest *validity*, not semantic correctness (whether the
generated manifest actually does what the instruction asked for) - a valid
but wrong manifest still counts as "valid" here. Worth keeping in mind when
reading the numbers.
