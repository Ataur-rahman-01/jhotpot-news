#!/usr/bin/env bash
# setup_gcp.sh — One-time Google Cloud Platform setup for BD News scraper.
#
# Run once from your local machine BEFORE pushing code:
#   export GCP_PROJECT_ID=your-project-id
#   export MONGO_URI="mongodb+srv://..."
#   export OPENAI_API_KEY="sk-..."
#   export B2_KEY_ID="..."
#   export B2_APP_KEY="..."
#   export B2_BUCKET_NAME="bd-news-archive"
#   export B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com"
#   bash setup_gcp.sh
#
# Prerequisites:
#   - gcloud CLI installed (https://cloud.google.com/sdk/docs/install)
#   - gcloud auth login && gcloud auth application-default login
#   - Docker installed and running
#   - GCP project already created at console.cloud.google.com
#
# What this script creates (all idempotent — safe to re-run):
#   - Enables required GCP APIs
#   - Artifact Registry repository: bd-news
#   - Service accounts: scraper SA + scheduler SA + deploy SA
#   - IAM role bindings
#   - Workload Identity Federation pool + provider (for GitHub Actions)
#   - Secrets in Secret Manager
#   - Initial Docker image build + push
#   - Cloud Run Jobs: group-a, group-b, archiver
#   - Cloud Scheduler jobs: triggers at :00, :30, midnight UTC

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="asia-south1"
REPOSITORY="bd-news"
IMAGE="scraper"

SCRAPER_SA="bd-news-scraper-sa"
SCHEDULER_SA="bd-news-scheduler-sa"
DEPLOY_SA="bd-news-deploy-sa"

GITHUB_REPO="${GITHUB_REPO:-}"   # e.g. "your-username/jhotpot-news"

# Secret values (set as env vars before running, or edit here)
MONGO_URI="${MONGO_URI:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
B2_KEY_ID="${B2_KEY_ID:-}"
B2_APP_KEY="${B2_APP_KEY:-}"
B2_BUCKET_NAME="${B2_BUCKET_NAME:-}"
B2_ENDPOINT="${B2_ENDPOINT:-}"
FIREBASE_CREDENTIALS="${FIREBASE_CREDENTIALS:-}"   # full JSON from Firebase console (as a string)

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: set GCP_PROJECT_ID env var before running."
  exit 1
fi

IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$IMAGE:latest"
SCRAPER_SA_EMAIL="$SCRAPER_SA@$PROJECT_ID.iam.gserviceaccount.com"
SCHEDULER_SA_EMAIL="$SCHEDULER_SA@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOY_SA_EMAIL="$DEPLOY_SA@$PROJECT_ID.iam.gserviceaccount.com"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════╗"
echo "║    BD News — GCP one-time setup              ║"
echo "╚══════════════════════════════════════════════╝"
echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Image   : $IMAGE_URL"
echo ""

# ── 1. Set default project ────────────────────────────────────────────────────
gcloud config set project "$PROJECT_ID"

# ── 2. Enable APIs ───────────────────────────────────────────────────────────
echo "[1/8] Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com
echo "  done."

# ── 3. Artifact Registry repo ─────────────────────────────────────────────────
echo "[2/8] Artifact Registry repository..."
if gcloud artifacts repositories describe "$REPOSITORY" --location="$REGION" &>/dev/null; then
  echo "  already exists — skipped."
else
  gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format=docker \
    --location="$REGION" \
    --description="BD News scraper Docker images"
  echo "  created."
fi

# ── 4. Service accounts ───────────────────────────────────────────────────────
echo "[3/8] Service accounts..."

ensure_sa() {
  local sa="$1" display="$2"
  local email="$sa@$PROJECT_ID.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "$email" &>/dev/null; then
    echo "  $sa — already exists."
  else
    gcloud iam service-accounts create "$sa" --display-name="$display"
    echo "  $sa — created."
  fi
}

