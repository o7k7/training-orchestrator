import asyncio
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

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


def test_hf_env_vars_omitted_when_no_repo_set(service):
    job = _submit(service)

    env_names = {e.name for e in job.spec.template.spec.containers[0].env}
    assert "HF_TOKEN" not in env_names
    assert "HF_HUB_REPO_ID" not in env_names


def test_hf_env_vars_included_when_repo_set(service):
    job = _submit(service, push_to_hub_repo="my-user/my-adapter")

    env = {e.name: e for e in job.spec.template.spec.containers[0].env}
    assert env["HF_HUB_REPO_ID"].value == "my-user/my-adapter"
    # Token must come from a Secret, never as a plaintext value in the Job spec.
    assert env["HF_TOKEN"].value is None
    assert env["HF_TOKEN"].value_from.secret_key_ref.name == app_config.TRAINING_JOB_SECRETS_NAME
    assert env["HF_TOKEN"].value_from.secret_key_ref.key == "HF_TOKEN"


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


def test_get_job_status_returns_none_when_not_found(service):
    service.batch_api.read_namespaced_job_status.side_effect = ApiException(status=404)

    assert service.get_job_status("does-not-exist") is None


def test_get_job_status_reraises_non_404_errors(service):
    service.batch_api.read_namespaced_job_status.side_effect = ApiException(status=500)

    with pytest.raises(ApiException):
        service.get_job_status("training-job-abc123")


def test_get_job_status_returns_sanitized_status(service):
    fake_status = MagicMock()
    service.batch_api.read_namespaced_job_status.return_value = MagicMock(status=fake_status)
    service.k8s_api_client = MagicMock()

    result = service.get_job_status("training-job-abc123")

    service.k8s_api_client.sanitize_for_serialization.assert_called_once_with(fake_status)
    assert result == service.k8s_api_client.sanitize_for_serialization.return_value


def test_get_job_logs_returns_none_when_no_pods(service):
    with patch("app.k8s_job.kubernetes_service.client.CoreV1Api") as MockCoreV1:
        MockCoreV1.return_value.list_namespaced_pod.return_value = MagicMock(items=[])

        assert service.get_job_logs("training-job-abc123") is None


def test_get_job_logs_reads_most_recent_pod(service):
    older_pod = MagicMock()
    older_pod.metadata.name = "training-job-abc123-aaaaa"
    newer_pod = MagicMock()
    newer_pod.metadata.name = "training-job-abc123-bbbbb"

    with patch("app.k8s_job.kubernetes_service.client.CoreV1Api") as MockCoreV1:
        mock_core_v1 = MockCoreV1.return_value
        mock_core_v1.list_namespaced_pod.return_value = MagicMock(items=[older_pod, newer_pod])
        mock_core_v1.read_namespaced_pod_log.return_value = "log output"

        result = service.get_job_logs("training-job-abc123")

        assert result == "log output"
        mock_core_v1.read_namespaced_pod_log.assert_called_once_with(
            name="training-job-abc123-bbbbb",
            namespace=app_config.K8S_NAMESPACE,
            container="training-container",
        )


def test_get_job_logs_returns_empty_string_when_container_not_started(service):
    pod = MagicMock()
    pod.metadata.name = "training-job-abc123-aaaaa"

    with patch("app.k8s_job.kubernetes_service.client.CoreV1Api") as MockCoreV1:
        mock_core_v1 = MockCoreV1.return_value
        mock_core_v1.list_namespaced_pod.return_value = MagicMock(items=[pod])
        mock_core_v1.read_namespaced_pod_log.side_effect = ApiException(status=400)

        assert service.get_job_logs("training-job-abc123") == ""


def test_list_pods_is_scoped_to_configured_namespace(service, monkeypatch):
    # Regression test: list_pod_for_all_namespaces() needs cluster-wide RBAC that this
    # orchestrator's namespace-scoped Role can't grant (403 in practice) - must use the
    # namespaced call instead.
    monkeypatch.setattr(app_config, "K8S_NAMESPACE", "training-ns")

    with patch("app.k8s_job.kubernetes_service.client.CoreV1Api") as MockCoreV1:
        mock_core_v1 = MockCoreV1.return_value
        thread = MagicMock()
        thread.get.return_value = MagicMock()
        mock_core_v1.list_namespaced_pod.return_value = thread
        mock_core_v1.list_pod_for_all_namespaces = MagicMock(
            side_effect=AssertionError("must not call the cluster-wide list")
        )

        asyncio.run(service.list_pods())

        mock_core_v1.list_namespaced_pod.assert_called_once_with(
            namespace="training-ns", watch=False, async_req=True
        )
