output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  value = module.eks.cluster_certificate_authority_data
}

# Feed this into infra/gpu-node-group's cluster_name variable.
output "oidc_provider_arn" {
  description = "Needed to build any IRSA role's trust policy (e.g. the training-job S3 access role)."
  value       = module.eks.oidc_provider_arn
}

output "oidc_provider_url" {
  value = module.eks.cluster_oidc_issuer_url
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

# Feed this into infra/gpu-node-group's subnet_ids variable.
output "private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "configure_kubectl" {
  description = "Run this after apply to point kubectl at the new cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region} --profile training-orchestrator"
}
