# BD News API — Google Cloud Run Deployment Guide

> **Region:** `asia-south1` (Mumbai — lowest latency to Bangladesh)  
> **Service name:** `bd-news-api`  
> **Image repo:** `bd-news-backend` (Artifact Registry)

---

## 1 — Prerequisites

```bash
# Install Google Cloud SDK if not already installed
# https://cloud.google.com/sdk/docs/install

# Verify install
gcloud --version

# Log in
gcloud auth login

# Set up Docker credential helper (needed for Artifact Registry push)
gcloud auth configure-docker asia-south1-docker.pkg.dev
```

---

## 2 — Create Project & Enable APIs

```bash
# Pick a project ID (must be globally unique — add a suffix if taken)
export PROJECT_ID=bd-news-archive

# Create the project
gcloud projects create $PROJECT_ID --name="BD News Archive"

# Set it as active
gcloud config set project $PROJECT_ID

# Link a billing account (required for Cloud Run)
# List your billing accounts first:
gcloud billing accounts list

# Then link (replace BILLING_ACCOUNT_ID with yours, e.g. 01A2B3-C4D5E6-F7G8H9):
gcloud billing projects link $PROJECT_ID \
  --billing-account=BILLING_ACCOUNT_ID

# Enable all required APIs in one shot
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  logging.googleapis.com
```

---

## 3 — Create Artifact Registry Repository

```bash
gcloud artifacts repositories create bd-news-backend \
  --repository-format=docker \
  --location=asia-south1 \
  --description="BD News API container images"
```

---

## 4 — Store All Secrets in Secret Manager

Run each block once. Paste the real value when prompted by `--data-file=-`.

### 4.1 MONGO_URI
```bash
echo -n "mongodb+srv://USER:PASS@cluster.mongodb.net/bd_news_archive?retryWrites=true&w=majority" \
  | gcloud secrets create MONGO_URI \
      --data-file=- \
      --replication-policy=automatic
```

### 4.2 MONGO_DB_NAME
```bash
echo -n "bd_news_archive" \
  | gcloud secrets create MONGO_DB_NAME \
      --data-file=- \
      --replication-policy=automatic
```

### 4.3 FIREBASE_CREDENTIALS
The value must be the **entire JSON object** on one line (no newlines inside).

```bash
# Option A — pipe from file (recommended — avoids shell escaping issues)
gcloud secrets create FIREBASE_CREDENTIALS \
  --data-file=/path/to/firebase-service-account.json \
  --replication-policy=automatic

# Option B — paste inline
cat /path/to/firebase-service-account.json \
  | gcloud secrets create FIREBASE_CREDENTIALS \
      --data-file=- \
      --replication-policy=automatic
```

### 4.4 OPENAI_API_KEY
```bash
echo -n "sk-proj-..." \
  | gcloud secrets create OPENAI_API_KEY \
      --data-file=- \
      --replication-policy=automatic
```

### 4.5 B2_KEY_ID
```bash
echo -n "your-b2-key-id" \
  | gcloud secrets create B2_KEY_ID \
      --data-file=- \
      --replication-policy=automatic
```

### 4.6 B2_APP_KEY
```bash
echo -n "your-b2-application-key" \
  | gcloud secrets create B2_APP_KEY \
      --data-file=- \
      --replication-policy=automatic
```

### 4.7 B2_BUCKET_NAME
```bash
echo -n "bd-news-archive" \
  | gcloud secrets create B2_BUCKET_NAME \
      --data-file=- \
      --replication-policy=automatic
```

### 4.8 B2_ENDPOINT
```bash
# Format: https://s3.us-west-004.backblazeb2.com  (check your B2 bucket settings)
echo -n "https://s3.REGION.backblazeb2.com" \
  | gcloud secrets create B2_ENDPOINT \
      --data-file=- \
      --replication-policy=automatic
```

### Verify all 8 secrets exist
```bash
gcloud secrets list
# Expected output: 8 rows — MONGO_URI, MONGO_DB_NAME, FIREBASE_CREDENTIALS,
# OPENAI_API_KEY, B2_KEY_ID, B2_APP_KEY, B2_BUCKET_NAME, B2_ENDPOINT
```

### Update a secret value later
```bash
# Example: rotate the OpenAI key
echo -n "sk-proj-NEW..." \
  | gcloud secrets versions add OPENAI_API_KEY --data-file=-
```

