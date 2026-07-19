from enum import Enum

from kubernetes.config import KUBE_CONFIG_DEFAULT_LOCATION
from pydantic_settings import SettingsConfigDict, BaseSettings

class Environment(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

class Config(BaseSettings):
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str
    KUBE_CONFIG_FILE_DIR: str = KUBE_CONFIG_DEFAULT_LOCATION

    ML_FLOW_URI: str
    # Only set for S3-compatible endpoints that aren't real AWS S3 (e.g. local SeaweedFS/MinIO).
    # Left unset on EKS, where the training job's ServiceAccount uses IRSA instead of static keys.
    S3_ENDPOINT: str | None = None

    API_KEY: str

    # K8s Secret (in K8S_NAMESPACE) that training job pods pull credentials from via
    # secretKeyRef. This holds AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (only used when S3_ENDPOINT is
    # set) and/or WANDB_API_KEY.
    TRAINING_JOB_SECRETS_NAME: str = "training-job-secrets"

    K8S_NAMESPACE: str = "default"
    TRAINING_JOB_SERVICE_ACCOUNT: str = "default"
    DEFAULT_JOB_DEADLINE_SECONDS: int = 21600
    ZOMBIE_JOB_MAX_AGE_SECONDS: int = 86400

    # Kueue's LocalQueue (in K8S_NAMESPACE) that training jobs are submitted through.
    KUEUE_LOCAL_QUEUE_NAME: str = "training-local-queue"
    # Must match the nodeLabels on Kueue's "gpu-flavor" ResourceFlavor and the label
    # applied by the GPU node group (see k8s/cluster-addons/kueue/resources, infra/gpu-node-group).
    GPU_NODE_LABEL_KEY: str = "nvidia.com/gpu.present"
    GPU_NODE_LABEL_VALUE: str = "true"

    ENVIRONMENT: Environment

    model_config = SettingsConfigDict(
        env_file ='.env',
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

config = Config()