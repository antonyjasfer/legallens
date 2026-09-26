# LegalLens — Google Cloud Setup & Infrastructure Automation Script
# Configures required Google Cloud services using least privilege security.

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$ProjectId = "",

    [Parameter(Mandatory = $false)]
    [string]$Region = "us-central1"
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LegalLens — Google Cloud Automated Infrastructure Setup" -ForegroundColor Cyan
Write-Host "============================================================"

# 1. Verify gcloud login
Write-Host "`n1. Verifying Google Cloud CLI authentication..." -ForegroundColor Yellow
$activeAccount = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
if (-not $activeAccount) {
    Write-Host "No active gcloud login detected. Initiating authentication..." -ForegroundColor Yellow
    gcloud auth login
    $activeAccount = gcloud auth list --filter=status:ACTIVE --format="value(account)"
}
Write-Host "Authenticated as: $activeAccount" -ForegroundColor Green

# 2. Verify or select Project
Write-Host "`n2. Verifying Google Cloud Project..." -ForegroundColor Yellow
if (-not $ProjectId) {
    $ProjectId = gcloud config get-value project 2>$null
    if (-not $ProjectId) {
        $ProjectId = Read-Host -Prompt "Enter your Google Cloud Project ID"
        gcloud config set project $ProjectId
    }
}
Write-Host "Active GCP Project: $ProjectId" -ForegroundColor Green
Write-Host "Deployment Region:  $Region" -ForegroundColor Green

# 3. Enable only necessary Google Cloud APIs
Write-Host "`n3. Enabling required Google Cloud APIs..." -ForegroundColor Yellow
$requiredApis = @(
    "run.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "documentai.googleapis.com",
    "secretmanager.googleapis.com",
    "generativelanguage.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com"
)

foreach ($api in $requiredApis) {
    Write-Host "  -> Enabling $api..." -NoNewline
    gcloud services enable $api --project=$ProjectId 2>$null
    Write-Host " DONE" -ForegroundColor Green
}

# 4. Create Private Cloud Storage Bucket for Legal PDFs
Write-Host "`n4. Provisioning Private Cloud Storage Bucket..." -ForegroundColor Yellow
$bucketName = "legallens-docs-$ProjectId"
$bucketExists = gsutil ls -b "gs://$bucketName" 2>$null
if (-not $bucketExists) {
    Write-Host "Creating bucket gs://$bucketName with uniform bucket-level access..." -ForegroundColor Yellow
    gcloud storage buckets create "gs://$bucketName" `
        --project=$ProjectId `
        --location=$Region `
        --uniform-bucket-level-access `
        --public-access-prevention
    Write-Host "Bucket created: gs://$bucketName (STRICT PRIVATE ACCESS)" -ForegroundColor Green
} else {
    Write-Host "Bucket already exists: gs://$bucketName" -ForegroundColor Green
}

# 5. Create Cloud Run Dedicated Service Account (Least Privilege)
Write-Host "`n5. Provisioning Cloud Run runtime service account..." -ForegroundColor Yellow
$saName = "legallens-runner"
$saEmail = "$saName@$ProjectId.iam.gserviceaccount.com"

$saExists = gcloud iam service-accounts describe $saEmail --project=$ProjectId 2>$null
if (-not $saExists) {
    Write-Host "Creating service account $saEmail..." -ForegroundColor Yellow
    gcloud iam service-accounts create $saName `
        --description="Dedicated runtime identity for LegalLens Cloud Run service" `
        --display-name="LegalLens Runner SA" `
        --project=$ProjectId
} else {
    Write-Host "Service account $saEmail already exists." -ForegroundColor Green
}

# 6. Assign Minimum Required IAM Roles
Write-Host "`n6. Assigning Least-Privilege IAM Roles to $saEmail..." -ForegroundColor Yellow
$roles = @(
    "roles/storage.objectUser",
    "roles/datastore.user",
    "roles/documentai.apiUser",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter"
)

foreach ($role in $roles) {
    Write-Host "  -> Granting $role..." -NoNewline
    gcloud projects add-iam-policy-binding $ProjectId `
        --member="serviceAccount:$saEmail" `
        --role=$role `
        --condition=None `
        --quiet 2>$null | Out-Null
    Write-Host " OK" -ForegroundColor Green
}

# 7. Document AI Layout Parser Instructions
Write-Host "`n7. Checking Document AI Layout Parser..." -ForegroundColor Yellow
Write-Host "Document AI Layout Parser requires an initial processor to be instantiated." -ForegroundColor Cyan
Write-Host "If you already have a processor ID, enter it below. Otherwise, press Enter to continue with PyMuPDF OCR fallback."
$docAiId = Read-Host -Prompt "Document AI Processor ID (optional, press Enter to skip)"

# 8. Create Secret in Secret Manager
Write-Host "`n8. Google Secret Manager Setup..." -ForegroundColor Yellow
& "$PSScriptRoot\create_secrets.ps1" -ProjectId $ProjectId

# 9. Summary & Output
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "Google Cloud Environment Setup Complete!" -ForegroundColor Green
Write-Host "============================================================"
Write-Host "GCP Project:          $ProjectId"
Write-Host "Region:               $Region"
Write-Host "Storage Bucket:       gs://$bucketName"
Write-Host "Service Account:      $saEmail"
Write-Host "Document AI:          $(if ($docAiId) { $docAiId } else { 'Disabled (local fallback active)' })"
Write-Host "`nTo deploy to Cloud Run, execute:" -ForegroundColor Cyan
Write-Host "  .\scripts\deploy_cloud_run.ps1 -ProjectId $ProjectId -Region $Region -BucketName $bucketName" -ForegroundColor White
