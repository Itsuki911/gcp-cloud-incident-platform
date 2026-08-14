[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "asia-northeast1"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw "Google Cloud CLI is not installed or is not on PATH."
}

$activeAccount = gcloud auth list --filter=status:ACTIVE --format="value(account)"
if (-not $activeAccount) {
    gcloud auth login
}

gcloud config set project $ProjectId
gcloud config set run/region $Region
gcloud auth application-default login
gcloud auth application-default set-quota-project $ProjectId

gcloud services enable run.googleapis.com sqladmin.googleapis.com pubsub.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com

$topic = "incident-tickets"
$subscription = "incident-tickets-worker"

gcloud pubsub topics describe $topic --project $ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud pubsub topics create $topic --project $ProjectId
}

gcloud pubsub subscriptions describe $subscription --project $ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud pubsub subscriptions create $subscription --topic $topic --project $ProjectId
}

Write-Host "Google Cloud base configuration completed for $ProjectId in $Region."
Write-Host "Create the AI API secret and Cloud SQL instance after choosing credentials and billing settings."

