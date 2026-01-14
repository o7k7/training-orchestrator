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
    S3_ENDPOINT: str
    AWS_KEY: str
    AWS_SECRET: str

    ENVIRONMENT: Environment

    model_config = SettingsConfigDict(
        env_file ='.env',
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

config = Config()