---

## 5 — Build & Test Docker Locally

```bash
# From the bd-news-backend directory
cd /path/to/bd-news-backend

# Build
docker build -t bd-news-api:local .

# Run locally with a .env file for testing
# Create .env with all 8 vars first, then:
docker run --rm -p 8080:8080 --env-file .env bd-news-api:local

# Smoke test
curl http://localhost:8080/
# Expected: {"status":"ok","message":"BD News Archive API"}

curl http://localhost:8080/sources
curl "http://localhost:8080/articles/bn?page=1"
```

---

## 6 — Push Image to Artifact Registry

```bash
export PROJECT_ID=bd-news-archive
export REGION=asia-south1
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api

# Tag
docker tag bd-news-api:local $IMAGE:latest

# Push
docker push $IMAGE:latest
```

---

## 7 — Grant Cloud Run Access to Secrets

Cloud Run runs as the **Compute Engine default service account**. Give it Secret Manager access before deploying.

```bash
export PROJECT_ID=bd-news-archive

# Get the project number
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Grant Secret Manager Secret Accessor to the default Compute SA
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## 8 — Deploy to Cloud Run

```bash
export PROJECT_ID=bd-news-archive
export REGION=asia-south1
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api:latest

gcloud run deploy bd-news-api \
  --image=$IMAGE \
  --platform=managed \
  --region=$REGION \
  --allow-unauthenticated \
  --port=8080 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=80 \
  --timeout=60 \
  --set-secrets="MONGO_URI=MONGO_URI:latest" \
  --set-secrets="MONGO_DB_NAME=MONGO_DB_NAME:latest" \
  --set-secrets="FIREBASE_CREDENTIALS=FIREBASE_CREDENTIALS:latest" \
  --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest" \
  --set-secrets="B2_KEY_ID=B2_KEY_ID:latest" \
  --set-secrets="B2_APP_KEY=B2_APP_KEY:latest" \
  --set-secrets="B2_BUCKET_NAME=B2_BUCKET_NAME:latest" \
  --set-secrets="B2_ENDPOINT=B2_ENDPOINT:latest"
```

> Cloud Run prints the service URL on success — it looks like  
> `https://bd-news-api-XXXXXXXXXXXX-as.a.run.app`

---

## 9 — Verify Deployment

```bash
# Get the deployed URL
export SERVICE_URL=$(gcloud run services describe bd-news-api \
  --platform=managed --region=asia-south1 \
  --format="value(status.url)")

echo $SERVICE_URL

# Health check
curl $SERVICE_URL/
# Expected: {"status":"ok","message":"BD News Archive API"}

# Test endpoints
curl "$SERVICE_URL/sources"
curl "$SERVICE_URL/articles/bn?page=1"
curl "$SERVICE_URL/articles/en?page=1"

# Check logs (last 50 lines)
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=bd-news-api" \
  --limit=50 \
  --format="value(textPayload)" \
  --project=$PROJECT_ID
```

---

## 10 — CI/CD: Auto-redeploy on Git Push (Cloud Build)

Create `bd-news-backend/cloudbuild.yaml`:

```yaml
steps:
  # Step 1 — build the image
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - build
      - -t
      - 'asia-south1-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api:$COMMIT_SHA'
      - -t
      - 'asia-south1-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api:latest'
      - .

  # Step 2 — push both tags
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '--all-tags',
           'asia-south1-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api']

  # Step 3 — deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - bd-news-api
      - --image=asia-south1-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api:$COMMIT_SHA
      - --platform=managed
      - --region=asia-south1
      - --quiet

options:
  logging: CLOUD_LOGGING_ONLY
```

Then create the trigger in Google Cloud Console:

```bash
# Or via CLI — connects to your GitHub repo
gcloud builds triggers create github \
  --name=bd-news-api-deploy \
  --repo-name=YOUR_GITHUB_REPO_NAME \
  --repo-owner=YOUR_GITHUB_USERNAME \
  --branch-pattern='^main$' \
  --build-config=bd-news-backend/cloudbuild.yaml \
  --included-files='bd-news-backend/**'
```

> **Note:** First-time GitHub connection must be done via Cloud Console UI:  
> Cloud Build → Triggers → Connect Repository → GitHub → authenticate.

