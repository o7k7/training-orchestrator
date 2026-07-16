import uuid

from fastapi import APIRouter, Request
from fastapi.params import Depends
from fastapi_limiter.depends import RateLimiter

from app.di.dependencies import get_kubernetes_service
from app.k8s_job.kubernetes_service import KubernetesService
from app.k8s_job.models.create_build_job_request import CreateBuildJobRequest
from app.k8s_job.models.create_job_request import CreateJobRequest
from app.security.auth import verify_api_key

job_router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(verify_api_key)],
)

@job_router.post("/", dependencies=[Depends(RateLimiter(times=5, seconds=10))])
async def create_job(request: CreateJobRequest, kubernetes_service: KubernetesService = Depends(get_kubernetes_service)):
    return kubernetes_service.create_training_job(request)

@job_router.get("/", dependencies=[Depends(RateLimiter(times=5, seconds=10))])
async def list_jobs(kubernetes_service: KubernetesService = Depends(get_kubernetes_service)):
    return await kubernetes_service.list_pods()

@job_router.post("/build", dependencies=[Depends(RateLimiter(times=5, seconds=10))])
async def create_build_job(request: CreateBuildJobRequest, kubernetes_service: KubernetesService = Depends(get_kubernetes_service)):
    job_id = uuid.uuid4().hex[:6]
    return kubernetes_service.create_kaniko_build_job(job_id, request.git_repo, request.image_target)