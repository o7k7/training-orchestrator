from pydantic_settings import SettingsConfigDict, BaseSettings

class Config(BaseSettings):
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str
    KUBE_CONFIG_FILE_DIR: str

    model_config = SettingsConfigDict(
        env_file ='.env',
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

config = Config()