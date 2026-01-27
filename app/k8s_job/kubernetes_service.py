import logging
import uuid

from kubernetes import client, config
from kubernetes.client import V1PodList, V1Job, V1JobStatus

from app.config import config as app_config, Environment
from app.k8s_job.interface_kubernetes_service import IKubernetesService
from app.k8s_job.models.create_job_request import CreateJobRequest
from app.k8s_job.models.create_job_response import CreateJobResponse


class KubernetesService(IKubernetesService):
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.k8s_api_client = client.ApiClient()
        self.batch_api = client.BatchV1Api()

        try:
            if app_config.ENVIRONMENT == Environment.LOCAL:
                config.load_kube_config(config_file=app_config.KUBE_CONFIG_FILE_DIR)
            else:
                config.load_incluster_config()
        except config.ConfigException as e:
            self.logger.error(f"Kube Config Exception: {e}")


    async def list_pods(self):
        v1 = client.CoreV1Api()
        thread = v1.list_pod_for_all_namespaces(watch=False, async_req=True)
        response: V1PodList = thread.get()
        return self.k8s_api_client.sanitize_for_serialization(response)

    def create_training_job(self, req: CreateJobRequest) -> CreateJobResponse:
        job_name = f"training-job-{uuid.uuid4().hex[:6]}"

        volume_name = "temp-code-volume"
        mount_path = "/code"
        shared_volume = client.V1Volume(
            name=volume_name,
            empty_dir=client.V1EmptyDirVolumeSource()
        )

        git_pull_container = client.V1Container(
            name="git-cloner",
            image="alpine/git",
            args=[
                "clone",
                "--single-branch",
                "--branch", req.branch,
                req.repo_url,
                mount_path,
            ],
            volume_mounts=[
                client.V1VolumeMount(name=volume_name, mount_path=mount_path)
            ],
        )

        main_container = client.V1Container(
            name="training-container",
            image=req.image_name,
            working_dir=mount_path,
            command=["/bin/bash", "-c"],
            args=[req.command],
            volume_mounts=[
                client.V1VolumeMount(name=volume_name, mount_path=mount_path)
            ],
            env=[
                client.V1EnvVar(name="MLFLOW_TRACKING_URI", value=app_config.ML_FLOW_URI),
                client.V1EnvVar(name="MLFLOW_EXPERIMENT_ID", value=req.experiment_id),

                client.V1EnvVar(name="MLFLOW_S3_ENDPOINT_URL", value=app_config.S3_ENDPOINT),
                client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=app_config.AWS_KEY),
                client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=app_config.AWS_SECRET),
            ]
        )

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            init_containers=[git_pull_container],
            containers=[main_container],
            volumes=[shared_volume],
        )

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name,
                                         labels={
                                             "app": "orchestrator",
                                             "type": "training-job",
                                             # "user_id": "user_id" # TODO Add for user tracking
                                         }),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(spec=pod_spec),
                ttl_seconds_after_finished=120,
                active_deadline_seconds=30,
                backoff_limit=5
            )
        )

        try:
            thread = self.batch_api.create_namespaced_job(body=job, namespace="default", async_req=True)
            response: V1Job = thread.get()
            job_status: V1JobStatus = response.status
        except Exception as e:
            self.logger.error(f"Kubernetes Job Exception: {e}")
            return CreateJobResponse(job_name=job_name, status="Failed")

        return CreateJobResponse(job_name=job_name, status=str(job_status))