variable "oidc_provider_arn" {
  description = "From infra/eks-cluster's oidc_provider_arn output."
  type        = string
}

variable "oidc_provider_url" {
  description = "From infra/eks-cluster's oidc_provider_url output (with or without the https:// scheme - stripped internally)."
  type        = string
}

variable "namespace" {
  description = "Must match app.config.Config.K8S_NAMESPACE."
  type        = string
  default     = "default"
}

variable "service_account_name" {
  description = "Must match k8s/orchestrator values.yaml's serviceAccount.trainingJob.name."
  type        = string
  default     = "training-job-sa"
}

variable "bucket_name" {
  description = "S3 bucket for training checkpoints. Must be globally unique if create_bucket is true."
  type        = string
}

variable "create_bucket" {
  description = "If true, Terraform creates bucket_name. If false, it must already exist - this role is just granted access to it."
  type        = bool
  default     = true
}

variable "force_destroy_bucket" {
  description = "Allow `terraform destroy` to delete the bucket even if it still has checkpoint objects in it. Only applies when create_bucket is true. Defaults to false - a one-day experiment tearing itself down is a reasonable case to flip this to true, but it's an explicit opt-in, not silent by default."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
