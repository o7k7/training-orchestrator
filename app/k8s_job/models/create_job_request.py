from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    image_name: str = Field(..., description="Environment image", examples=["python:3.12-slim"])
    repo_url: str = Field(..., description="Repository URL")
    branch: str = "main"
    command: str = "train.py"

    experiment_id: str = Field(..., description="Experiment ID")
    memory_request: str = "1Gi"
    cpu_request: str = "500m"
    active_deadline_seconds: int | None = Field(
        default=None, description="Max job runtime in seconds before it's killed; defaults to a platform-wide setting"
    )