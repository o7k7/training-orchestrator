#!/usr/bin/env bash
# Applies infra/eks-cluster, infra/gpu-node-group, and infra/irsa-training-job-s3 in
# order, passing each module's outputs into the next. Stops for a typed confirmation
# before touching AWS at all, unless -y/--yes is passed.
#
# Usage:
#   AWS_PROFILE=training-orchestrator BUCKET_NAME=my-unique-bucket-name ./deploy.sh
#
# Env vars:
#   AWS_PROFILE  (default: training-orchestrator)
#   AWS_REGION   (default: eu-central-1)
#   BUCKET_NAME  (required) - must be globally unique if CREATE_BUCKET=true
#   CREATE_BUCKET (default: true)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_PROFILE="${AWS_PROFILE:-training-orchestrator}"
AWS_REGION="${AWS_REGION:-eu-central-1}"
CREATE_BUCKET="${CREATE_BUCKET:-true}"
FORCE_DESTROY_BUCKET="${FORCE_DESTROY_BUCKET:-false}"
AUTO_YES=false

for arg in "$@"; do
  case "$arg" in
    -y|--yes) AUTO_YES=true ;;
  esac
done

if [ -z "${BUCKET_NAME:-}" ]; then
  echo "BUCKET_NAME is required (must be globally unique if CREATE_BUCKET=true)." >&2
  exit 1
fi

export AWS_PROFILE AWS_REGION

echo "=================================================================="
echo "About to apply, in order, against AWS account/profile: $AWS_PROFILE"
echo "  region:        $AWS_REGION"
echo "  1. infra/eks-cluster           (VPC, EKS control plane, default node group)"
echo "  2. infra/gpu-node-group        (GPU node group, attached to the cluster above)"
echo "  3. infra/irsa-training-job-s3  (IAM role for S3 checkpoint access; bucket: $BUCKET_NAME, create=$CREATE_BUCKET)"
echo
echo "Rough cost while all of this is running: ~\$8-10/day base cluster + GPU node cost"
echo "(instance-type dependent, see infra/gpu-node-group/variables.tf) for as long as it's up."
echo "Nothing here scales to zero automatically - use destroy.sh when you're done."
echo "=================================================================="

if [ "$AUTO_YES" = false ]; then
  read -r -p "Type 'yes' to continue: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
fi

echo
echo "--- [1/3] infra/eks-cluster ---"
cd "$SCRIPT_DIR/eks-cluster"
terraform init
terraform apply -auto-approve

CLUSTER_NAME="$(terraform output -raw cluster_name)"
SUBNET_IDS_JSON="$(terraform output -json private_subnet_ids)"
OIDC_PROVIDER_ARN="$(terraform output -raw oidc_provider_arn)"
OIDC_PROVIDER_URL="$(terraform output -raw oidc_provider_url)"

echo
echo "--- [2/3] infra/gpu-node-group ---"
cd "$SCRIPT_DIR/gpu-node-group"
terraform init
terraform apply -auto-approve \
  -var "cluster_name=$CLUSTER_NAME" \
  -var "subnet_ids=$SUBNET_IDS_JSON"

echo
echo "--- [3/3] infra/irsa-training-job-s3 ---"
cd "$SCRIPT_DIR/irsa-training-job-s3"
terraform init
terraform apply -auto-approve \
  -var "oidc_provider_arn=$OIDC_PROVIDER_ARN" \
  -var "oidc_provider_url=$OIDC_PROVIDER_URL" \
  -var "bucket_name=$BUCKET_NAME" \
  -var "create_bucket=$CREATE_BUCKET" \
  -var "force_destroy_bucket=$FORCE_DESTROY_BUCKET"

TRAINING_JOB_ROLE_ARN="$(terraform output -raw role_arn)"

echo
echo "--- Configuring kubectl ---"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --profile "$AWS_PROFILE"

echo
echo "=================================================================="
echo "Done. Remaining manual steps:"
echo "  1. Set k8s/orchestrator values: serviceAccount.trainingJob.irsaRoleArn=$TRAINING_JOB_ROLE_ARN"
echo "  2. Push the orchestrator image to a real registry (ECR) - :local kind-loaded"
echo "     images aren't visible to this cluster's nodes."
echo "  3. helm install the device plugin, Kueue (installQueueResources=false then"
echo "     true), and the orchestrator charts against this cluster."
echo "  4. Bump Kueue's GPU quota from 0 to however many GPU nodes you actually have."
echo "  5. When you're done for the day: ./destroy.sh"
echo "=================================================================="
