variable "cluster_name" {
  description = "Name of the EKS cluster. infra/gpu-node-group's cluster_name must match this."
  type        = string
  default     = "training-orchestrator"
}

variable "kubernetes_version" {
  description = "EKS control plane version. Matches the kind version (v1.31.0) used for local testing."
  type        = string
  default     = "1.31"
}

variable "region" {
  description = "AWS region. Set AWS_REGION/--profile region to match when running terraform."
  type        = string
  default     = "eu-central-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread subnets across. EKS requires at least 2."
  type        = list(string)
  default     = ["eu-central-1a", "eu-central-1b"]
}

variable "single_nat_gateway" {
  description = "One NAT gateway shared across AZs (cheaper) instead of one per AZ (more resilient)."
  type        = bool
  default     = true
}

# Sizing for the *default* (non-GPU) node group - system pods, the orchestrator itself,
# the observability stack. GPU capacity is a separate node group (see infra/gpu-node-group),
# attached to this same cluster by name after it's created.
variable "default_node_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

variable "default_node_desired_size" {
  type    = number
  default = 2
}

variable "default_node_min_size" {
  type    = number
  default = 1
}

variable "default_node_max_size" {
  type    = number
  default = 3
}

# Restrict this in any real deployment - defaults to open for initial setup convenience.
variable "cluster_endpoint_public_access_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "tags" {
  type    = map(string)
  default = {}
}
