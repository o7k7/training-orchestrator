from pydantic import BaseModel, Field


class CreateBuildJobRequest(BaseModel):
    git_repo: str = Field(..., description="Git context URL for the Kaniko build")
    image_target: str = Field(..., description="Destination image reference to push")
