from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    image_name: str = Field(..., description="Environment image", examples=["python:3.12-slim"])
    repo_url: str = Field(..., description="Repository URL")
    branch: str = "main"
    command: str = "train.py"

    experiment_id: str = Field(..., description="Experiment ID")
    memory_request: str = "1Gi"
    cpu_request: str = "500m"
    gpu_request: int = Field(default=0, description="Number of GPUs to request; routes the job onto GPU nodes via Kueue's gpu-flavor")
    active_deadline_seconds: int | None = Field(
        default=None, description="Max job runtime in seconds before it's killed; defaults to a platform-wide setting"
    )

    # Weights & Biases is additive to MLflow, not a replacement. Leave wandb_project
    # unset to skip W&B entirely; the training script still owns wandb.init()/wandb.log(),
    # this platform only injects credentials/config the same way it does for MLflow.
    wandb_project: str | None = Field(default=None, description="W&B project name; omit to skip W&B entirely")
    wandb_entity: str | None = Field(default=None, description="W&B entity (user/team); only used if wandb_project is set")

    push_to_hub_repo: str | None = Field(
        default=None, description="HF Hub repo id (e.g. 'username/my-adapter') to push the result to; omit to skip"
    )