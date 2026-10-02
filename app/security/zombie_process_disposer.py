import logging
from datetime import datetime, timezone
from kubernetes import client, config
from app.config import config as app_config, Environment
from app.k8s_job.constants import ORCHESTRATOR_LABEL_SELECTOR

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
        namespace=app_config.K8S_NAMESPACE,
        label_selector=ORCHESTRATOR_LABEL_SELECTOR
    )

    now = datetime.now(timezone.utc)

    for job in jobs.items:
        job_name = job.metadata.name
        start_time = job.status.start_time

        if start_time:
            age = (now - start_time).total_seconds()
            if age > app_config.ZOMBIE_JOB_MAX_AGE_SECONDS:
                logger.info(f"Disposing zombie job (Age: {age}s): {job_name}")
                delete_job(batch_v1, job_name)


def delete_job(api, name):
    api.delete_namespaced_job(
        name=name,
        namespace=app_config.K8S_NAMESPACE,
        propagation_policy='Background'
    )


if __name__ == "__main__":
    dispose_jobs()
