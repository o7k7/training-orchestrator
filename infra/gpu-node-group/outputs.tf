output "node_group_arn" {
  value = aws_eks_node_group.gpu.arn
}

output "node_role_arn" {
  value = aws_iam_role.gpu_node.arn
}

output "gpu_node_label" {
  value = "${var.gpu_node_label_key}=${var.gpu_node_label_value}"
}
