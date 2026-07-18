variable "cluster_name" {
  description = "Name of the existing EKS cluster to attach this GPU node group to."
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs (private, with a NAT/internet route) the GPU node group's instances launch into."
  type        = list(string)
}

variable "instance_types" {
  description = "EC2 instance types for the node group. All must share the same number of GPUs/vCPU/memory shape if using multiple (EKS requirement for a single node group)."
  type        = list(string)
  default     = ["g5.xlarge"]
}

variable "capacity_type" {
  description = "ON_DEMAND or SPOT."
  type        = string
  default     = "ON_DEMAND"
}

variable "ami_type" {
  description = "EKS-optimized accelerated AMI type."
  type        = string
  default     = "AL2023_x86_64_NVIDIA"
}

variable "desired_size" {
  type    = number
  default = 1
}

variable "min_size" {
  type    = number
  default = 0
}

variable "max_size" {
  type    = number
  default = 2
}

variable "disk_size_gb" {
  type    = number
  default = 100
}

# Must match app.config.Config.GPU_NODE_LABEL_KEY/VALUE and the nodeLabels on
# Kueue's "gpu-flavor" ResourceFlavor (k8s/cluster-addons/kueue/resources/resource-flavors.yaml),
# and the nodeSelector on the NVIDIA device plugin DaemonSet
# (k8s/cluster-addons/nvidia-device-plugin.yaml). Changing this value in only one
# of those places will silently break GPU scheduling.
variable "gpu_node_label_key" {
  type    = string
  default = "nvidia.com/gpu.present"
}

variable "gpu_node_label_value" {
  type    = string
  default = "true"
}

# Must match the toleration app.k8s_job.kubernetes_service.KubernetesService adds
# to training pods (key="nvidia.com/gpu", effect="NoSchedule") and the toleration
# on the gpu-flavor ResourceFlavor / device plugin DaemonSet.
variable "gpu_taint_key" {
  type    = string
  default = "nvidia.com/gpu"
}

variable "tags" {
  type    = map(string)
  default = {}
}
