import logging
import uuid

from kubernetes import client, config
from kubernetes.client import V1PodList, V1Job, V1JobStatus

from app.config import config as app_config, Environment
from app.k8s_job.constants import ORCHESTRATOR_LABEL_KEY, ORCHESTRATOR_LABEL_VALUE
from app.k8s_job.interface_kubernetes_service import IKubernetesService
from app.k8s_job.models.create_job_request import CreateJobRequest
from app.k8s_job.models.create_job_response import CreateJobResponse
from app.metrics import job_creation_latency_seconds, jobs_submitted_total


class KubernetesService(IKubernetesService):
    logger = logging.getLogger(__name__)

    def __init__(self):
        try:
            if app_config.ENVIRONMENT == Environment.LOCAL:
                config.load_kube_config(config_file=app_config.KUBE_CONFIG_FILE_DIR)
            else:
                config.load_incluster_config()
        except config.ConfigException as e:
            self.logger.error(f"Kube Config Exception: {e}")

        # Must be constructed *after* the config loader above: ApiClient()/BatchV1Api()
        # snapshot whatever the default Configuration is at construction time, and
        # load_incluster_config()/load_kube_config() are what populate that default.
        self.k8s_api_client = client.ApiClient()
        self.batch_api = client.BatchV1Api()


    @staticmethod
    def _secret_env_var(env_name: str, secret_key: str) -> client.V1EnvVar:
        return client.V1EnvVar(
            name=env_name,
            value_from=client.V1EnvVarSource(
                secret_key_ref=client.V1SecretKeySelector(
                    name=app_config.TRAINING_JOB_SECRETS_NAME, key=secret_key
                )
            ),
        )

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

        env = [
            client.V1EnvVar(name="MLFLOW_TRACKING_URI", value=app_config.ML_FLOW_URI),
            client.V1EnvVar(name="MLFLOW_EXPERIMENT_ID", value=req.experiment_id),
        ]
        # S3_ENDPOINT is only set for non-AWS S3-compatible stores (e.g. local SeaweedFS/MinIO).
        # On EKS with real S3, credentials come from the pod's IRSA-annotated ServiceAccount instead.
        if app_config.S3_ENDPOINT:
            env.extend([
                client.V1EnvVar(name="MLFLOW_S3_ENDPOINT_URL", value=app_config.S3_ENDPOINT),
                self._secret_env_var("AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
                self._secret_env_var("AWS_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
            ])

        # Weights & Biases is additive to MLflow - the training script owns wandb.init()/
        # wandb.log(), this only injects credentials/config the same way MLflow's env vars do.
        if req.wandb_project:
            env.extend([
                self._secret_env_var("WANDB_API_KEY", "WANDB_API_KEY"),
                client.V1EnvVar(name="WANDB_PROJECT", value=req.wandb_project),
            ])
            if req.wandb_entity:
                env.append(client.V1EnvVar(name="WANDB_ENTITY", value=req.wandb_entity))

        # GPU requests/limits must be equal - the K8s device-plugin API has no notion
        # of a "burstable" GPU request the way it does for CPU/memory.
        resource_quantities = {"cpu": req.cpu_request, "memory": req.memory_request}
        if req.gpu_request > 0:
            resource_quantities["nvidia.com/gpu"] = str(req.gpu_request)

        main_container = client.V1Container(
            name="training-container",
            image=req.image_name,
            working_dir=mount_path,
            command=["/bin/bash", "-c"],
            args=[req.command],
            volume_mounts=[
                client.V1VolumeMount(name=volume_name, mount_path=mount_path)
            ],
            env=env,
            resources=client.V1ResourceRequirements(
                requests=resource_quantities,
                limits=resource_quantities,
            ),
        )

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            service_account_name=app_config.TRAINING_JOB_SERVICE_ACCOUNT,
            init_containers=[git_pull_container],
            containers=[main_container],
            volumes=[shared_volume],
        )
        if req.gpu_request > 0:
            pod_spec.node_selector = {app_config.GPU_NODE_LABEL_KEY: app_config.GPU_NODE_LABEL_VALUE}
            pod_spec.tolerations = [
                client.V1Toleration(key="nvidia.com/gpu", operator="Exists", effect="NoSchedule")
            ]

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name,
                                         labels={
                                             ORCHESTRATOR_LABEL_KEY: ORCHESTRATOR_LABEL_VALUE,
                                             "type": "training-job",
                                             "kueue.x-k8s.io/queue-name": app_config.KUEUE_LOCAL_QUEUE_NAME,
                                             # "user_id": "user_id" # TODO Add for user tracking
                                         }),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(spec=pod_spec),
                ttl_seconds_after_finished=120,
                active_deadline_seconds=req.active_deadline_seconds or app_config.DEFAULT_JOB_DEADLINE_SECONDS,
                backoff_limit=5,
                # Required for Kueue to manage this Job at all - its controller flips
                # this to false once the workload is admitted against queue quota.
                suspend=True,
            )
        )

        gpu_label = str(req.gpu_request > 0)
        try:
            with job_creation_latency_seconds.time():
                thread = self.batch_api.create_namespaced_job(body=job, namespace=app_config.K8S_NAMESPACE, async_req=True)
                response: V1Job = thread.get()
                job_status: V1JobStatus = response.status
        except Exception as e:
            self.logger.error(f"Kubernetes Job Exception: {e}")
            jobs_submitted_total.labels(status="failed", gpu=gpu_label).inc()
            return CreateJobResponse(job_name=job_name, status="Failed")

        jobs_submitted_total.labels(status="created", gpu=gpu_label).inc()
        return CreateJobResponse(job_name=job_name, status=str(job_status))

    def create_kaniko_build_job(self, job_id: str, git_repo: str, image_target: str) -> CreateJobResponse:
        job_name = f"build-{job_id}"

        volume_mount = client.V1VolumeMount(
            name="kaniko-secret",
            mount_path="/kaniko/.docker/",
        )

        volume = client.V1Volume(
            name="kaniko-secret",
            secret=client.V1SecretVolumeSource(
                secret_name="registry_credentials",
                items=[client.V1KeyToPath(key=".dockerconfigjson", path="config.json")]
            )
        )

        container = client.V1Container(
            name="kaniko-builder",
            image="gcr.io/kaniko-project/executor:latest", # TODO obtain from env
            args=[
                f"--context={git_repo}",
                f"--destination={image_target}",
                "--cache=true"
            ],
            volume_mounts=[volume_mount]
        )

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                labels={"type": "builder", ORCHESTRATOR_LABEL_KEY: ORCHESTRATOR_LABEL_VALUE}
            ),
            spec=client.V1JobSpec(
                template=client.V1PodTemplateSpec(
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        containers=[container],
                        volumes=[volume]
                    )
                ),
                backoff_limit=2
            )
        )

        try:
            thread = self.batch_api.create_namespaced_job(namespace=app_config.K8S_NAMESPACE, body=job, async_req=True)
            response: V1Job = thread.get()
            job_status: V1JobStatus = response.status
        except Exception as e:
            self.logger.error(f"Kubernetes Build Job Exception: {e}")
            return CreateJobResponse(job_name=job_name, status="Failed")

        return CreateJobResponse(job_name=job_name, status=str(job_status))