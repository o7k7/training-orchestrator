import os
import sys

import httpx
import typer

app = typer.Typer(help="CLI for the training-orchestrator API.")


def _base_url() -> str:
    url = os.environ.get("TRAINING_ORCHESTRATOR_URL")
    if not url:
        typer.echo("TRAINING_ORCHESTRATOR_URL is not set (e.g. http://localhost:8080)", err=True)
        raise typer.Exit(code=1)
    return url.rstrip("/")


def _api_key() -> str:
    key = os.environ.get("TRAINING_ORCHESTRATOR_API_KEY")
    if not key:
        typer.echo("TRAINING_ORCHESTRATOR_API_KEY is not set", err=True)
        raise typer.Exit(code=1)
    return key


def _client() -> httpx.Client:
    return httpx.Client(base_url=_base_url(), headers={"X-API-Key": _api_key()}, timeout=30.0)


def _fail_on_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    typer.echo(f"Error {response.status_code}: {response.text}", err=True)
    raise typer.Exit(code=1)


@app.command()
def submit(
    image: str = typer.Option(..., "--image", help="Container image to run"),
    repo_url: str = typer.Option(..., "--repo-url", help="Git repository URL to clone"),
    branch: str = typer.Option("main", "--branch"),
    command: str = typer.Option("train.py", "--command"),
    experiment_id: str = typer.Option(..., "--experiment-id"),
    cpu: str = typer.Option("500m", "--cpu", help="CPU request, e.g. 500m or 2"),
    memory: str = typer.Option("1Gi", "--memory", help="Memory request, e.g. 1Gi"),
    gpu: int = typer.Option(0, "--gpu", help="Number of GPUs to request"),
    deadline: int | None = typer.Option(None, "--deadline", help="Max runtime in seconds"),
    wandb_project: str | None = typer.Option(None, "--wandb-project"),
    wandb_entity: str | None = typer.Option(None, "--wandb-entity"),
    push_to_hub_repo: str | None = typer.Option(None, "--push-to-hub-repo", help="HF Hub repo id to push results to, e.g. user/my-adapter"),
):
    """Submit a training job."""
    payload = {
        "image_name": image,
        "repo_url": repo_url,
        "branch": branch,
        "command": command,
        "experiment_id": experiment_id,
        "cpu_request": cpu,
        "memory_request": memory,
        "gpu_request": gpu,
    }
    if deadline is not None:
        payload["active_deadline_seconds"] = deadline
    if wandb_project:
        payload["wandb_project"] = wandb_project
        if wandb_entity:
            payload["wandb_entity"] = wandb_entity
    if push_to_hub_repo:
        payload["push_to_hub_repo"] = push_to_hub_repo

    with _client() as client:
        response = client.post("/api/v1/jobs/", json=payload)
    _fail_on_error(response)
    body = response.json()
    typer.echo(f"Submitted: {body['job_name']} ({body['status']})")


@app.command(name="list")
def list_jobs():
    """List all pods across the cluster (not scoped to training jobs only)."""
    with _client() as client:
        response = client.get("/api/v1/jobs/")
    _fail_on_error(response)
    items = response.json().get("items", [])
    if not items:
        typer.echo("No pods found.")
        return

    rows = []
    for item in items:
        metadata = item.get("metadata", {})
        rows.append(
            (
                metadata.get("name", "?"),
                metadata.get("namespace", "?"),
                item.get("status", {}).get("phase", "?"),
                item.get("spec", {}).get("nodeName", "-"),
            )
        )

    name_w = max(len(r[0]) for r in rows + [("NAME", "", "", "")])
    ns_w = max(len(r[1]) for r in rows + [("", "NAMESPACE", "", "")])
    phase_w = max(len(r[2]) for r in rows + [("", "", "PHASE", "")])
    header = f"{'NAME':<{name_w}}  {'NAMESPACE':<{ns_w}}  {'PHASE':<{phase_w}}  NODE"
    typer.echo(header)
    for name, namespace, phase, node in rows:
        typer.echo(f"{name:<{name_w}}  {namespace:<{ns_w}}  {phase:<{phase_w}}  {node}")


@app.command()
def status(job_name: str = typer.Argument(..., help="Job name, e.g. training-job-abc123")):
    """Show a training job's K8s Job status."""
    with _client() as client:
        response = client.get(f"/api/v1/jobs/{job_name}")
    _fail_on_error(response)
    typer.echo(response.json())


@app.command()
def logs(job_name: str = typer.Argument(..., help="Job name, e.g. training-job-abc123")):
    """Show a training job's pod logs."""
    with _client() as client:
        response = client.get(f"/api/v1/jobs/{job_name}/logs")
    _fail_on_error(response)
    typer.echo(response.text)


if __name__ == "__main__":
    app()
