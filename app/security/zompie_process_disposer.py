import logging
from datetime import datetime, timezone
from kubernetes import client, config
from app.config import config as app_config, Environment

MAX_AGE_SECONDS = 3600 * 24
ZOMBIE_TIMEOUT = 3600

logger = logging.getLogger("ZombieProcessDisposer")

def dispose_jobs():
    try:
        if app_config.ENVIRONMENT == Environment.LOCAL:
            config.load_kube_config(config_file=app_config.KUBE_CONFIG_FILE_DIR)
        else:
            config.load_incluster_config()
    except config.ConfigException as e:
        logger.error(f"Kube Config Exception: {e}")

    batch_v1 = client.BatchV1Api()

    jobs = batch_v1.list_namespaced_job(
        namespace="default",
        label_selector="app=orchestrator" # TODO Obtain it from config
    )

    now = datetime.now(timezone.utc)

    for job in jobs.items:
        job_name = job.metadata.name
        start_time = job.status.start_time

        if start_time:
            age = (now - start_time).total_seconds()
            if age > MAX_AGE_SECONDS:
                logger.info(f"Disposing zombie job (Age: {age}s): {job_name}")
                delete_job(batch_v1, job_name)


def delete_job(api, name):
    api.delete_namespaced_job(
        name=name,
        namespace="default",
        propagation_policy='Background'
    )


if __name__ == "__main__":
    dispose_jobs()