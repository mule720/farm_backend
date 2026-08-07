# AgroNexus — Deployment Guide

Step-by-step guide to deploy AgroNexus on Google Cloud Platform (GKE + Cloud SQL + GCS).

---

## Architecture

```
Internet → GKE Ingress (HTTPS) → Frontend (nginx) / Backend (Django/gunicorn)
                                         ↓                     ↓
                                   Cloud Storage (GCS)   Cloud SQL (PostgreSQL 15)
                                                              ↑
                                                       Cloud SQL Auth Proxy (sidecar)
                                                              ↑
                                                     Celery Worker + Beat (same image)
                                                              ↑
                                                         Redis (in-cluster)
```

---

## Prerequisites

Install these on your machine before running anything:

```bash
# 1. Google Cloud SDK
# https://cloud.google.com/sdk/docs/install
gcloud --version

# 2. kubectl
gcloud components install kubectl

# 3. Docker Desktop
docker --version

# 4. GitHub CLI (optional, for repo setup)
gh --version
```

---

## Step 1 — GCP Project Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project.
2. Enable billing on the project.
3. Note your **Project ID** (e.g. `agronexus-prod-123456`).

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

---

## Step 2 — Edit deploy.sh

Open `deploy.sh` and set your values at the top:

```bash
PROJECT_ID="your-gcp-project-id"    # from Step 1
REGION="us-central1"                # pick the closest GCP region
DOMAIN="yourdomain.com"             # your real domain
API_DOMAIN="api.yourdomain.com"     # subdomain for the backend API
```

---

## Step 3 — Run the First-Time Deploy Script

```bash
chmod +x deploy.sh
./deploy.sh
```

This script (takes ~10 minutes) will:

| Step | What it does |
|------|-------------|
| 1 | Enable all required GCP APIs |
| 2 | Create Artifact Registry Docker repository |
| 3 | Provision Cloud SQL PostgreSQL 15 (db-g1-small, 20GB SSD) |
| 4 | Create GCS media bucket |
| 5 | Create GCP service account + IAM roles (Cloud SQL, GCS) |
| 6 | Create GKE Standard cluster (e2-standard-2, 1-4 nodes, Workload Identity) |
| 7 | Reserve global static IP, bind Workload Identity |
| 8 | Build and push backend + frontend Docker images |
| 9 | Apply all Kubernetes manifests |
| 10 | Run Django migrations |

> ⚠ **Save the `DB_PASSWORD`** printed by the script — it's generated once and not shown again.

---

## Step 4 — Point DNS Records

After Step 3, get your static IP:

```bash
kubectl get ingress -n agronexus
# or
gcloud compute addresses describe agronexus-ip --global --format="get(address)"
```

Create two DNS `A` records at your domain registrar:

| Name | Type | Value |
|------|------|-------|
| `@` (or `yourdomain.com`) | A | `<STATIC_IP>` |
| `api` | A | `<STATIC_IP>` |

The GKE ManagedCertificate will auto-provision SSL — takes **10–15 minutes** after DNS propagates.

---

## Step 5 — Update Secrets

After first deploy, replace the placeholder API keys:

```bash
# Get the current secret (to see what's there)
kubectl get secret agronexus-secrets -n agronexus -o yaml

# Update Anthropic API key
kubectl patch secret agronexus-secrets -n agronexus \
  -p '{"data":{"ANTHROPIC_API_KEY":"'$(echo -n "sk-ant-YOUR_KEY" | base64)'"}}'

# Update SendGrid API key
kubectl patch secret agronexus-secrets -n agronexus \
  -p '{"data":{"EMAIL_HOST_PASSWORD":"'$(echo -n "SG.YOUR_KEY" | base64)'"}}'
```

---

## Step 6 — Create the Platform Admin User

Run the superuser job (edit the values first):

```bash
# Edit the job to set your admin email, name, and password
nano k8s/jobs/migrate.yaml   # find DJANGO_SUPERUSER_* env vars

# Apply it
kubectl delete job agronexus-createsuperuser -n agronexus --ignore-not-found
kubectl apply -f k8s/jobs/migrate.yaml
kubectl logs -f job/agronexus-createsuperuser -n agronexus
```

