#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AgroNexus — First-time GKE + Cloud SQL PostgreSQL deployment script
# Run this once to set up the full infrastructure from scratch.
# After this, Cloud Build handles all subsequent deployments automatically.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated  (gcloud auth login)
#   - kubectl installed
#   - Docker installed
#   - GCP project created with billing enabled
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── EDIT THESE BEFORE RUNNING ────────────────────────────────────────────────
PROJECT_ID="agrinexus-farm"                       # GCP project ID
REGION="us-central1"                       # GCP region
CLUSTER="agronexus-cluster"               # GKE cluster name
DOMAIN="agrinuxes.com"                    # Spaceship domain
API_DOMAIN="api.agrinuxes.com"           # API subdomain
REPO="agronexus"                          # Artifact Registry repo name

# PostgreSQL settings
DB_INSTANCE="agronexus-db"               # Cloud SQL instance name
DB_NAME="agronexus"                       # PostgreSQL database name
DB_USER="agronexus_user"                 # PostgreSQL user
DB_TIER="db-g1-small"                    # db-f1-micro / db-g1-small / db-custom-2-7680
DB_VERSION="POSTGRES_15"
# ─────────────────────────────────────────────────────────────────────────────

VITE_API_URL="https://${API_DOMAIN}/graphql/"
SA_EMAIL="agronexus-sa@${PROJECT_ID}.iam.gserviceaccount.com"
DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          AgroNexus — GKE + PostgreSQL Deployment            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: GCP project and APIs ─────────────────────────────────────────────
echo "━━━ [1/10] Setting GCP project and enabling APIs ━━━"
gcloud config set project "$PROJECT_ID"

gcloud services enable \
  container.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  servicenetworking.googleapis.com

# ── Step 2: Artifact Registry ─────────────────────────────────────────────
echo ""
echo "━━━ [2/10] Creating Artifact Registry repository ━━━"
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --description="AgroNexus container images" 2>/dev/null || echo "  (already exists)"

# ── Step 3: Cloud SQL PostgreSQL ─────────────────────────────────────────────
echo ""
echo "━━━ [3/10] Provisioning Cloud SQL PostgreSQL 15 ━━━"
echo "  Instance : $DB_INSTANCE"
echo "  Tier     : $DB_TIER"
echo "  Region   : $REGION"
echo ""

# Create the instance (takes 3-5 minutes)
gcloud sql instances create "$DB_INSTANCE" \
  --database-version="$DB_VERSION" \
  --tier="$DB_TIER" \
  --region="$REGION" \
  --storage-type=SSD \
  --storage-size=20GB \
  --storage-auto-increase \
  --backup-start-time=02:00 \
  --retained-backups-count=7 \
  --deletion-protection \
  2>/dev/null || echo "  (instance already exists)"

# Create the database
echo "  Creating database '$DB_NAME'..."
gcloud sql databases create "$DB_NAME" \
  --instance="$DB_INSTANCE" 2>/dev/null || echo "  (database already exists)"

# Create the user with a generated password
echo "  Creating user '$DB_USER'..."
gcloud sql users create "$DB_USER" \
  --instance="$DB_INSTANCE" \
  --password="$DB_PASSWORD" 2>/dev/null || echo "  (user already exists — password NOT changed)"

# Build the DATABASE_URL using Cloud SQL Unix socket (used by the Cloud SQL proxy sidecar)
DB_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${DB_INSTANCE}"
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${DB_CONNECTION_NAME}"

echo ""
echo "  ✔ PostgreSQL ready"
echo "  Connection name : $DB_CONNECTION_NAME"
echo "  DATABASE_URL    : postgresql://${DB_USER}:***@/${DB_NAME}?host=/cloudsql/${DB_CONNECTION_NAME}"
echo ""
echo "  ⚠ SAVE this password somewhere safe — it won't be shown again:"
echo "  DB_PASSWORD=$DB_PASSWORD"
echo ""

# ── Step 4: GCS Media Bucket ─────────────────────────────────────────────────
echo "━━━ [4/10] Creating GCS media bucket ━━━"
gsutil mb -l "$REGION" "gs://agronexus-media-prod" 2>/dev/null || echo "  (already exists)"
gsutil uniformbucketlevelaccess set on "gs://agronexus-media-prod"

# ── Step 5: GCP Service Account + Workload Identity ──────────────────────────
echo ""
echo "━━━ [5/10] Setting up service account and IAM permissions ━━━"

gcloud iam service-accounts create agronexus-sa \
  --display-name="AgroNexus Workload Identity SA" 2>/dev/null || echo "  (already exists)"

# Cloud SQL access
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client" --quiet

# GCS media bucket access
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin" --quiet

# ── Step 6: GKE Cluster ───────────────────────────────────────────────────────
echo ""
echo "━━━ [6/10] Creating GKE Standard cluster ━━━"
gcloud container clusters create "$CLUSTER" \
  --region "$REGION" \
  --num-nodes 1 \
  --machine-type e2-standard-2 \
  --workload-pool="${PROJECT_ID}.svc.id.goog" \
  --enable-autoscaling --min-nodes 1 --max-nodes 4 \
  2>/dev/null || echo "  (cluster already exists)"

echo "  Getting credentials..."
gcloud container clusters get-credentials "$CLUSTER" --region "$REGION"

# Reserve a stable global IP for the Ingress (referenced in ingress.yaml as agronexus-ip)
echo "  Reserving global static IP address..."
gcloud compute addresses create agronexus-ip --global 2>/dev/null || echo "  (IP already reserved)"
STATIC_IP=$(gcloud compute addresses describe agronexus-ip --global --format="get(address)")
echo "  Static IP: $STATIC_IP  ← Point your DNS A records here"

