from fastapi import APIRouter, Request
from fastapi.params import Depends
from fastapi_limiter.depends import RateLimiter

from app.k8s_job.kubernetes_service import KubernetesService

job_router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
)

@job_router.post("/", dependencies=[Depends(RateLimiter(times=5, seconds=10))])
async def create_job(request: Request, kubernetes_service: KubernetesService = Depends(KubernetesService)):
    return kubernetes_service.list_pods()

@job_router.get("/", dependencies=[Depends(RateLimiter(times=5, seconds=10))])
async def list_jobs(kubernetes_service: KubernetesService = Depends(KubernetesService)):
    return await kubernetes_service.list_pods()