output "role_arn" {
  description = "Set this as k8s/orchestrator values.yaml's serviceAccount.trainingJob.irsaRoleArn."
  value       = aws_iam_role.training_job_s3.arn
}

output "bucket_name" {
  value = var.bucket_name
}