# Bind GCP SA to K8s SA via Workload Identity
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[agronexus/agronexus-sa]" --quiet

# ── Step 7: Build and push Docker images ──────────────────────────────────────
echo ""
echo "━━━ [7/10] Building and pushing Docker images ━━━"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "  Building backend..."
docker build \
  --build-arg SECRET_KEY="build-time-dummy-key-not-used-in-production" \
  -t "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/backend:latest" \
  ./
docker push "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/backend:latest"

echo "  Building frontend..."
docker build \
  --build-arg "VITE_API_URL=${VITE_API_URL}" \
  -t "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/frontend:latest" \
  ../farm_frontend
docker push "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/frontend:latest"

# ── Step 8: Inject real values into K8s manifests ────────────────────────────
echo ""
echo "━━━ [8/10] Configuring Kubernetes manifests ━━━"
find k8s/ -name "*.yaml" -exec sed -i \
  -e "s|PROJECT_ID|${PROJECT_ID}|g" \
  -e "s|REGION|${REGION}|g" \
  -e "s|yourdomain\.com|${DOMAIN}|g" \
  -e "s|api\.yourdomain\.com|${API_DOMAIN}|g" \
  -e "s|agronexus-media-prod|agronexus-media-prod|g" {} \;

# Update Cloud SQL proxy instance connection name in deployments
sed -i "s|PROJECT_ID:REGION:agronexus-db|${DB_CONNECTION_NAME}|g" \
  k8s/backend/deployment.yaml \
  k8s/celery/worker-deployment.yaml \
  k8s/celery/beat-deployment.yaml

# Update configmap with real domain values
sed -i "s|api.yourdomain.com|${API_DOMAIN}|g" k8s/configmap.yaml
sed -i "s|https://yourdomain.com|https://${DOMAIN}|g" k8s/configmap.yaml
sed -i "s|noreply@yourdomain.com|noreply@${DOMAIN}|g" k8s/configmap.yaml

# ── Step 9: Apply Kubernetes resources ───────────────────────────────────────
echo ""
echo "━━━ [9/10] Applying Kubernetes manifests ━━━"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/configmap.yaml

# Auto-generate secrets (user will need Anthropic key and SendGrid key)
echo ""
echo "  Generating Django SECRET_KEY..."
DJANGO_SECRET=$(python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'!@#%^&*(-_=+)') for _ in range(60)))")
JWT_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

kubectl create secret generic agronexus-secrets \
  --namespace=agronexus \
  --from-literal=SECRET_KEY="$DJANGO_SECRET" \
  --from-literal=JWT_SIGNING_KEY="$JWT_KEY" \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --from-literal=ANTHROPIC_API_KEY="REPLACE_WITH_YOUR_ANTHROPIC_KEY" \
  --from-literal=EMAIL_HOST_USER="apikey" \
  --from-literal=EMAIL_HOST_PASSWORD="REPLACE_WITH_YOUR_SENDGRID_KEY" \
  2>/dev/null || echo "  (secret already exists — skipping)"

echo "  Deploying Redis..."
kubectl apply -f k8s/redis/

echo "  Deploying backend..."
kubectl apply -f k8s/backend/

echo "  Deploying Celery worker and beat..."
kubectl apply -f k8s/celery/

echo "  Deploying frontend..."
kubectl apply -f k8s/frontend/

echo "  Applying Ingress, HPA..."
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/serviceaccount.yaml

# ── Step 10: Run migrations ────────────────────────────────────────────────
echo ""
echo "━━━ [10/10] Running Django database migrations ━━━"
echo "  Waiting for backend pod to be ready..."
kubectl rollout status deployment/agronexus-backend -n agronexus --timeout=300s

BACKEND_POD=$(kubectl get pods -n agronexus -l app=agronexus-backend -o jsonpath='{.items[0].metadata.name}')
echo "  Running migrate on pod: $BACKEND_POD"
kubectl exec -n agronexus "$BACKEND_POD" -- python manage.py migrate --noinput

echo ""
echo "━━━ [Bonus] Setting up Cloud Build CI/CD trigger ━━━"
echo "  Connecting Cloud Build to your git repository..."
echo "  (This step requires you to have connected your repo in the GCP Console first)"
echo "  Go to: https://console.cloud.google.com/cloud-build/triggers"
echo "  Create a trigger pointing to cloudbuild.yaml with these substitutions:"
echo "    _REGION        = $REGION"
echo "    _PROJECT_ID    = $PROJECT_ID"
echo "    _CLUSTER       = $CLUSTER"
echo "    _VITE_API_URL  = $VITE_API_URL"
echo ""

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  Deployment Complete!                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  ⚠ IMPORTANT — Update these two secrets before going live:"
echo "    kubectl edit secret agronexus-secrets -n agronexus"
echo "    Change ANTHROPIC_API_KEY and EMAIL_HOST_PASSWORD to real values"
echo ""
echo "  Check rollout status:"
echo "    kubectl get pods -n agronexus"
echo "    kubectl rollout status deployment/agronexus-backend -n agronexus"
echo ""
echo "  Get external IP (takes 2-5 min after ingress is applied):"
echo "    kubectl get ingress -n agronexus"
echo ""
echo "  Point your DNS records to the IP above:"
echo "    A  ${DOMAIN}      → <EXTERNAL_IP>"
echo "    A  ${API_DOMAIN}  → <EXTERNAL_IP>"
echo ""