ensure_sa "$SCRAPER_SA"   "BD News Scraper (Cloud Run Jobs)"
ensure_sa "$SCHEDULER_SA" "BD News Scheduler (triggers Cloud Run Jobs)"
ensure_sa "$DEPLOY_SA"    "BD News Deploy (GitHub Actions CI/CD)"

# ── 5. IAM role bindings ──────────────────────────────────────────────────────
echo "[4/8] IAM role bindings..."

bind_role() {
  local member="$1" role="$2"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="$member" --role="$role" --quiet
}

# Scraper SA: read secrets + pull images
bind_role "serviceAccount:$SCRAPER_SA_EMAIL" "roles/secretmanager.secretAccessor"
bind_role "serviceAccount:$SCRAPER_SA_EMAIL" "roles/artifactregistry.reader"

# Scheduler SA: trigger Cloud Run Jobs
bind_role "serviceAccount:$SCHEDULER_SA_EMAIL" "roles/run.developer"

# Deploy SA: submit Cloud Builds, push images, update Cloud Run Jobs
bind_role "serviceAccount:$DEPLOY_SA_EMAIL" "roles/cloudbuild.builds.editor"
bind_role "serviceAccount:$DEPLOY_SA_EMAIL" "roles/artifactregistry.writer"
bind_role "serviceAccount:$DEPLOY_SA_EMAIL" "roles/run.developer"

# Cloud Build SA: push images to Artifact Registry
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
bind_role "serviceAccount:$PROJECT_NUMBER@cloudbuild.gserviceaccount.com" "roles/artifactregistry.writer"

echo "  done."

# ── 6. Workload Identity Federation (GitHub Actions → GCP, no key files) ──────
echo "[5/8] Workload Identity Federation..."

WIF_POOL="github-actions-pool"
WIF_PROVIDER="github-provider"
WIF_POOL_FULL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL"

if gcloud iam workload-identity-pools describe "$WIF_POOL" --location=global &>/dev/null; then
  echo "  pool '$WIF_POOL' already exists."
else
  gcloud iam workload-identity-pools create "$WIF_POOL" \
    --location=global \
    --display-name="GitHub Actions pool"
  echo "  pool created."
fi

if gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
    --workload-identity-pool="$WIF_POOL" --location=global &>/dev/null; then
  echo "  provider '$WIF_PROVIDER' already exists."
else
  gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
    --workload-identity-pool="$WIF_POOL" \
    --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
    --attribute-condition="assertion.repository_owner=='$(echo "${GITHUB_REPO:-unknown/unknown}" | cut -d/ -f1)'"
  echo "  provider created."
fi

# Allow Deploy SA to be impersonated by GitHub Actions runs from this repo
if [[ -n "$GITHUB_REPO" ]]; then
  gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA_EMAIL" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/$WIF_POOL_FULL/attribute.repository/$GITHUB_REPO" \
    --quiet
  echo "  bound deploy SA to repo: $GITHUB_REPO"
else
  echo "  SKIP: GITHUB_REPO not set — bind manually:"
  echo "    gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA_EMAIL \\"
  echo "      --role=roles/iam.workloadIdentityUser \\"
  echo "      --member=\"principalSet://iam.googleapis.com/$WIF_POOL_FULL/attribute.repository/OWNER/REPO\""
fi

# ── 7. Secret Manager ─────────────────────────────────────────────────────────
echo "[6/8] Secrets in Secret Manager..."

store_secret() {
  local name="$1" value="$2"
  if [[ -z "$value" ]]; then
    echo "  SKIP $name — value not set. Add it manually:"
    echo "    echo -n 'VALUE' | gcloud secrets versions add $name --data-file=-"
    echo "    (create first if needed: gcloud secrets create $name --replication-policy=automatic)"
    return
  fi
  if gcloud secrets describe "$name" &>/dev/null; then
    echo -n "$value" | gcloud secrets versions add "$name" --data-file=-
    echo "  $name — new version added."
  else
    gcloud secrets create "$name" --replication-policy=automatic
    echo -n "$value" | gcloud secrets versions add "$name" --data-file=-
    echo "  $name — created."
  fi
}

