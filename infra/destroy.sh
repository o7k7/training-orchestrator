#!/usr/bin/env bash
# Tears down infra/irsa-training-job-s3, infra/gpu-node-group, and infra/eks-cluster,
# in that order (the cluster must go last - the other two depend on it existing).
# Requires the same -var values used at apply time for gpu-node-group and
# irsa-training-job-s3, since destroy still needs to know what it's destroying.
#
# Usage:
#   AWS_PROFILE=training-orchestrator BUCKET_NAME=my-unique-bucket-name ./destroy.sh
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
  echo "BUCKET_NAME is required - must match what deploy.sh was run with." >&2
  exit 1
fi

export AWS_PROFILE AWS_REGION

echo "=================================================================="
echo "About to DESTROY, in order, against AWS account/profile: $AWS_PROFILE"
echo "  1. infra/irsa-training-job-s3  (IAM role; bucket $BUCKET_NAME too, if create_bucket=$CREATE_BUCKET)"
echo "  2. infra/gpu-node-group        (GPU node group)"
echo "  3. infra/eks-cluster           (VPC, EKS control plane, default node group)"
echo
if [ "$CREATE_BUCKET" = true ] && [ "$FORCE_DESTROY_BUCKET" != true ]; then
  echo "NOTE: force_destroy_bucket is false - if the bucket still has checkpoint"
  echo "objects in it, step 1 will fail. Empty it manually first, or re-run with"
  echo "FORCE_DESTROY_BUCKET=true to delete it (and everything in it) unconditionally."
  echo
fi
echo "This is destructive and cannot be undone."
echo "=================================================================="

if [ "$AUTO_YES" = false ]; then
  read -r -p "Type 'yes' to continue: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
fi

# eks-cluster's state still exists at this point (we destroy it last), so its outputs
# are still readable without re-applying anything - same values irsa-training-job-s3
# was originally applied with.
OIDC_PROVIDER_ARN="$(cd "$SCRIPT_DIR/eks-cluster" && terraform output -raw oidc_provider_arn)"
OIDC_PROVIDER_URL="$(cd "$SCRIPT_DIR/eks-cluster" && terraform output -raw oidc_provider_url)"

echo
echo "--- [1/3] infra/irsa-training-job-s3 ---"
cd "$SCRIPT_DIR/irsa-training-job-s3"
terraform destroy -auto-approve \
  -var "oidc_provider_arn=$OIDC_PROVIDER_ARN" \
  -var "oidc_provider_url=$OIDC_PROVIDER_URL" \
  -var "bucket_name=$BUCKET_NAME" \
  -var "create_bucket=$CREATE_BUCKET" \
  -var "force_destroy_bucket=$FORCE_DESTROY_BUCKET"

CLUSTER_NAME="$(cd "$SCRIPT_DIR/eks-cluster" && terraform output -raw cluster_name)"
SUBNET_IDS_JSON="$(cd "$SCRIPT_DIR/eks-cluster" && terraform output -json private_subnet_ids)"

echo
echo "--- [2/3] infra/gpu-node-group ---"
cd "$SCRIPT_DIR/gpu-node-group"
terraform destroy -auto-approve \
  -var "cluster_name=$CLUSTER_NAME" \
  -var "subnet_ids=$SUBNET_IDS_JSON"

echo
echo "--- [3/3] infra/eks-cluster ---"
cd "$SCRIPT_DIR/eks-cluster"
terraform destroy -auto-approve

echo
echo "Done. Verify nothing billable is left: aws eks list-clusters --profile $AWS_PROFILE"
