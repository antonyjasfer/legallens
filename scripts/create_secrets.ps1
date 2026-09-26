# LegalLens — Google Secret Manager Setup Script (Windows PowerShell)
# Creates and configures GEMINI_API_KEY in Google Secret Manager without leaking secrets.

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$ProjectId = "",

    [Parameter(Mandatory = $false)]
    [string]$SecretName = "legallens-gemini-api-key"
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "LegalLens — Google Secret Manager Provisioning" -ForegroundColor Cyan
Write-Host "============================================================"

# 1. Determine Project ID
if (-not $ProjectId) {
    $ProjectId = gcloud config get-value project 2>$null
    if (-not $ProjectId) {
        Write-Error "No active GCP project found. Run 'gcloud config set project <PROJECT_ID>' or pass -ProjectId"
        exit 1
    }
}
Write-Host "Using GCP Project: $ProjectId" -ForegroundColor Green

# 2. Enable Secret Manager API
Write-Host "Enabling Secret Manager API..." -ForegroundColor Yellow
gcloud services enable secretmanager.googleapis.com --project=$ProjectId

# 3. Prompt for API key securely if not in environment
$ApiKey = $env:GEMINI_API_KEY
if (-not $ApiKey) {
    if (Test-Path ".env") {
        $line = Get-Content ".env" | Where-Object { $_ -match "^GEMINI_API_KEY=(.+)$" }
        if ($line) {
            $ApiKey = $line.Substring(15).Trim()
        }
    }
}

if (-not $ApiKey) {
    $SecureKey = Read-Host -Prompt "Enter your Google Gemini API Key" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
    $ApiKey = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

if (-not $ApiKey) {
    Write-Error "Gemini API key is required to create secret."
    exit 1
}

# 4. Check if secret exists or create it
$secretExists = gcloud secrets describe $SecretName --project=$ProjectId 2>$null
if (-not $secretExists) {
    Write-Host "Creating secret '$SecretName'..." -ForegroundColor Yellow
    gcloud secrets create $SecretName `
        --project=$ProjectId `
        --replication-policy="automatic" `
        --labels="application=legallens,environment=production"
} else {
    Write-Host "Secret '$SecretName' already exists." -ForegroundColor Green
}

# 5. Add secret version via standard input (never passed as command line argument)
Write-Host "Adding secret version safely via stdin (value not printed in logs)..." -ForegroundColor Yellow
$ApiKey | gcloud secrets versions add $SecretName --data-file=- --project=$ProjectId

Write-Host "`nSecret Manager provisioning complete!" -ForegroundColor Green
Write-Host "Secret Resource: projects/$ProjectId/secrets/$SecretName" -ForegroundColor Cyan