store_secret "MONGO_URI"             "$MONGO_URI"
store_secret "OPENAI_API_KEY"        "$OPENAI_API_KEY"
store_secret "B2_KEY_ID"             "$B2_KEY_ID"
store_secret "B2_APP_KEY"            "$B2_APP_KEY"
store_secret "B2_BUCKET_NAME"        "$B2_BUCKET_NAME"
store_secret "B2_ENDPOINT"           "$B2_ENDPOINT"
store_secret "FIREBASE_CREDENTIALS"  "$FIREBASE_CREDENTIALS"

# ── 8. Build & push initial Docker image via Cloud Build (no local Docker needed)
echo "[7/8] Docker image (building via Cloud Build)..."
gcloud builds submit "$SCRIPT_DIR" \
  --config="$SCRIPT_DIR/cloudbuild.yaml" \
  --substitutions="_IMAGE_URL=$IMAGE_URL" \
  --region="$REGION" \
  --quiet
echo "  pushed: $IMAGE_URL"

# ── 9. Cloud Run Jobs ─────────────────────────────────────────────────────────
echo "[8/8] Cloud Run Jobs + Cloud Scheduler..."

SECRET_REFS="MONGO_URI=MONGO_URI:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,B2_KEY_ID=B2_KEY_ID:latest,B2_APP_KEY=B2_APP_KEY:latest,B2_BUCKET_NAME=B2_BUCKET_NAME:latest,B2_ENDPOINT=B2_ENDPOINT:latest"

create_or_update_job() {
  local job_name="$1"
  local args="$2"
  local timeout="$3"

  if gcloud run jobs describe "$job_name" --region="$REGION" &>/dev/null; then
    gcloud run jobs update "$job_name" \
      --image="$IMAGE_URL" \
      --region="$REGION" \
      --quiet
    echo "  $job_name — updated image."
  else
    gcloud run jobs create "$job_name" \
      --image="$IMAGE_URL" \
      --region="$REGION" \
      --service-account="$SCRAPER_SA_EMAIL" \
      --args="$args" \
      --set-secrets="$SECRET_REFS" \
      --memory=512Mi \
      --cpu=1 \
      --task-timeout="$timeout" \
      --max-retries=1 \
      --quiet
    echo "  $job_name — created."
  fi
}

create_or_update_job "bd-news-scraper-group-a" "-m,scraper.main,--group,a" "600s"
create_or_update_job "bd-news-scraper-group-b" "-m,scraper.main,--group,b" "600s"
create_or_update_job "bd-news-archiver"        "-m,archive.archiver,--mode,size-check" "1800s"

# ── 10. Cloud Scheduler ───────────────────────────────────────────────────────
create_or_update_scheduler() {
  local name="$1"
  local schedule="$2"
  local job_name="$3"
  local uri="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$job_name:run"

  if gcloud scheduler jobs describe "$name" --location="$REGION" &>/dev/null; then
    gcloud scheduler jobs update http "$name" \
      --location="$REGION" \
      --schedule="$schedule" \
      --uri="$uri" \
      --quiet
    echo "  scheduler/$name — updated."
  else
    gcloud scheduler jobs create http "$name" \
      --location="$REGION" \
      --schedule="$schedule" \
      --uri="$uri" \
      --http-method=POST \
      --oauth-service-account-email="$SCHEDULER_SA_EMAIL" \
      --time-zone="UTC" \
      --attempt-deadline=30m \
      --quiet
    echo "  scheduler/$name — created."
  fi
}

# Group A  — every hour at :00 UTC
create_or_update_scheduler "bd-news-scrape-group-a" "0 * * * *"  "bd-news-scraper-group-a"
# Group B  — every hour at :30 UTC
create_or_update_scheduler "bd-news-scrape-group-b" "30 * * * *" "bd-news-scraper-group-b"
# Archiver — every day at midnight UTC
create_or_update_scheduler "bd-news-archive"        "0 0 * * *"  "bd-news-archiver"