---

## Step 7 — Set Up CI/CD (GitHub Actions)

The `.github/workflows/deploy.yml` workflow deploys automatically on every push to `main`.

### Required GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|--------|-------------|
| `GCP_PROJECT_ID` | Your GCP Project ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider (see below) |
| `GCP_SERVICE_ACCOUNT` | `github-deploy@YOUR_PROJECT_ID.iam.gserviceaccount.com` |
| `VITE_API_URL` | `https://api.yourdomain.com/graphql/` (frontend only) |

### Set up Workload Identity Federation for GitHub Actions

```bash
PROJECT_ID="your-gcp-project-id"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="get(projectNumber)")

# Create a WIF pool for GitHub
gcloud iam workload-identity-pools create "github-pool" \
  --project=$PROJECT_ID \
  --location="global" \
  --display-name="GitHub Actions Pool"

# Create a WIF provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# Create a deploy service account
gcloud iam service-accounts create github-deploy \
  --project=$PROJECT_ID \
  --display-name="GitHub Actions Deploy SA"

# Grant it required roles
for ROLE in roles/container.developer roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=$ROLE --quiet
done

# Allow GitHub to impersonate this SA
gcloud iam service-accounts add-iam-policy-binding \
  "github-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/mule720/farm_backend"

# Get the WIF provider name (put this in GCP_WORKLOAD_IDENTITY_PROVIDER secret)
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
```

---

## Useful Commands

```bash
# View all pods
kubectl get pods -n agronexus

# View logs
kubectl logs -f deployment/agronexus-backend -n agronexus
kubectl logs -f deployment/agronexus-celery-worker -n agronexus

# Run a Django shell in the cluster
kubectl exec -it deployment/agronexus-backend -n agronexus -c backend -- python manage.py shell

# Run a migration manually
kubectl delete job agronexus-migrate -n agronexus --ignore-not-found
kubectl apply -f k8s/jobs/migrate.yaml
kubectl wait job/agronexus-migrate --for=condition=complete --timeout=180s -n agronexus

# Scale backend pods
kubectl scale deployment agronexus-backend --replicas=3 -n agronexus

# Check ingress and TLS status
kubectl get ingress -n agronexus
kubectl describe managedcertificate agronexus-cert -n agronexus

# Check HPA status
kubectl get hpa -n agronexus
```

---

## Cost Estimate (10 heavy users, ~$320/month)

| Service | Config | Est. Cost |
|---------|--------|-----------|
| GKE Standard cluster | 2× e2-standard-2 (auto 1-4) | ~$100/mo |
| Cloud SQL PostgreSQL | db-g1-small, 20GB SSD | ~$30/mo |
| Cloud Load Balancer | Global HTTP(S) | ~$20/mo |
| Artifact Registry | ~5GB images | ~$5/mo |
| Cloud Storage (GCS) | 10GB media | ~$2/mo |
| Cloud Build | ~30 builds/mo | ~$5/mo |
| Networking | Egress | ~$10/mo |
| **Buffer** | | ~$148/mo |
| **Total** | | **~$320/mo** |

---

## Repository Structure (farm_backend)

```
farm_backend/
├── apps/               # 21 Django apps
├── config/             # Django settings, urls, schema, wsgi
├── k8s/                # Kubernetes manifests
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml      (reference only — real values in K8s)
│   ├── serviceaccount.yaml
│   ├── ingress.yaml
│   ├── hpa.yaml
│   ├── backend/
│   ├── celery/
│   ├── frontend/
│   ├── redis/
│   └── jobs/
│       └── migrate.yaml
├── .github/workflows/  # GitHub Actions CI/CD
├── Dockerfile
├── gunicorn.conf.py
├── cloudbuild.yaml     # Google Cloud Build CI/CD
├── deploy.sh           # First-time GCP setup script
├── requirements.txt
└── DEPLOYMENT.md       # This file
```
