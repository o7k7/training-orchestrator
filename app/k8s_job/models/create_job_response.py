from pydantic import BaseModel


class CreateJobResponse(BaseModel):
    job_name: str
    status: str