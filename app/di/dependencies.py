from app.k8s_job.interface_kubernetes_service import IKubernetesService
from app.k8s_job.kubernetes_service import KubernetesService


def get_kubernetes_service() -> IKubernetesService:
    return KubernetesService()