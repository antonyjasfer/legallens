# LegalLens — Cloud Run Production Deployment Script
# Deploys containerized LegalLens to Google Cloud Run with Secret Manager mounting and health verification.

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$ProjectId = "",

    [Parameter(Mandatory = $false)]
    [string]$Region = "us-central1",

    [Parameter(Mandatory = $false)]
    [string]$ServiceName = "legallens",

    [Parameter(Mandatory = $false)]
    [string]$BucketName = ""
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LegalLens — Cloud Run Production Deployment" -ForegroundColor Cyan
Write-Host "============================================================"

# 1. Determine Project
if (-not $ProjectId) {
    $ProjectId = gcloud config get-value project 2>$null
    if (-not $ProjectId) {
        Write-Error "No active GCP project found. Run 'gcloud config set project <PROJECT_ID>' or pass -ProjectId"
        exit 1
    }
}

if (-not $BucketName) {
    $BucketName = "legallens-docs-$ProjectId"
}

$saEmail = "legallens-runner@$ProjectId.iam.gserviceaccount.com"

Write-Host "Project ID:       $ProjectId" -ForegroundColor Green
Write-Host "Region:           $Region" -ForegroundColor Green
Write-Host "Service Name:     $ServiceName" -ForegroundColor Green
Write-Host "Cloud Storage:    $BucketName" -ForegroundColor Green
Write-Host "Service Account:  $saEmail" -ForegroundColor Green

# 2. Deploy from Source via Cloud Run buildpacks or Dockerfile
Write-Host "`nSubmitting build and deploying to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --source . `
    --project=$ProjectId `
    --region=$Region `
    --platform=managed `
    --allow-unauthenticated `
    --service-account=$saEmail `
    --set-env-vars="APP_ENV=production,GOOGLE_CLOUD_PROJECT=$ProjectId,GOOGLE_CLOUD_LOCATION=$Region,GCS_BUCKET=$BucketName,GEMINI_MODEL=gemini-3.8-flash,DOCUMENT_AI_ENABLED=false" `
    --set-secrets="GEMINI_API_KEY=legallens-gemini-api-key:latest" `
    --cpu=1 `
    --memory=1Gi `
    --timeout=120 `
    --concurrency=80 `
    --min-instances=0 `
    --max-instances=5

if ($LASTEXITCODE -ne 0) {
    Write-Error "Cloud Run deployment command failed."
    exit $LASTEXITCODE
}

# 3. Retrieve Deployed Service URL
$ServiceUrl = gcloud run services describe $ServiceName `
    --project=$ProjectId `
    --region=$Region `
    --format="value(status.url)"

Write-Host "`nDeployed Service URL: $ServiceUrl" -ForegroundColor Green

# 4. Automatically test health endpoints
Write-Host "`nRunning automated post-deployment health verification..." -ForegroundColor Yellow
try {
    Write-Host "Checking GET $ServiceUrl/api/health..." -NoNewline
    $healthResp = Invoke-RestMethod -Uri "$ServiceUrl/api/health" -Method Get
    Write-Host " OK ($($healthResp.status))" -ForegroundColor Green

    Write-Host "Checking GET $ServiceUrl/api/health/google..." -NoNewline
    $googleHealth = Invoke-RestMethod -Uri "$ServiceUrl/api/health/google" -Method Get
    Write-Host " OK" -ForegroundColor Green
    Write-Host "Gemini Reachable: $($googleHealth.gemini.reachable) (model: $($googleHealth.gemini.model))" -ForegroundColor Cyan
    Write-Host "File Search:      $($googleHealth.file_search.reachable)" -ForegroundColor Cyan
} catch {
    Write-Warning "Health verification check failed or service is still warming up: $_"
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "Production Deployment Complete: $ServiceUrl" -ForegroundColor Green
Write-Host "============================================================"
