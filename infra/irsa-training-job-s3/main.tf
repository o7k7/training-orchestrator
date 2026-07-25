locals {
  # IAM's OIDC condition key wants the issuer host+path, no scheme.
  oidc_provider_host = replace(var.oidc_provider_url, "https://", "")
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # Scopes this role to exactly one ServiceAccount - not "anything in this cluster,"
    # not even "anything in this namespace."
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider_host}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account_name}"]
    }
  }
}

resource "aws_iam_role" "training_job_s3" {
  name               = "training-job-s3-access"
  assume_role_policy = data.aws_iam_policy_document.trust.json
  tags               = var.tags
}

resource "aws_s3_bucket" "checkpoints" {
  count         = var.create_bucket ? 1 : 0
  bucket        = var.bucket_name
  force_destroy = var.force_destroy_bucket
  tags          = var.tags
}

data "aws_iam_policy_document" "s3_access" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.bucket_name}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.bucket_name}"]
  }
}

resource "aws_iam_role_policy" "s3_access" {
  name   = "s3-checkpoint-access"
  role   = aws_iam_role.training_job_s3.id
  policy = data.aws_iam_policy_document.s3_access.json
}
