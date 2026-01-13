import logging

from kubernetes import client, config
from app.config import config as app_config
from app.k8s_job.interface_kubernetes_service import IKubernetesService


class KubernetesService(IKubernetesService):
    logger = logging.getLogger(__name__)

    def __init__(self):
        try:
            config.load_kube_config(config_file=app_config.KUBE_CONFIG_FILE_DIR)
        except config.ConfigException as e:
            self.logger.error(f"Kube Config Exception: {e}")


    async def list_pods(self):
        v1 = client.CoreV1Api()
        thread = v1.list_pod_for_all_namespaces(watch=False, async_req=True)
        response = thread.get()

        return response.items