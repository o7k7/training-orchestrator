from abc import ABC, abstractmethod

from app.k8s_job.models.create_job_request import CreateJobRequest
from app.k8s_job.models.create_job_response import CreateJobResponse


class IKubernetesService(ABC):
    @abstractmethod
    def list_pods(self):
        pass

    @abstractmethod
    def create_training_job(self, req: CreateJobRequest) -> CreateJobResponse:
        pass

    @abstractmethod
    def create_kaniko_build_job(self, job_id: str, git_repo: str, image_target: str) -> CreateJobResponse:
        pass

    @abstractmethod
    def get_job_status(self, job_name: str) -> dict | None:
        pass

    @abstractmethod
    def get_job_logs(self, job_name: str) -> str | None:
        pass