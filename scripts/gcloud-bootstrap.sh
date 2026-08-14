#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:?Usage: ./scripts/gcloud-bootstrap.sh PROJECT_ID [REGION]}"
REGION="${2:-asia-northeast1}"
TOPIC="incident-tickets"
SUBSCRIPTION="incident-tickets-worker"

command -v gcloud >/dev/null 2>&1 || {
  echo "Google Cloud CLI is not installed or is not on PATH." >&2
  exit 1
}

if [[ -z "$(gcloud auth list --filter=status:ACTIVE --format='value(account)')" ]]; then
  gcloud auth login
fi

gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
gcloud auth application-default login
gcloud auth application-default set-quota-project "${PROJECT_ID}"

gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

gcloud pubsub topics describe "${TOPIC}" --project "${PROJECT_ID}" >/dev/null 2>&1 || \
  gcloud pubsub topics create "${TOPIC}" --project "${PROJECT_ID}"

gcloud pubsub subscriptions describe "${SUBSCRIPTION}" --project "${PROJECT_ID}" >/dev/null 2>&1 || \
  gcloud pubsub subscriptions create "${SUBSCRIPTION}" --topic "${TOPIC}" --project "${PROJECT_ID}"

echo "Google Cloud base configuration completed for ${PROJECT_ID} in ${REGION}."
echo "Create the AI API secret and Cloud SQL instance after choosing credentials and billing settings."

