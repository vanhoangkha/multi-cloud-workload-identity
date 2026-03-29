variable "project_id" { description = "GCP Project ID" }
variable "project_number" { description = "GCP Project Number" }
variable "azure_tenant_id" { description = "Azure Entra ID Tenant ID" }
variable "azure_app_id_uri" { description = "Azure App ID URI" }
variable "pool_id" { default = "azure-pool" }
variable "provider_id" { default = "azure-provider" }
variable "sa_name" { default = "azure-workload-sa" }
variable "sa_roles" {
  default = ["roles/bigquery.dataViewer", "roles/bigquery.jobUser"]
}

resource "google_iam_workload_identity_pool" "azure" {
  workload_identity_pool_id = var.pool_id
  display_name              = "Azure Pool"
  project                   = var.project_id
}

resource "google_iam_workload_identity_pool_provider" "azure" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.azure.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  project                            = var.project_id
  attribute_mapping                  = { "google.subject" = "assertion.sub" }
  oidc {
    issuer_uri        = "https://sts.windows.net/${var.azure_tenant_id}/"
    allowed_audiences = [var.azure_app_id_uri]
  }
}

resource "google_service_account" "workload" {
  account_id   = var.sa_name
  display_name = "Azure Workload SA"
  project      = var.project_id
}

resource "google_project_iam_member" "sa_roles" {
  for_each = toset(var.sa_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.workload.email}"
}

output "pool_name" { value = google_iam_workload_identity_pool.azure.name }
output "provider_name" { value = google_iam_workload_identity_pool_provider.azure.name }
output "service_account_email" { value = google_service_account.workload.email }
