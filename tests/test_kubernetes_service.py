from unittest.mock import MagicMock, patch

import pytest

from app.config import config as app_config
from app.k8s_job.models.create_job_request import CreateJobRequest


@pytest.fixture
def service():
    with patch("app.k8s_job.kubernetes_service.config.load_kube_config"):
        from app.k8s_job.kubernetes_service import KubernetesService

        svc = KubernetesService()

    svc.batch_api = MagicMock()
    thread = MagicMock()
    thread.get.return_value = MagicMock(status="Running")
    svc.batch_api.create_namespaced_job.return_value = thread
    return svc


def _submit(service, **overrides):
    req = CreateJobRequest(
        image_name="python:3.12-slim",
        repo_url="https://github.com/example/repo.git",
        experiment_id="exp-1",
        **overrides,
    )
    service.create_training_job(req)
    _, kwargs = service.batch_api.create_namespaced_job.call_args
    return kwargs["body"]


def test_default_deadline_replaces_old_30_second_bug(service):
    job = _submit(service)

    assert job.spec.active_deadline_seconds == app_config.DEFAULT_JOB_DEADLINE_SECONDS
    assert job.spec.active_deadline_seconds != 30


def test_custom_deadline_overrides_default(service):
    job = _submit(service, active_deadline_seconds=99)

    assert job.spec.active_deadline_seconds == 99


def test_resource_requests_are_wired_into_container(service):
    job = _submit(service, cpu_request="2", memory_request="4Gi")

    resources = job.spec.template.spec.containers[0].resources
    assert resources.requests == {"cpu": "2", "memory": "4Gi"}
    assert resources.limits == {"cpu": "2", "memory": "4Gi"}


def test_namespace_comes_from_config(service, monkeypatch):
    monkeypatch.setattr(app_config, "K8S_NAMESPACE", "training-ns")

    _submit(service)

    _, kwargs = service.batch_api.create_namespaced_job.call_args
    assert kwargs["namespace"] == "training-ns"


def test_training_pod_uses_dedicated_service_account(service, monkeypatch):
    monkeypatch.setattr(app_config, "TRAINING_JOB_SERVICE_ACCOUNT", "training-job-sa")

    job = _submit(service)

    assert job.spec.template.spec.service_account_name == "training-job-sa"


def test_s3_env_vars_omitted_when_no_s3_endpoint_configured(service, monkeypatch):
    monkeypatch.setattr(app_config, "S3_ENDPOINT", None)

    job = _submit(service)

    env_names = {e.name for e in job.spec.template.spec.containers[0].env}
    assert "AWS_ACCESS_KEY_ID" not in env_names
    assert "MLFLOW_S3_ENDPOINT_URL" not in env_names


def test_s3_env_vars_included_when_s3_endpoint_configured(service, monkeypatch):
    monkeypatch.setattr(app_config, "S3_ENDPOINT", "http://seaweedfs:8333")

    job = _submit(service)

    env = {e.name: e for e in job.spec.template.spec.containers[0].env}
    assert "AWS_ACCESS_KEY_ID" in env
    # Must come from a Secret, never as a plaintext value in the Job spec.
    assert env["AWS_ACCESS_KEY_ID"].value is None
    assert env["AWS_ACCESS_KEY_ID"].value_from.secret_key_ref.name == app_config.TRAINING_JOB_SECRETS_NAME
    assert env["AWS_ACCESS_KEY_ID"].value_from.secret_key_ref.key == "AWS_ACCESS_KEY_ID"


def test_wandb_env_vars_omitted_when_no_project_set(service):
    job = _submit(service)

    env_names = {e.name for e in job.spec.template.spec.containers[0].env}
    assert "WANDB_API_KEY" not in env_names
    assert "WANDB_PROJECT" not in env_names
    assert "WANDB_ENTITY" not in env_names


def test_wandb_env_vars_included_when_project_set(service):
    job = _submit(service, wandb_project="my-project", wandb_entity="my-team")

    env = {e.name: e for e in job.spec.template.spec.containers[0].env}
    assert env["WANDB_PROJECT"].value == "my-project"
    assert env["WANDB_ENTITY"].value == "my-team"
    # API key must come from a Secret, never as a plaintext value in the Job spec.
    assert env["WANDB_API_KEY"].value is None
    assert env["WANDB_API_KEY"].value_from.secret_key_ref.name == app_config.TRAINING_JOB_SECRETS_NAME
    assert env["WANDB_API_KEY"].value_from.secret_key_ref.key == "WANDB_API_KEY"


def test_wandb_entity_omitted_when_not_set(service):
    job = _submit(service, wandb_project="my-project")

    env_names = {e.name for e in job.spec.template.spec.containers[0].env}
    assert "WANDB_PROJECT" in env_names
    assert "WANDB_API_KEY" in env_names
    assert "WANDB_ENTITY" not in env_names


def test_job_is_suspended_and_labeled_for_kueue(service):
    job = _submit(service)

    assert job.spec.suspend is True
    assert job.metadata.labels["kueue.x-k8s.io/queue-name"] == app_config.KUEUE_LOCAL_QUEUE_NAME


def test_cpu_only_job_has_no_gpu_node_selector(service):
    job = _submit(service)

    pod_spec = job.spec.template.spec
    assert pod_spec.node_selector is None
    assert pod_spec.tolerations is None
    assert "nvidia.com/gpu" not in job.spec.template.spec.containers[0].resources.requests


def test_gpu_job_gets_gpu_resources_and_node_selector(service, monkeypatch):
    monkeypatch.setattr(app_config, "GPU_NODE_LABEL_KEY", "nvidia.com/gpu.present")
    monkeypatch.setattr(app_config, "GPU_NODE_LABEL_VALUE", "true")

    job = _submit(service, gpu_request=2)

    pod_spec = job.spec.template.spec
    resources = pod_spec.containers[0].resources
    assert resources.requests["nvidia.com/gpu"] == "2"
    assert resources.limits["nvidia.com/gpu"] == "2"
    assert pod_spec.node_selector == {"nvidia.com/gpu.present": "true"}
    assert pod_spec.tolerations[0].key == "nvidia.com/gpu"
