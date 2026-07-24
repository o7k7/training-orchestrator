#!/usr/bin/env bash
# Installs the Kubernetes-layer charts onto an already-existing cluster (run
# infra/deploy.sh first): nvidia-device-plugin -> kueue-stack (two-step bootstrap,
# same dance we hit locally) -> orchestrator, then bumps Kueue's GPU quota.
#
# Usage:
#   ORCHESTRATOR_IMAGE_REPO=<account>.dkr.ecr.eu-central-1.amazonaws.com/training-orchestrator \
#   ORCHESTRATOR_IMAGE_TAG=v1 \
#   TRAINING_JOB_ROLE_ARN=<from infra/deploy.sh's printed output> \
#   API_KEY=<a real secret, e.g. `openssl rand -hex 32`> \
#   ./k8s-deploy.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPU_QUOTA="${GPU_QUOTA:-1}"
AUTO_YES=false

for arg in "$@"; do
  case "$arg" in
    -y|--yes) AUTO_YES=true ;;
  esac
done

for var in ORCHESTRATOR_IMAGE_REPO ORCHESTRATOR_IMAGE_TAG TRAINING_JOB_ROLE_ARN API_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "$var is required." >&2
    exit 1
  fi
done

CURRENT_CONTEXT="$(kubectl config current-context)"

echo "=================================================================="
echo "kubectl context: $CURRENT_CONTEXT"
echo "About to helm install/upgrade, in order:"
echo "  1. nvidia-device-plugin  (namespace kube-system)"
echo "  2. kueue-stack           (namespace kueue-system; bootstrap then GPU quota=$GPU_QUOTA)"
echo "  3. orchestrator          (namespace default; image $ORCHESTRATOR_IMAGE_REPO:$ORCHESTRATOR_IMAGE_TAG)"
echo
echo "Double-check that context is your real EKS cluster, not a local kind cluster"
echo "(kind-spectraops-dev / kind-gpu-test) - this script doesn't guess for you."
echo "=================================================================="

if [ "$AUTO_YES" = false ]; then
  read -r -p "Type 'yes' to continue: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
fi

echo
echo "--- [1/3] nvidia-device-plugin ---"
cd "$REPO_ROOT/k8s/cluster-addons/nvidia-device-plugin"
helm dependency build .
helm upgrade --install nvidia-device-plugin . --namespace kube-system --wait --timeout 2m

echo
echo "--- [2/3] kueue-stack ---"
cd "$REPO_ROOT/k8s/cluster-addons/kueue"
helm dependency build .
# Bootstrap: CRDs may not exist yet on a brand-new cluster, so exclude our
# ClusterQueue/LocalQueue/ResourceFlavor from this first apply (see values.yaml's
# installQueueResources comment for why - this isn't optional on a fresh cluster).
helm upgrade --install kueue-stack . --namespace kueue-system --create-namespace \
  --set installQueueResources=false \
  --wait --timeout 5m
# Now the CRDs + controller exist - safe to add our queue resources for real, and
# set the actual GPU quota now that a GPU node group exists.
helm upgrade kueue-stack . --namespace kueue-system \
  --set installQueueResources=true \
  --set "queue.gpu.nominalQuota=$GPU_QUOTA"

echo
echo "--- [3/3] orchestrator ---"
cd "$REPO_ROOT/k8s/orchestrator"
helm upgrade --install training-orchestrator . --namespace default \
  -f values.yaml -f values-aws.yaml \
  --set "image.repository=$ORCHESTRATOR_IMAGE_REPO" \
  --set "image.tag=$ORCHESTRATOR_IMAGE_TAG" \
  --set "serviceAccount.trainingJob.irsaRoleArn=$TRAINING_JOB_ROLE_ARN" \
  --set "secrets.apiKey=$API_KEY" \
  --wait --timeout 3m

echo
echo "=================================================================="
echo "Done. To reach the API (no Ingress set up - this is a one-shot experiment,"
echo "not a durable service):"
echo "  kubectl port-forward svc/training-orchestrator-service 8080:80"
echo "  export TRAINING_ORCHESTRATOR_URL=http://localhost:8080"
echo "  export TRAINING_ORCHESTRATOR_API_KEY=$API_KEY"
echo "  uv run python -m cli.main submit --gpu 1 ..."
echo "=================================================================="