Grant Cloud Build permission to deploy to Cloud Run:

```bash
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$PROJECT_NUMBER@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding \
  $PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --member="serviceAccount:$PROJECT_NUMBER@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

---

## 11 — Updating the API (One-Liner Redeploy)

After any code change, build → push → deploy in one command:

```bash
export PROJECT_ID=bd-news-archive
export REGION=asia-south1
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/bd-news-backend/api:latest

docker build -t $IMAGE . && \
docker push $IMAGE && \
gcloud run deploy bd-news-api \
  --image=$IMAGE \
  --platform=managed \
  --region=$REGION \
  --quiet
```

Or if CI/CD is set up, just:

```bash
git push origin main
# Cloud Build picks it up automatically
```

---

## 12 — Troubleshooting

### View logs (Cloud Console)
Cloud Run → bd-news-api → Logs tab — filter by severity.

### View logs (CLI)
```bash
# Live tail (last 100 entries)
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=bd-news-api" \
  --limit=100 --order=desc \
  --project=bd-news-archive

# Filter errors only
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=bd-news-api AND severity>=ERROR" \
  --limit=50 \
  --project=bd-news-archive
```

### MongoDB Atlas — allow Cloud Run IPs

Cloud Run uses dynamic IPs, so Atlas must allow **all IPs**:

1. Atlas Console → Network Access → Add IP Address
2. Enter `0.0.0.0/0` → Comment: `Cloud Run dynamic IPs` → Confirm

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `MONGO_URI is not set` | Secret not mounted | Check `--set-secrets` flags in deploy command |
| `FIREBASE_CREDENTIALS is not set` | Same as above | Same fix |
| `ServerSelectionTimeoutError` | Atlas IP not whitelisted | Add `0.0.0.0/0` to Atlas Network Access |
| `Container failed to start` | Port mismatch | Ensure `ENV PORT=8080` in Dockerfile and `--port=8080` in deploy |
| `403 PERMISSION_DENIED` on secrets | SA missing role | Re-run the IAM grant in Step 7 |
| `Image not found` | Wrong registry path | Verify `gcloud artifacts repositories list --location=asia-south1` |
| Cold-start timeout | `min-instances=0` + slow startup | Set `--min-instances=1` (adds ~$5/month) |

### Inspect a secret value (sanity check)
```bash
gcloud secrets versions access latest --secret=MONGO_URI
```

### Roll back to a previous revision
```bash
# List revisions
gcloud run revisions list --service=bd-news-api --region=asia-south1

# Route 100% traffic to a specific revision
gcloud run services update-traffic bd-news-api \
  --to-revisions=bd-news-api-REVISION_ID=100 \
  --region=asia-south1
```

---

## Quick Reference — All Commands

| Action | Command |
|---|---|
| Set active project | `gcloud config set project bd-news-archive` |
| List secrets | `gcloud secrets list` |
| Update a secret | `echo -n "VALUE" \| gcloud secrets versions add SECRET_NAME --data-file=-` |
| Get service URL | `gcloud run services describe bd-news-api --region=asia-south1 --format="value(status.url)"` |
| View logs | `gcloud logging read "resource.labels.service_name=bd-news-api" --limit=50` |
| One-liner redeploy | `docker build -t IMAGE . && docker push IMAGE && gcloud run deploy bd-news-api --image=IMAGE --region=asia-south1 --quiet` |
| Roll back | `gcloud run services update-traffic bd-news-api --to-revisions=REVISION=100 --region=asia-south1` |
| List revisions | `gcloud run revisions list --service=bd-news-api --region=asia-south1` |
| Describe service | `gcloud run services describe bd-news-api --region=asia-south1` |
| Delete service | `gcloud run services delete bd-news-api --region=asia-south1` |

---

## Cost Estimate (Cloud Run free tier)

| Resource | Free tier | Estimated usage |
|---|---|---|
| Cloud Run requests | 2M req/month | Well within free |
| Cloud Run CPU | 180K vCPU-sec/month | Well within free (low traffic) |
| Cloud Run memory | 360K GB-sec/month | Well within free |
| Artifact Registry | 0.5 GB/month | ~1 image, within free |
| Secret Manager | 6 secret versions free | 8 secrets, minimal cost |
| Cloud Build | 120 min/day free | Within free for small teams |
| **Estimated total** | | **$0–$1/month** |