# ── 11. FastAPI Cloud Run Service ─────────────────────────────────────────────
echo "[+] FastAPI Cloud Run Service..."

API_IMAGE_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/api:latest"
API_SECRET_REFS="MONGO_URI=MONGO_URI:latest,FIREBASE_CREDENTIALS=FIREBASE_CREDENTIALS:latest,B2_KEY_ID=B2_KEY_ID:latest,B2_APP_KEY=B2_APP_KEY:latest,B2_BUCKET_NAME=B2_BUCKET_NAME:latest,B2_ENDPOINT=B2_ENDPOINT:latest"

# Build and push API image using Cloud Build
API_CLOUDBUILD="$SCRIPT_DIR/cloudbuild.api.yaml"
cat > "$API_CLOUDBUILD" <<'YAML'
steps:
  - name: gcr.io/cloud-builders/docker
    args: [build, -f, Dockerfile, -t, $_IMAGE_URL, .]
images:
  - $_IMAGE_URL
options:
  logging: CLOUD_LOGGING_ONLY
YAML

gcloud builds submit "$SCRIPT_DIR" \
  --config="$API_CLOUDBUILD" \
  --substitutions="_IMAGE_URL=$API_IMAGE_URL" \
  --region="$REGION" \
  --quiet
echo "  API image pushed: $API_IMAGE_URL"

# Grant scraper SA access to FIREBASE_CREDENTIALS (API service uses scraper SA)
# Actually create a dedicated API SA
API_SA="bd-news-api-sa"
API_SA_EMAIL="$API_SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts describe "$API_SA_EMAIL" &>/dev/null || \
  gcloud iam service-accounts create "$API_SA" --display-name="BD News API Service Account"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$API_SA_EMAIL" \
  --role="roles/secretmanager.secretAccessor" --quiet

# Deploy or update the Cloud Run Service
if gcloud run services describe "bd-news-api" --region="$REGION" &>/dev/null; then
  gcloud run services update "bd-news-api" \
    --image="$API_IMAGE_URL" \
    --region="$REGION" \
    --quiet
  echo "  bd-news-api — updated."
else
  gcloud run deploy "bd-news-api" \
    --image="$API_IMAGE_URL" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --service-account="$API_SA_EMAIL" \
    --set-secrets="$API_SECRET_REFS" \
    --min-instances=0 \
    --max-instances=10 \
    --memory=512Mi \
    --cpu=1 \
    --port=8080 \
    --quiet
  echo "  bd-news-api — created."
fi

API_URL=$(gcloud run services describe "bd-news-api" --region="$REGION" --format="value(status.url)")
echo "  API URL: $API_URL"

# ── Done ──────────────────────────────────────────────────────────────────────
WIF_PROVIDER_FULL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/providers/$WIF_PROVIDER"

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                                 ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "API URL (use this in your Flutter app):"
echo "  $API_URL"
echo ""
echo "Cloud Run Jobs:"
gcloud run jobs list --region="$REGION" --format="table(name,region,lastModifiedTime)"
echo ""
echo "Cloud Scheduler:"
gcloud scheduler jobs list --location="$REGION" --format="table(name,schedule,state)"
echo ""
echo "Add these 3 secrets to GitHub → Settings → Secrets → Actions:"
echo ""
echo "  GCP_PROJECT_ID                 = $PROJECT_ID"
echo "  GCP_SERVICE_ACCOUNT            = $DEPLOY_SA_EMAIL"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER = $WIF_PROVIDER_FULL"
echo ""
echo "Monitor at:"
echo "  https://console.cloud.google.com/run?project=$PROJECT_ID"
echo "  https://console.cloud.google.com/cloudscheduler?project=$PROJECT_ID"
