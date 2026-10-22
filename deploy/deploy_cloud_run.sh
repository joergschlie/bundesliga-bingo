#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Google Cloud Run Deployment + Hard $0 Cost Kill-Switch Setup
# ==============================================================================
# NOTE: Google Cloud Run's Always-Free Tier is only available in:
#   us-central1, us-east1, or us-west1
# Deploying to us-central1 ensures 2M requests + 180k vCPU-seconds/month at $0.
# ==============================================================================

PROJECT_ID="${1:-}"
BILLING_ACCOUNT_ID="${2:-}"
REGION="us-central1"
SERVICE_NAME="bundesliga-bingo"
TOPIC_NAME="billing-killswitch-topic"
FUNCTION_NAME="stop-billing-killswitch"

if [[ -z "$PROJECT_ID" || -z "$BILLING_ACCOUNT_ID" ]]; then
  echo "Usage: ./deploy/deploy_cloud_run.sh <PROJECT_ID> <BILLING_ACCOUNT_ID>"
  echo "Example: ./deploy/deploy_cloud_run.sh my-bingo-2026 01ABCD-23EFGH-45IJKL"
  echo "Tip: Run 'gcloud beta billing accounts list' to see your BILLING_ACCOUNT_ID."
  exit 1
fi

echo "==> 1. Configuring GCP Project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

echo "==> 2. Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  cloudfunctions.googleapis.com \
  cloudbilling.googleapis.com \
  billingbudgets.googleapis.com

echo "==> 3. Deploying Streamlit App to Cloud Run (Strictly Capped at 1 Tiny Instance)..."
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=1 \
  --cpu=1 \
  --memory=512Mi \
  --cpu-throttling \
  --concurrency=20 \
  --timeout=60s

echo "==> 4. Creating Pub/Sub Topic for Budget Alert Kill-Switch..."
if ! gcloud pubsub topics describe "$TOPIC_NAME" >/dev/null 2>&1; then
  gcloud pubsub topics create "$TOPIC_NAME"
fi

echo "==> 5. Deploying Automated Billing Kill-Switch Function..."
gcloud functions deploy "$FUNCTION_NAME" \
  --region="$REGION" \
  --runtime=python312 \
  --source=./deploy/billing_killswitch \
  --entry-point=stop_billing \
  --trigger-topic="$TOPIC_NAME" \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},BILLING_ACCOUNT=${BILLING_ACCOUNT_ID}"

# Grant the function's service account permission to unlink billing on this project
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
SA_EMAIL="${PROJECT_ID}@appspot.gserviceaccount.com"
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SA in "$SA_EMAIL" "$COMPUTE_SA"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" \
    --role="roles/billing.projectManager" >/dev/null 2>&1 || true
done

echo "==> 6. Creating $0.05 Hard-Cap Budget Alert connected to Pub/Sub Kill-Switch..."
gcloud billing budgets create \
  --billing-account="$BILLING_ACCOUNT_ID" \
  --display-name="Bingo Zero-Cost Killswitch (${PROJECT_ID})" \
  --budget-amount=0.05USD \
  --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=1.0 \
  --notifications-rule-pubsub-topic="projects/${PROJECT_ID}/topics/${TOPIC_NAME}" || \
  echo "Budget already exists or must be confirmed in Cloud Console -> Billing -> Budgets & alerts."

echo ""
echo "=============================================================================="
echo "Deployment complete!"
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format="value(status.url)")
echo "Your public Bingo Tracker URL: $SERVICE_URL"
echo "=============================================================================="
