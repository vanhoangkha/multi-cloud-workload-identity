variable "project_id" { description = "GCP Project ID" }
variable "project_number" { description = "GCP Project Number" }
variable "aws_account_id" { description = "AWS Account ID (12 digits)" }
variable "pool_id" { default = "aws-pool" }
variable "provider_id" { default = "aws-provider" }
variable "sa_name" { default = "aws-workload-sa" }
variable "sa_roles" {
  default = ["roles/bigquery.dataViewer", "roles/bigquery.jobUser"]
}

resource "google_iam_workload_identity_pool" "aws" {
  workload_identity_pool_id = var.pool_id
  display_name              = "AWS Pool"
  project                   = var.project_id
}

resource "google_iam_workload_identity_pool_provider" "aws" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.aws.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  project                            = var.project_id
  attribute_mapping                  = { "google.subject" = "assertion.arn" }
  aws { account_id = var.aws_account_id }
}

resource "google_service_account" "workload" {
  account_id   = var.sa_name
  display_name = "AWS Workload SA"
  project      = var.project_id
}

resource "google_project_iam_member" "sa_roles" {
  for_each = toset(var.sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.workload.email}"
}

output "pool_name" { value = google_iam_workload_identity_pool.aws.name }
output "provider_name" { value = google_iam_workload_identity_pool_provider.aws.name }
output "service_account_email" { value = google_service_account.workload.email }
